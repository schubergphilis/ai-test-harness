#!/usr/bin/env bash
# Sample remote TCP endpoints of the audit harness processes every 0.5 s until killed.
# Ports come from harnesses.toml (purpose "audit"). Read-only: lsof only, never kills anything.
# Output: <port> <remote-endpoint> lines (deduplicate afterwards).
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
PORTS=()
for h in $(reg names); do PORTS+=("$(reg port "$h" audit)"); done
while true; do
  for p in "${PORTS[@]}"; do
    for pid in $(lsof -tiTCP:"$p" -sTCP:LISTEN 2>/dev/null); do
      lsof -nP -a -p "$pid" -iTCP 2>/dev/null | awk -v port="$p" 'NR>1 && $NF!="(LISTEN)" {print port, $9}'
    done
  done
  sleep 0.5
done
