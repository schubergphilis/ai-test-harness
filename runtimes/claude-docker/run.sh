#!/usr/bin/env bash
# Run the claude-code harness container with claude-docker's guardrails (mirrors run_container() in
# github.com/schubergphilis/claude-docker run.sh v0.3.3), then serve the compat contract on localhost.
#   runtimes/claude-docker/run.sh [MODEL]       # needs `make native-up` (litellm :4000) and the image:
#   docker build -f runtimes/claude-docker/Dockerfile -t agentrt/claude-code:claude-docker .
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
MODEL=${1:-${MODEL:-mock}}
PORT=${PORT:-$(python3 "$ROOT/scripts/registry.py" port claude-code claude-docker)}
set -a; [[ -f $ROOT/.env ]] && . "$ROOT/.env"; set +a   # LITELLM_MASTER_KEY, as native-up uses
RUNTIME=${CLAUDE_DOCKER_RUNTIME:-docker}

# the guardrail flags live in scripts/registry.py (RUNTIME_RUN_ARGS), shared with the QA runner's container launch
GUARDS=(); while IFS= read -r f; do GUARDS+=("$f"); done < <(python3 "$ROOT/scripts/registry.py" run-args claude-docker)

NAME=agentrt-claude-code
NET=(--add-host host.docker.internal:host-gateway -p "127.0.0.1:$PORT:8080")
if [[ $(python3 "$ROOT/scripts/registry.py" egress claude-docker) == proxy-only && $RUNTIME == docker ]]; then
  # internal network: only LiteLLM (:4000) is reachable, through a gateway that also publishes the API port
  NET=(); while IFS= read -r f; do NET+=("$f"); done < <(python3 "$ROOT/scripts/egress_gw.py" up "$NAME-gw" \
    --agent "$NAME" --forward 4000 --publish "$PORT")
  trap 'python3 "$ROOT/scripts/egress_gw.py" down "$NAME-gw"' EXIT
fi

"$RUNTIME" run --rm --name "$NAME" "${GUARDS[@]}" \
  -e OPENAI_BASE_URL=http://host.docker.internal:4000/v1 \
  -e OPENAI_API_KEY="${LITELLM_MASTER_KEY:-sk-local-dev}" \
  -e MODEL="$MODEL" -e CANARY_FIXTURE=/app/canary.json \
  "${NET[@]}" \
  agentrt/claude-code:claude-docker
