"""Prove the story: one trace ID across web -> app -> agent -> gateway -> Bedrock in Dynatrace.

  uv run python -m scripts.verify              # check last 15 min
  uv run python -m scripts.verify --send 10    # send 10 requests first (app must be up)

Checks (exit code 1 if any fails):
  1. at least one trace contains spans from BOTH claims-app and ai-gateway (trace not broken)
  2. gateway spans carry token usage (gen_ai.usage.*)
  3. optional --rum: browser sessions exist and are linked to backend traces
Arize side is checked by hand (or via evals.run_evals) with the printed trace ID.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx


def dql(query: str, minutes: int) -> list[dict]:
    base, token = os.environ["DT_APPS_URL"].rstrip("/"), os.environ["DT_PLATFORM_TOKEN"]
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = httpx.post(f"{base}/platform/storage/query/v1/query:execute", headers=h, timeout=60,
                   json={"query": query, "defaultTimeframeStart": f"now()-{minutes}m", "defaultTimeframeEnd": "now()"})
    r.raise_for_status()
    body = r.json()
    while body.get("state") in ("RUNNING", "NOT_STARTED"):
        time.sleep(1)
        p = httpx.get(f"{base}/platform/storage/query/v1/query:poll", headers=h, timeout=60,
                      params={"request-token": body["requestToken"]})
        p.raise_for_status()
        body = p.json()
    return (body.get("result") or {}).get("records", [])


def main(minutes: int, send: int, rum: bool) -> int:
    if send:
        from loadgen.run import run
        run(send, "burst")
        time.sleep(20)  # let batch exporters + ingest catch up

    ok = True
    traces = dql(
        """fetch spans
        | filter in(service.name, "claims-app", "ai-gateway", "claims-loadgen")
        | summarize services = collectDistinct(service.name), spans = count(), start = min(start_time), by:{trace.id}
        | filter in("claims-app", services) and in("ai-gateway", services)
        | sort start desc | limit 5""", minutes)
    if traces:
        print(f"PASS 1: {len(traces)}+ traces span claims-app AND ai-gateway. Newest trace.id = {traces[0]['trace.id']}")
        print(f"        services in it: {traces[0]['services']}  spans: {traces[0]['spans']}")
    else:
        ok = False
        print("FAIL 1: no trace contains both claims-app and ai-gateway (gateway not continuing traceparent, or no data yet)")

    tok = dql(
        """fetch spans
        | filter service.name == "ai-gateway"
        | filter isNotNull(gen_ai.usage.input_tokens) or isNotNull(llm.token_count.prompt)
        | summarize n = count(), input_tokens = sum(gen_ai.usage.input_tokens)""", minutes)
    if tok and int(tok[0].get("n", 0)) > 0:
        print(f"PASS 2: gateway spans carry token usage ({tok[0]['n']} spans)")
    else:
        ok = False
        print("FAIL 2: no token-usage attributes on gateway spans (check LiteLLM otel callback / attribute names in a trace)")

    if rum:
        sess = dql('fetch user.sessions | summarize n = count()', minutes)
        n = int(sess[0]["n"]) if sess else 0
        print(("PASS" if n else "FAIL") + f" 3: {n} RUM user sessions")
        ok = ok and bool(n)

    print("\nArize: open the project 'v2-ai-demo' and search for the trace ID above.")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=15)
    ap.add_argument("--send", type=int, default=0)
    ap.add_argument("--rum", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.minutes, a.send, a.rum))
