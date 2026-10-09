#!/usr/bin/env bash
# garak safety scan against one compat-contract agent (/invocations) or a bare litellm alias.
# Usage: run.sh <target> <alias> <probes> [part]
#   target: a harness from harnesses.toml (must be serving on its "safety" port) | "model" (bare litellm alias)
#   alias:  a model alias from models.toml (for harness targets it is a label; the harness runs with MODEL=<alias>)
#   part:   writes <target>-<alias>~<part>.report.jsonl (a second garak call for the same target)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=../lib.sh
. "$HERE/../lib.sh"
TARGET=$1 ALIAS=$2 PROBES=$3 PART=${4:-}
if [[ $TARGET != model ]]; then PORT=$(reg port "$TARGET" safety); fi   # fails on unknown harness
mkdir -p "$HERE/results" "$HERE/configs/generated"
# per target: sweep.sh runs several targets at once, a shared generated file could be read half-written
CFG="$HERE/configs/generated/run-$TARGET-$ALIAS${PART:+~$PART}.yaml"
sed "s#REPORT_DIR#$HERE/results#" "$HERE/configs/run.yaml" > "$CFG"
GEN="$HERE/configs/generated/$TARGET-$ALIAS${PART:+~$PART}.json"
if [[ $TARGET == model ]]; then
  # bare model through the litellm alias (OpenAI-compatible); separates model behaviour from harness behaviour.
  # max_tokens is not sent: some probes (promptinject, web_injection) cap it at 60, and a reasoning model spends
  # that on reasoning and returns no text at all (finish_reason=length), leaving no baseline. The harnesses
  # don't pass the probe's cap either, so the comparison stays like for like.
  cat > "$GEN" <<JSON
{"openai": {"OpenAICompatible": {"uri": "${LITELLM_URL:-http://127.0.0.1:4000/v1}", "model": "$ALIAS",
  "api_key": "${LITELLM_MASTER_KEY:-sk-local-dev}", "stop": [], "temperature": 0.7,
  "suppressed_params": ["n", "frequency_penalty", "presence_penalty", "stop", "max_tokens"]}}}
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
.venv/bin/python -m garak --config "$CFG" --target_type "$TT" --target_name "$NAME" \
  --generator_option_file "$GEN" --probes "$PROBES" --report_prefix "$TARGET-$ALIAS${PART:+~$PART}"
