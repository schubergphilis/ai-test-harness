#!/usr/bin/env bash
# Run one harness image inside an OpenShell sandbox and forward it to localhost:<openshell port> (harnesses.toml).
# Prereqs: docker-local stack up (litellm on :4000, built agent image), OpenShell gateway running:
#   openshell-gateway --compute-driver docker --disable-tls &      # 127.0.0.1:17670
#   openshell gateway add http://127.0.0.1:17670 --local --name local && openshell gateway select local
# Docker Desktop: enable host networking, disable Enhanced Container Isolation.
# UNVERIFIED end to end (see README.md).
set -euo pipefail
HARNESS=${1:?usage: run.sh <harness>}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
reg() { python3 "$ROOT/scripts/registry.py" "$@"; }
PORT=$(reg port "$HARNESS" openshell)   # harnesses.toml [ports].openshell + index; fails on unknown harness
NAME=agentrt-$HARNESS

# OpenShell replaces the image ENTRYPOINT/CMD, so the start command is passed explicitly (by language).
if [[ $(reg get "$HARNESS" language) == node ]]; then CMD=(/usr/local/bin/node dist/server.js)
else CMD=(/app/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080); fi

openshell sandbox delete "$NAME" >/dev/null 2>&1 || true
openshell sandbox create --name "$NAME" --from "agentrt/$HARNESS:dev" --policy "$HERE/policy.yaml" \
  --env OPENAI_BASE_URL=http://host.openshell.internal:4000/v1 \
  --env OPENAI_API_KEY="${LITELLM_MASTER_KEY:-sk-local-dev}" \
  --env MODEL="${MODEL:-mock}" \
  --env CANARY_FIXTURE=/app/canary.json \
  --env PORT=8080 \
  --no-credential-warnings \
  --detach -- "${CMD[@]}"

openshell forward service "$NAME" --target-port 8080 --local "$PORT" &
FWD=$!
trap 'kill $FWD 2>/dev/null || true' EXIT
until curl -sf "localhost:$PORT/ping" >/dev/null; do sleep 1; done
echo "sandbox $NAME ready on http://localhost:$PORT (Ctrl-C to stop forwarding)"
wait $FWD
