"""API load generator — produces telemetry without anyone clicking.

Local:   uv run python -m loadgen.run --mode normal        (loops forever)
         uv run python -m loadgen.run --once 20            (20 requests, then exit)
Lambda:  handler(event, context)  — EventBridge Scheduler invokes it; event may carry
         {"count": 3}. Modes are applied by changing the schedule rate (scripts/loadgen.sh).

Each request starts a fresh client trace (span "loadgen.ask") so every synthetic
question is its own end-to-end trace: loadgen -> app -> agent -> gateway -> Bedrock.
"""

from __future__ import annotations

import argparse
import os
import random
import time
import uuid
from pathlib import Path

import httpx
import yaml

from src.app import telemetry

telemetry.setup("claims-loadgen")
from opentelemetry import trace  # noqa: E402

tracer = trace.get_tracer("loadgen")
SCENARIOS = yaml.safe_load((Path(__file__).parent / "scenarios.yaml").read_text())["scenarios"]
MODES = {"normal": 300, "burst": 15, "demo": 60}  # seconds between requests


def render(s: dict) -> str:
    q = s["question"]
    if "amount" in s:
        q = q.replace("${amount}", f"${random.choice(s['amount']):,}")
    if "long" in s:
        q = q.replace("${long}", s["long"] * s.get("long_repeat", 50))
    return q


def ask_once(client: httpx.Client, base_url: str) -> dict:
    s = random.choices(SCENARIOS, weights=[x["weight"] for x in SCENARIOS])[0]
    with tracer.start_as_current_span("loadgen.ask", kind=trace.SpanKind.CLIENT) as span:
        span.set_attribute("app.scenario", s["id"])
        try:
            r = client.post(
                f"{base_url.rstrip('/')}/api/ask",
                json={"question": render(s), "session_id": f"loadgen-{uuid.uuid4().hex[:8]}", "scenario": s["id"]},
                timeout=60,
            )
            span.set_attribute("http.response.status_code", r.status_code)
            return {"scenario": s["id"], "status": r.status_code}
        except httpx.HTTPError as exc:
            span.record_exception(exc)
            return {"scenario": s["id"], "status": "error", "error": str(exc)}


def run(count: int | None, mode: str) -> list[dict]:
    base_url = os.environ.get("APP_URL", "http://127.0.0.1:8080")
    results = []
    with httpx.Client() as client:
        i = 0
        while count is None or i < count:
            res = ask_once(client, base_url)
            results.append(res)
            print(res, flush=True)
            telemetry.flush()
            i += 1
            if count is None:
                time.sleep(MODES[mode] * random.uniform(0.7, 1.3))
    return results


def handler(event, _context):  # AWS Lambda
    results = run(int((event or {}).get("count", 1)), "normal")
    return {"sent": len(results), "results": results}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(MODES), default="normal")
    ap.add_argument("--once", type=int, help="send N requests and exit")
    a = ap.parse_args()
    run(a.once, a.mode)
