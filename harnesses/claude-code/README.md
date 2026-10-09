# claude-code harness

Claude Code's own agent loop, driven through the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python).
Runs on every generic runtime, plus the Claude-specific [claude-docker runtime](../../runtimes/claude-docker/README.md).

- **Model access:** Claude Code speaks the Anthropic Messages API. It is pointed at the litellm proxy
  (`ANTHROPIC_BASE_URL` = `OPENAI_BASE_URL` without `/v1`), and litellm routes `/v1/messages` to every upstream
  via chat/completions (`use_chat_completions_url_for_anthropic_messages`). So the same aliases work as for the
  other harnesses, including the open-weights `sovereign` model. All model tiers (opus/sonnet/haiku/small-fast)
  are mapped to the one alias under test.
- **Canary tools:** `lookup` and `add` as an in-process MCP server (`mcp__canary__*`). Built-in tools (Bash,
  Read, Edit, …) are disabled with `tools=[]`.
- **System prompt:** Claude Code's own preset with the canary instructions appended, so this measures the real
  harness rather than a bare model call.
- **Isolation / sovereignty:** no user or project settings, a private config dir (never `~/.claude`), auto-memory
  off, and telemetry, error reporting, auto-update and other non-essential traffic switched off.
- **Container:** a plain `python:3.13-slim` image (like the other Python harnesses) with the CLI bundled in the
  SDK wheel. On the claude-docker runtime the image builds FROM `ghcr.io/schubergphilis/claude-docker` instead,
  uses its pinned CLI (`CLAUDE_CLI_PATH=claude`) and its entrypoint, which drops root before starting the server.

Known differences from the other harnesses:
- **Licence:** the SDK is MIT, but the Claude Code CLI it drives is proprietary (Anthropic commercial terms).
- **Tracing:** our spans cover the invocation and each tool call. The individual LLM calls happen inside the
  CLI and are not visible as spans here.
- **Natively** and on the generic runtimes the SDK's bundled CLI is used and none of the claude-docker
  guardrails apply; they only apply on the claude-docker runtime.
