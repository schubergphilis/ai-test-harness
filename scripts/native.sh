#!/usr/bin/env bash
# Native shared infra (no Docker): mock LLM on :14000 and the litellm proxy on :4000.
#   scripts/native.sh up | down | status
# Processes are tracked by PID in .run/ (never killed by name). litellm reads .env (if present) and the
# generated runtimes/docker-local/litellm.yaml. Versions are pinned for reproducible runs.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUN=$ROOT/.run
LITELLM_VERSION=1.103.1
mkdir -p "$RUN"

start() {  # name, health-url, command...
  local name=$1 url=$2; shift 2
  if [[ -f $RUN/$name.pid ]] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  "$@" > "$RUN/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"
  for _ in $(seq 1 120); do curl -sf "$url" >/dev/null && { echo "$name up ($url)"; return; }; sleep 1; done
  echo "$name failed to start; see $RUN/$name.log" >&2; exit 1
}

stop() {
  local name=$1 pid
  [[ -f $RUN/$name.pid ]] || return 0
  pid=$(cat "$RUN/$name.pid")
  if kill -0 "$pid" 2>/dev/null; then
    pkill -TERM -P "$pid" 2>/dev/null || true   # children of this PID only (uv -> python)
    kill "$pid" 2>/dev/null || true
    echo "$name stopped"
  fi
  rm -f "$RUN/$name.pid"
}

case ${1:-} in
  up)
    start mock-llm http://127.0.0.1:14000/v1/models \
      uv run --no-project --with fastapi==0.142.2 --with uvicorn==0.54.0 \
        uvicorn --app-dir "$ROOT/compat/mock-llm" mock_llm:app --host 127.0.0.1 --port 14000
    (
      set -a; [[ -f $ROOT/.env ]] && . "$ROOT/.env"; set +a
      export MOCK_LLM_BASE_URL=http://127.0.0.1:14000/v1 LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:-sk-local-dev}
      # litellm refuses to start with an unset model env var: give unconfigured aliases a visible placeholder
      for v in $(python3 "$ROOT/scripts/registry.py" model-env-vars); do
        [[ -n ${!v:-} ]] || { export "$v=unconfigured-$v"; echo "note: $v not set in .env; that alias will fail" >&2; }
      done
      start litellm http://127.0.0.1:4000/health/liveliness \
        uvx --from "litellm[proxy]==$LITELLM_VERSION" litellm \
          --config "$ROOT/runtimes/docker-local/litellm.yaml" --host 127.0.0.1 --port 4000
    ) ;;
  down) stop litellm; stop mock-llm ;;
  status)
    for n in mock-llm litellm; do
      if [[ -f $RUN/$n.pid ]] && kill -0 "$(cat "$RUN/$n.pid")" 2>/dev/null; then echo "$n running (pid $(cat "$RUN/$n.pid"))"
      else echo "$n stopped"; fi
    done ;;
  *) echo "usage: $0 up|down|status" >&2; exit 2 ;;
esac
