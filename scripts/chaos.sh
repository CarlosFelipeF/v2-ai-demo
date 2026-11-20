#!/usr/bin/env bash
# Toggle gateway fault injection. Usage: scripts/chaos.sh off|latency|errors [--aws]
set -euo pipefail
MODE="${1:?off|latency|errors}"; ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "${2:-}" == "--aws" ]]; then
  aws ssm put-parameter --name /v2-ai-demo/chaos --type String --overwrite --value "$MODE" --profile "${AWS_DEPLOY_PROFILE:-v2-ai-demo-deployer}" >/dev/null
else
  echo "$MODE" >"$ROOT/.chaos"
fi
echo "chaos=$MODE (takes effect within ~5s)"
