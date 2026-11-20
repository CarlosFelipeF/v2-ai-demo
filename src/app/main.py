"""Claims assistant web app: serves the chat page and the /api/ask endpoint.

Runs locally with uvicorn and on AWS Lambda via Mangum (same code).
Trace flow: browser (Dynatrace RUM, W3C traceparent) -> this FastAPI server span
-> Strands agent spans -> httpx span to the AI gateway (traceparent injected).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from . import telemetry

telemetry.setup(os.getenv("OTEL_SERVICE_NAME", "claims-app"))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from .agent import build_agent  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("claims-app")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Southern Cross Mutual - Claims Assistant")


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    scenario: str | None = None  # set by the load generator, shows up as a span attribute


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html = (WEB_DIR / "index.html").read_text()
    return html.replace("<!--DT_RUM_SNIPPET-->", os.getenv("DT_RUM_SNIPPET", ""))


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/ask")
async def ask(body: Ask, request: Request) -> JSONResponse:
    span = trace.get_current_span()
    span.set_attribute("app.session_id", body.session_id or "")
    span.set_attribute("app.scenario", body.scenario or "interactive")
    span.set_attribute("app.traffic", "synthetic" if body.scenario else "user")

    started = time.perf_counter()
    try:
        agent = build_agent()
        result = await agent.invoke_async(body.question)
        answer = str(result).strip()
    except Exception as exc:  # gateway down / chaos / model error
        log.exception("agent failed")
        span.record_exception(exc)
        raise HTTPException(status_code=502, detail="The assistant is unavailable right now.") from exc
    finally:
        telemetry.flush()

    ctx = span.get_span_context()
    return JSONResponse(
        {
            "answer": answer,
            "trace_id": format(ctx.trace_id, "032x"),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    )


FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")

# AWS Lambda entry point
try:
    from mangum import Mangum

    handler = Mangum(app, lifespan="off")
except ImportError:  # pragma: no cover
    handler = None
