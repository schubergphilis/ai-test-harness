#!/usr/bin/env bash
# garak safety scan against one compat-contract agent (/invocations) or a bare litellm alias.
# Usage: run.sh <target> <alias> <probes>
#   target: a harness from harnesses.toml (must be serving on its "safety" port) | "model" (bare litellm alias)
#   alias:  a model alias from models.toml (for harness targets it is a label; the harness runs with MODEL=<alias>)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
TARGET=$1 ALIAS=$2 PROBES=$3
if [[ $TARGET != model ]]; then PORT=$(reg port "$TARGET" safety); fi   # fails on unknown harness
mkdir -p "$HERE/results" "$HERE/configs/generated"
sed "s#REPORT_DIR#$HERE/results#" "$HERE/configs/run.yaml" > "$HERE/configs/generated/run.yaml"
GEN="$HERE/configs/generated/$TARGET-$ALIAS.json"
if [[ $TARGET == model ]]; then
  # bare model through the litellm alias (OpenAI-compatible); separates model behaviour from harness behaviour
  cat > "$GEN" <<JSON
{"openai": {"OpenAICompatible": {"uri": "${LITELLM_URL:-http://127.0.0.1:4000/v1}", "model": "$ALIAS",
  "api_key": "${LITELLM_KEY:-sk-local-dev}", "max_tokens": 8192, "stop": [], "temperature": 0.7,
  "suppressed_params": ["n", "frequency_penalty", "presence_penalty", "stop"]}}}
JSON
  TT=openai.OpenAICompatible; NAME=$ALIAS
else
  # the agent: compat contract POST /invocations {"prompt": ...} -> {"output": ...}
  cat > "$GEN" <<JSON
{"rest": {"RestGenerator": {"name": "$TARGET-$ALIAS", "uri": "http://127.0.0.1:${PORT}/invocations",
  "method": "post", "headers": {"Content-Type": "application/json", "X-Agent-User": "garak"},
  "req_template_json_object": {"prompt": "\$INPUT"}, "response_json": true, "response_json_field": "output",
  "request_timeout": 300, "skip_codes": [400]}}}
JSON
  TT=rest; NAME="$TARGET-$ALIAS"
fi
cd "$HERE"
.venv/bin/python -m garak --config "$HERE/configs/generated/run.yaml" --target_type "$TT" --target_name "$NAME" \
  --generator_option_file "$GEN" --probes "$PROBES" --report_prefix "$TARGET-$ALIAS"
