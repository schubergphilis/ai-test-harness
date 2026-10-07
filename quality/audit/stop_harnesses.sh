#!/usr/bin/env bash
# Stop exactly the processes started by start_harnesses.sh (PIDs from <logdir>/audit-harnesses.pids).
# usage: stop_harnesses.sh <logdir>
set -uo pipefail
LOG=${1:-/tmp}
PIDFILE=$LOG/audit-harnesses.pids
[[ -f $PIDFILE ]] || { echo "no $PIDFILE; nothing to stop"; exit 0; }
while read -r pid; do
  [[ -n $pid ]] || continue
  pkill -TERM -P "$pid" 2>/dev/null
  kill "$pid" 2>/dev/null
done < "$PIDFILE"
rm -f "$PIDFILE"
echo "audit harnesses stopped"
