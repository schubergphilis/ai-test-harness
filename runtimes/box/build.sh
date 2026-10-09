#!/usr/bin/env bash
# Build the scenario box image from compat/fixtures/scenarios/scenarios.json.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
ctx="$(mktemp -d)"
trap 'rm -rf "$ctx"' EXIT
python3 - "$root/compat/fixtures/scenarios/scenarios.json" "$ctx/seed" <<'PY'
import json, pathlib, sys
world = json.loads(pathlib.Path(sys.argv[1]).read_text())
seed = pathlib.Path(sys.argv[2])
for path, content in world["filesystem"].items():
    if path == "/etc/passwd":  # the image has its own
        continue
    f = seed / path.lstrip("/")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
PY
cp "$here/Dockerfile" "$ctx/"
docker build -t "${BOX_IMAGE:-agentrt/box:dev}" "$ctx"
