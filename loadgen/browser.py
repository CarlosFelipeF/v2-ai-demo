"""Browser load generator (local) — real page loads + clicks, so Dynatrace RUM records
user sessions and links each click to the backend trace.

  uv run python -m loadgen.browser --sessions 5
On AWS the same journey runs as a Dynatrace browser clickpath synthetic monitor
(see docs/SYNTHETIC_MONITOR.md), so no browser is hosted on AWS.
"""

from __future__ import annotations

import argparse
import os
import random
import time

from playwright.sync_api import sync_playwright

BUTTONS = ["q-storm", "q-flood", "q-hail", "q-missing"]


def session(page, url: str) -> None:
    page.goto(url, wait_until="networkidle")
    for testid in random.sample(BUTTONS, k=2):
        before = page.locator('[data-testid="trace-id"]').count()
        page.click(f'[data-testid="{testid}"]')
        page.wait_for_function(
            f"document.querySelectorAll('[data-testid=\"trace-id\"], .msg.err').length > {before}", timeout=90_000
        )
        time.sleep(random.uniform(2, 5))


def main(sessions: int, pause: float) -> None:
    url = os.environ.get("APP_URL", "http://127.0.0.1:8080")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i in range(sessions):
            ctx = browser.new_context()  # new context = new RUM session
            try:
                session(ctx.new_page(), url)
                print(f"browser session {i + 1}/{sessions} ok", flush=True)
            except Exception as exc:  # keep going; failures are telemetry too
                print(f"browser session {i + 1} failed: {exc}", flush=True)
            finally:
                ctx.close()
            time.sleep(pause)
        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--pause", type=float, default=10)
    a = ap.parse_args()
    main(a.sessions, a.pause)
