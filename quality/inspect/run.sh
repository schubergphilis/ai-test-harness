#!/usr/bin/env bash
# Run the Inspect agent evals for every registered harness against one litellm alias.
#   quality/inspect/run.sh <alias> <epochs> [tasks...]   (default tasks: canary variants injection)
# Aliases: models.toml. Harnesses + ports: harnesses.toml (purpose "inspect").
# Needs litellm on :4000 (`make native-up`). Starts the harnesses natively and stops exactly those processes.
# Env: INSPECT_LOG_DIR, INSPECT_PROC_DIR (default results/logs, results/proc), INSPECT_HARNESSES (comma filter).
set -euo pipefail
ALIAS=${1:?alias}; EPOCHS=${2:?epochs}; shift 2
TASKS=${*:-canary variants injection}
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
ROOT=$QL_ROOT
read -r -a HARNESSES <<< "$(reg names)"
if [[ -n ${INSPECT_HARNESSES:-} ]]; then IFS=, read -r -a HARNESSES <<< "$INSPECT_HARNESSES"; fi
LOGS=${INSPECT_LOG_DIR:-$HERE/results/logs}; PROC=${INSPECT_PROC_DIR:-$HERE/results/proc}; mkdir -p "$LOGS" "$PROC"
export CANARY_FIXTURE=$ROOT/compat/fixtures/canary.json OPENAI_BASE_URL=${OPENAI_BASE_URL:-http://127.0.0.1:4000/v1} \
       OPENAI_API_KEY=${OPENAI_API_KEY:-${LITELLM_MASTER_KEY:-sk-local-dev}} MODEL=$ALIAS
trap qlib_cleanup EXIT

PORTS=()
for h in "${HARNESSES[@]}"; do
  port=$(reg port "$h" inspect)
  qlib_start_harness "$h" "$port" "$PROC/$h.log"
  PORTS+=("$port")
done
qlib_wait_ports 90 "${PORTS[@]}"

for i in "${!HARNESSES[@]}"; do
  h=${HARNESSES[$i]}
  for t in $TASKS; do
    (cd "$HERE" && uv run inspect eval "src/agentrt_inspect/tasks.py@$t" --model "harness/$h@$ALIAS" \
       --model-base-url "http://localhost:${PORTS[$i]}" -T epochs="$EPOCHS" --max-connections 2 --max-samples 2 \
       --max-retries 2 --timeout 180 --log-dir "$LOGS" --no-log-images --display none) || echo "eval failed: $h $t"
  done
done
