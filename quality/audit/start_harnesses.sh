#!/usr/bin/env bash
# Start every registered harness natively (ports: harnesses.toml, purpose "audit") with OTLP export to the
# local collector (:4318). PIDs go to <logdir>/audit-harnesses.pids so stop_harnesses.sh kills only these.
# usage: start_harnesses.sh <model-alias> <logdir>     env: AUDIT_HARNESSES (comma filter)
set -euo pipefail
MODEL=${1:-mock}; LOG=${2:-/tmp}
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
R=$QL_ROOT
read -r -a HARNESSES <<< "$(reg names)"
if [[ -n ${AUDIT_HARNESSES:-} ]]; then IFS=, read -r -a HARNESSES <<< "$AUDIT_HARNESSES"; fi
export CANARY_FIXTURE=$R/compat/fixtures/canary.json OPENAI_BASE_URL=http://127.0.0.1:4000/v1 \
       OPENAI_API_KEY=${LITELLM_MASTER_KEY:-sk-local-dev} MODEL
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
PORTS=()
for h in "${HARNESSES[@]}"; do
  port=$(reg port "$h" audit)
  qlib_start_harness "$h" "$port" "$LOG/audit-$h.log"
  PORTS+=("$port")
done
printf '%s\n' "${QL_PIDS[@]}" > "$LOG/audit-harnesses.pids"
if qlib_wait_ports 60 "${PORTS[@]}"; then
  echo "${#HARNESSES[@]} harnesses up (MODEL=$MODEL); pids in $LOG/audit-harnesses.pids"
else
  qlib_cleanup; rm -f "$LOG/audit-harnesses.pids"; exit 1
fi
