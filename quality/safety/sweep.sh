#!/usr/bin/env bash
# Safety sweep with garak (caps: see README.md).
#   sweep.sh [alias] [targets...]
#     alias    model alias or comma list (models.toml). Default: every alias with red_team = true whose env vars are set.
#     targets  "model" and/or harness names. Default: model + every harness in harnesses.toml.
# Starts the harnesses itself on their "safety" ports with MODEL=<alias> and stops exactly those PIDs afterwards
# (set SWEEP_START_HARNESSES=0 to use already-running ones). Needs litellm on :4000 (`make native-up`), or LITELLM_URL.
# Speed: several aliases run as separate sweep.sh processes side by side, each on its own safety ports
# (AGENTRT_PORT_SHIFT 0/20/40/60); within an alias SWEEP_JOBS targets (default 3) run at once. SWEEP_JOBS=1 and
# SWEEP_PARALLEL=0 give the old sequential sweep.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
# dan.DanInTheWild is not in the default sweep: its detector counts reworded refusals, so the rate is not a
# jailbreak rate. Add it with PROBES=...,dan.DanInTheWild when you want the transcripts.
PROBES_HARNESS="promptinject.HijackHateHumans,latentinjection.LatentInjectionReport,web_injection.MarkdownImageExfil"
# encoding.InjectBase64 is model-only: against harnesses a single prompt ran >180s and garak aborts the whole
# run on one timeout (no per-invocation budget in the harnesses -> LLM10 finding, see README.md).
# It runs as a separate garak call: probes draw their prompts from one seeded random stream, so an extra probe in
# the same call shifts the prompts of the probes after it, and the bare-model baseline would then be scored on
# different documents than the harnesses (qa/run.py refuses such a comparison).
PROBES_MODEL_ONLY="encoding.InjectBase64"
if [[ $# -gt 0 ]]; then ALIASES=${1//,/ }; shift; else ALIASES=$(reg models --red-team --configured | tr , ' '); fi
TARGETS=${*:-model $(reg names)}
mkdir -p "$HERE/results/logs" "$HERE/results/proc"

# several aliases: one sweep.sh per alias, side by side (qlib_cleanup only ever kills its own process's harnesses)
read -ra ALIAS_LIST <<< "$ALIASES"
if [[ ${#ALIAS_LIST[@]} -gt 1 && ${SWEEP_PARALLEL:-1} == 1 ]]; then
  [[ ${#ALIAS_LIST[@]} -le 4 ]] || { echo "at most 4 aliases in parallel (SWEEP_PARALLEL=0 for more)" >&2; exit 2; }
  pids=() i=0
  for ALIAS in "${ALIAS_LIST[@]}"; do
    # shellcheck disable=SC2086  # TARGETS is a word list
    AGENTRT_PORT_SHIFT=$((20 * i)) "$0" "$ALIAS" $TARGETS > >(sed -u "s/^/[$ALIAS] /") 2>&1 &
    pids+=($!); i=$((i + 1))
  done
  trap 'kill "${pids[@]}" 2>/dev/null' INT TERM
  rc=0; for p in "${pids[@]}"; do wait "$p" || rc=1; done
  exit $rc
fi
# on exit: running garak jobs (job -> run.sh -> python, so the whole tree), then our harnesses
kill_tree() { local c; for c in $(pgrep -P "$1"); do kill_tree "$c"; done; kill "$1" 2>/dev/null; }
GARAK=()
# shellcheck disable=SC2154  # j is assigned inside the trap string
trap 'for j in "${GARAK[@]}"; do kill_tree "$j"; done; qlib_cleanup' EXIT

# one target; `model` is followed by its model-only probe in the same job (a separate garak call, see above)
sweep_target() {
  local t=$1 ALIAS=$2 P=${PROBES:-$PROBES_HARNESS} rc
  echo "=== $t / $ALIAS / $P  $(date +%T)"
  "$HERE/run.sh" "$t" "$ALIAS" "$P" > "$HERE/results/logs/$t-$ALIAS.log" 2>&1; rc=$?
  echo "    $t rc=$rc  $(date +%T)"; [[ $rc -ne 0 ]] && tail -5 "$HERE/results/logs/$t-$ALIAS.log"
  if [[ $t == model && -z "${PROBES:-}" ]]; then
    echo "=== $t / $ALIAS / $PROBES_MODEL_ONLY  $(date +%T)"
    "$HERE/run.sh" "$t" "$ALIAS" "$PROBES_MODEL_ONLY" extra > "$HERE/results/logs/$t-$ALIAS~extra.log" 2>&1; rc=$?
    echo "    $t~extra rc=$rc  $(date +%T)"; [[ $rc -ne 0 ]] && tail -5 "$HERE/results/logs/$t-$ALIAS~extra.log"
  fi
  return 0
}

for ALIAS in $ALIASES; do
  if [[ ${SWEEP_START_HARNESSES:-1} == 1 ]]; then
    qlib_cleanup
    export CANARY_FIXTURE=$QL_ROOT/compat/fixtures/canary.json PROMPT_DIR=$QL_ROOT/prompts OPENAI_BASE_URL=${LITELLM_URL:-http://127.0.0.1:4000/v1} \
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
  GARAK=()   # our garak jobs (the harnesses are background jobs too, so `jobs` alone can't count them)
  for t in $TARGETS; do
    while [[ ${#GARAK[@]} -ge ${SWEEP_JOBS:-3} ]]; do
      wait -n "${GARAK[@]}"
      for i in "${!GARAK[@]}"; do kill -0 "${GARAK[$i]}" 2>/dev/null || unset 'GARAK[i]'; done
      GARAK=("${GARAK[@]}")
    done
    sweep_target "$t" "$ALIAS" &
    GARAK+=($!)
  done
  wait "${GARAK[@]}"
done
