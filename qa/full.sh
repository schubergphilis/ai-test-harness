#!/usr/bin/env bash
# Full QA run, side by side: one qa/run.py child per model (qa/run.py runs models in parallel) and the
# garak sweep for every red-team alias at the same time, through its own litellm on :4001 so garak traffic never
# counts in the run's token totals. Then the garak reports are ingested into the same run and the report rendered.
#   qa/full.sh [--quick] [--keep-safety] [extra qa/run.py args...]
#     --quick        1 epoch everywhere (iteration; numbers are noisier)
#     --keep-safety  reuse quality/safety/results instead of a new sweep
# Logs: runs/_full/<UTC time>/ (qa.log, garak.log). Survives a crash: re-run qa/run.py --resume <run id>.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
EPOCHS=3 SWEEP=1 ARGS=()
for x in "$@"; do
  case $x in
    --quick) EPOCHS=1 ;;
    --keep-safety) SWEEP=0 ;;
    *) ARGS+=("$x") ;;
  esac
done
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOGS=runs/_full/$STAMP
mkdir -p "$LOGS"
AWAKE=(); command -v caffeinate >/dev/null && AWAKE=(caffeinate -i)   # no idle sleep (VPN drops, clocks stop)
MODELS=${QA_MODELS:-$(python3 scripts/registry.py models --qa --configured)}
echo "full run $STAMP: models $MODELS, epochs $EPOCHS, logs $LOGS"

scripts/native.sh up || exit 1
runtimes/box/build.sh || exit 1
docker build -q -t agentrt/egress-gw:dev runtimes/egress-gw || exit 1

GARAK=
if [[ $SWEEP == 1 ]]; then
  scripts/native.sh up-safety || exit 1
  if compgen -G "quality/safety/results/*.jsonl" >/dev/null; then   # never mix reports of two sweeps
    mkdir -p "runs/_archive/$STAMP" && mv quality/safety/results "runs/_archive/$STAMP/safety-results"
  fi
  LITELLM_URL=http://127.0.0.1:4001/v1 quality/safety/sweep.sh > "$LOGS/garak.log" 2>&1 &
  GARAK=$!
  echo "garak sweep started (pid $GARAK)"
fi
# stopped: SIGTERM to everything this script started (qa/run.py then stops its per-model children and box
# containers itself), then quit instead of going on to the next step
kill_tree() { local c; for c in $(pgrep -P "$1"); do kill_tree "$c"; done; kill "$1" 2>/dev/null; }
trap 'for c in $(pgrep -P $$); do kill_tree "$c"; done; exit 143' INT TERM

"${AWAKE[@]}" python3 qa/run.py --models "$MODELS" --no-report \
  --suites conformance,audit,inspect,scenarios,box,perf,supply \
  --epochs "$EPOCHS" --scenario-epochs "$EPOCHS" "${ARGS[@]}" 2>&1 | tee "$LOGS/qa.log" &
wait $! || true   # in the background: bash only runs the stop trap between commands, `wait` is interruptible
RUN_DIR=$(sed -n 's/^run [^ ]* -> \(.*\)/\1/p' "$LOGS/qa.log" | head -1)
[[ -n $RUN_DIR ]] || { echo "no run id in $LOGS/qa.log" >&2; exit 1; }

if [[ -n $GARAK ]]; then
  echo "waiting for the garak sweep ($LOGS/garak.log)"
  wait "$GARAK"
  scripts/native.sh down-safety
fi
python3 qa/run.py --resume "$RUN_DIR" --suites safety "${ARGS[@]}" 2>&1 | tee -a "$LOGS/qa.log"
echo "done: $RUN_DIR/report.html (logs $LOGS)"
