"""One OpenTelemetry pipeline, two backends.

Spans are produced once (FastAPI server span, Strands agent/LLM/tool spans, httpx
client span to the AI gateway) and exported twice:

  * Dynatrace (OTLP/HTTP, Api-Token)  -> SRE / ops view, gen_ai.* semantic conventions
  * Arize AX  (OTLP/HTTP, space key)   -> AI engineering view, OpenInference attributes

The OpenInference Strands processor runs first and *adds* llm.* / openinference.*
attributes while keeping the original gen_ai.* ones, so both backends get what they
understand from the same span with the same trace and span IDs.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

log = logging.getLogger(__name__)

_provider: TracerProvider | None = None


def _dynatrace_exporter() -> OTLPSpanExporter | None:
    url, token = os.getenv("DT_ENV_URL"), os.getenv("DT_INGEST_TOKEN")
    if not (url and token):
        log.warning("Dynatrace export disabled (DT_ENV_URL / DT_INGEST_TOKEN not set)")
        return None
    return OTLPSpanExporter(
        endpoint=f"{url.rstrip('/')}/api/v2/otlp/v1/traces",
        headers={"Authorization": f"Api-Token {token}"},
    )


def _arize_exporter() -> OTLPSpanExporter | None:
    space, key = os.getenv("ARIZE_SPACE_ID"), os.getenv("ARIZE_API_KEY")
    if not (space and key):
        log.warning("Arize export disabled (ARIZE_SPACE_ID / ARIZE_API_KEY not set)")
        return None
    return OTLPSpanExporter(
        endpoint="https://otlp.arize.com/v1/traces",
        headers={"authorization": key, "arize-space-id": space},
    )


def setup(service_name: str) -> TracerProvider:
    """Idempotent. Call once at import time of each entry point."""
    global _provider
    if _provider is not None:
        return _provider

    # Strands: put prompts/completions on span attributes (gen_ai latest conventions)
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "v2-ai-demo",
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "local"),
            # Arize routes spans to a project by this resource attribute
            "openinference.project.name": os.getenv("ARIZE_PROJECT_NAME", "v2-ai-demo"),
        }
    )
    provider = TracerProvider(resource=resource)

    # 1) Enrich Strands spans with OpenInference attributes (must run before exporters)
    from openinference.instrumentation.strands_agents import StrandsAgentsToOpenInferenceProcessor

    provider.add_span_processor(StrandsAgentsToOpenInferenceProcessor())

    # 2) Fan out to both backends
    for exporter in (_dynatrace_exporter(), _arize_exporter()):
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=1000))

    trace.set_tracer_provider(provider)

    # httpx client spans + W3C traceparent injection on calls to the AI gateway
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()

    _provider = provider
    return provider


def flush(timeout_ms: int = 5000) -> None:
    """Lambda freezes the process after the response; flush before returning."""
    if _provider is not None:
        _provider.force_flush(timeout_ms)
