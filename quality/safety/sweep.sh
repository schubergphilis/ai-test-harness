#!/usr/bin/env bash
# Safety sweep with garak (caps: see README.md).
#   sweep.sh [alias] [targets...]
#     alias    model alias (models.toml). Default: every alias with red_team = true whose env vars are set.
#     targets  "model" and/or harness names. Default: model + every harness in harnesses.toml.
# Starts the harnesses itself on their "safety" ports with MODEL=<alias> and stops exactly those PIDs afterwards
# (set SWEEP_START_HARNESSES=0 to use already-running ones). Needs litellm on :4000 (`make native-up`).
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
PROBES_ALL="promptinject.HijackHateHumans,latentinjection.LatentInjectionReport,web_injection.MarkdownImageExfil,dan.DanInTheWild,encoding.InjectBase64"
# encoding.InjectBase64 is model-only: against harnesses a single prompt ran >180s and garak aborts the whole
# run on one timeout (no per-invocation budget in the harnesses -> LLM10 finding, see README.md).
PROBES_HARNESS="promptinject.HijackHateHumans,latentinjection.LatentInjectionReport,web_injection.MarkdownImageExfil,dan.DanInTheWild"

if [[ $# -gt 0 ]]; then ALIASES=$1; shift; else ALIASES=$(reg models --red-team --configured | tr , ' '); fi
TARGETS=${*:-model $(reg names)}
trap qlib_cleanup EXIT
mkdir -p "$HERE/results/logs" "$HERE/results/proc"

for ALIAS in $ALIASES; do
  if [[ ${SWEEP_START_HARNESSES:-1} == 1 ]]; then
    qlib_cleanup
    export CANARY_FIXTURE=$QL_ROOT/compat/fixtures/canary.json OPENAI_BASE_URL=http://127.0.0.1:4000/v1 \
           OPENAI_API_KEY=${LITELLM_MASTER_KEY:-sk-local-dev} MODEL=$ALIAS
    PORTS=()
    for t in $TARGETS; do
      [[ $t == model ]] && continue
      port=$(reg port "$t" safety) || exit 1
      qlib_start_harness "$t" "$port" "$HERE/results/proc/$t-$ALIAS.log"
      PORTS+=("$port")
    done
    if [[ ${#PORTS[@]} -gt 0 ]]; then qlib_wait_ports 90 "${PORTS[@]}" || exit 1; fi
  fi
  for t in $TARGETS; do
    if [[ -n "${PROBES:-}" ]]; then P=$PROBES; elif [[ $t == model ]]; then P=$PROBES_ALL; else P=$PROBES_HARNESS; fi
    echo "=== $t / $ALIAS / $P  $(date +%T)"
    "$HERE/run.sh" "$t" "$ALIAS" "$P" > "$HERE/results/logs/$t-$ALIAS.log" 2>&1; rc=$?
    echo "    rc=$rc  $(date +%T)"; [[ $rc -ne 0 ]] && tail -5 "$HERE/results/logs/$t-$ALIAS.log"
  done
done
