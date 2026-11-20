#!/usr/bin/env bash
# Run the whole demo locally: AI gateway (LiteLLM :4000) + claims app (:8080).
# Usage: scripts/dev.sh up | down | status | logs
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.run"; mkdir -p "$RUN"
[[ -f "$ROOT/.env" ]] || { echo "Missing .env (copy .env.example)"; exit 1; }
set -a; source "$ROOT/.env"; set +a

start_gateway() {
  ( cd "$ROOT/src/gateway"
    export LITELLM_PRIMARY_MODEL="bedrock/converse/${BEDROCK_MODEL_PRIMARY}"
    export LITELLM_FALLBACK_MODEL="bedrock/converse/${BEDROCK_MODEL_FALLBACK}"
    export OTEL_EXPORTER=otlp_http
    export OTEL_ENDPOINT="${DT_ENV_URL%/}/api/v2/otlp/v1/traces"
    export OTEL_HEADERS="Authorization=Api-Token ${DT_INGEST_TOKEN}"
    export OTEL_SERVICE_NAME=ai-gateway OTEL_ENVIRONMENT_NAME="${DEPLOYMENT_ENV}"
    export CHAOS_FILE="$ROOT/.chaos"
    nohup .venv/bin/litellm --config config.yaml --host 127.0.0.1 --port 4000 >"$RUN/gateway.log" 2>&1 &
    echo $! >"$RUN/gateway.pid" )
}
start_app() {
  ( cd "$ROOT"
    OTEL_SERVICE_NAME=claims-app nohup uv run --no-sync uvicorn src.app.main:app --host 127.0.0.1 --port 8080 >"$RUN/app.log" 2>&1 &
    echo $! >"$RUN/app.pid" )
}
wait_for() { for _ in $(seq 1 60); do curl -fsS "$1" >/dev/null 2>&1 && return 0; sleep 1; done; echo "timeout: $1"; return 1; }

case "${1:-up}" in
  up)   start_gateway; start_app
        wait_for http://127.0.0.1:4000/health/liveliness && wait_for http://127.0.0.1:8080/healthz
        echo "gateway :4000 and app :8080 up -> open $APP_URL" ;;
  down) for p in gateway app; do [[ -f "$RUN/$p.pid" ]] && kill "$(cat "$RUN/$p.pid")" 2>/dev/null || true; rm -f "$RUN/$p.pid"; done
        pkill -f "litellm --config config.yaml" 2>/dev/null || true; pkill -f "uvicorn src.app.main:app" 2>/dev/null || true; echo down ;;
  status) curl -fsS http://127.0.0.1:4000/health/liveliness && echo " gateway ok" || echo "gateway down"
          curl -fsS http://127.0.0.1:8080/healthz && echo " app ok" || echo "app down" ;;
  logs) tail -n 50 "$RUN/gateway.log" "$RUN/app.log" ;;
esac
