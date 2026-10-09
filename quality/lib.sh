#!/usr/bin/env bash
# Shared helpers for quality/ scripts. Source it:  . "$(dirname "$0")/../lib.sh"
# Harness names, ports and start commands come from harnesses.toml via scripts/registry.py.
# Processes are tracked by PID (QL_PIDS); qlib_cleanup kills only those PIDs and their children.

QL_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
QL_PIDS=()

reg() { python3 "$QL_ROOT/scripts/registry.py" "$@"; }

# qlib_start_harness <name> <port> <logfile>   (env: MODEL, OPENAI_*, CANARY_FIXTURE, OTEL_* as exported by caller)
qlib_start_harness() {
  local name=$1 port=$2 log=$3 dir="$QL_ROOT/harnesses/$1"
  if [[ $(reg get "$name" language) == node ]]; then
    [[ -f $dir/dist/server.js ]] || (cd "$dir" && npm run -s build)
    (cd "$dir" && OTEL_SERVICE_NAME=agent-$name HOST=127.0.0.1 PORT=$port exec node dist/server.js) > "$log" 2>&1 &
  else
    (cd "$dir" && OTEL_SERVICE_NAME=agent-$name exec uv run uvicorn app:app --host 127.0.0.1 --port "$port") > "$log" 2>&1 &
  fi
  QL_PIDS+=($!)
}

# qlib_wait_ports <timeout-s> <port>...   -> 0 when every /ping answers
qlib_wait_ports() {
  local timeout=$1 ok p; shift
  for _ in $(seq 1 "$timeout"); do
    ok=0
    for p in "$@"; do curl -sf "localhost:$p/ping" >/dev/null && ok=$((ok + 1)); done
    [[ $ok == "$#" ]] && return 0
    sleep 1
  done
  echo "only $ok/$# harnesses answered /ping" >&2
  return 1
}

# qlib_up <timeout-s> <name:port:log>...   start harnesses, wait for /ping, restart the silent ones once
# (a cold start can lose a race on a loaded machine); 0 when every /ping answers
qlib_up() {
  local timeout=$1 spec name port log i=0; shift
  local -a pids=() ports=()
  for spec; do
    IFS=: read -r name port log <<< "$spec"
    qlib_start_harness "$name" "$port" "$log"
    pids+=("${QL_PIDS[${#QL_PIDS[@]}-1]}"); ports+=("$port")
  done
  qlib_wait_ports "$timeout" "${ports[@]}" && return 0
  for spec; do
    IFS=: read -r name port log <<< "$spec"
    if ! curl -sf "localhost:$port/ping" >/dev/null; then
      echo "harness $name not ready, restarting once" >&2
      pkill -KILL -P "${pids[$i]}" 2>/dev/null || true; kill -KILL "${pids[$i]}" 2>/dev/null || true; sleep 2
      qlib_start_harness "$name" "$port" "${log%.log}.retry.log"
    fi
    i=$((i + 1))
  done
  qlib_wait_ports "$timeout" "${ports[@]}"
}

# Kill the PIDs we started (and their children, e.g. uv -> python), nothing else.
qlib_cleanup() {
  local p
  for p in "${QL_PIDS[@]:-}"; do
    [[ -n $p ]] || continue
    pkill -TERM -P "$p" 2>/dev/null || true
    kill "$p" 2>/dev/null || true
  done
  QL_PIDS=()
}
