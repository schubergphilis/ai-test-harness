"""claude-code harness: Claude Code's agent loop via the Claude Agent SDK.

The SDK drives the Claude Code CLI as a subprocess. Model access goes through the litellm proxy's
Anthropic-compatible endpoint (/v1/messages), so every alias in models.toml works, including the
OpenAI-compatible sovereign model. On the claude-docker runtime (runtimes/claude-docker) the image builds FROM
the hardened claude-docker image.

Isolation choices (all deliberate, see README.md):
- built-in tools (Bash, Read, Edit, ...) are disabled; only the canary tools are exposed, as an
  in-process MCP server
- no user/project settings are loaded and the CLI gets its own config dir, never ~/.claude
- telemetry, error reporting and other non-essential traffic are switched off
"""
import asyncio
import contextlib
import os
import shutil
import tempfile
from contextlib import nullcontext

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ProcessError,
    ResultMessage,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

import tools_canary

HARNESS = "claude-code"
_PREFIX = "mcp__canary__"
_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or tempfile.mkdtemp(prefix="claude-harness-")
_WORKDIR = tempfile.mkdtemp(prefix="claude-harness-cwd-")
_HOME = tempfile.mkdtemp(prefix="claude-harness-home-")

_tracer = None
if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads standard OTEL_* env vars
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(HARNESS)


def _span(name, **attrs):
    if _tracer is None:
        return nullcontext()
    return _tracer.start_as_current_span(name, attributes={k: v for k, v in attrs.items() if v is not None})


def _text(value) -> dict:
    return {"content": [{"type": "text", "text": str(value)}]}


def _make_tool(name: str):
    """MCP tool from tools_canary.TOOL_SPECS (JSON schema), dispatched through tools_canary.call()."""
    description, schema = tools_canary.TOOL_SPECS[name]

    @tool(name, description, schema)
    async def _impl(args):
        with _span(f"execute_tool {name}", **{"gen_ai.tool.name": name}):
            return _text(tools_canary.call(name, dict(args)))

    return _impl


_SERVER = create_sdk_mcp_server("canary", tools=[_make_tool(n) for n in tools_canary.ENABLED])


def _cli_env(model: str) -> dict:
    """Point Claude Code at the litellm proxy and switch off everything that phones home."""
    base = os.environ["OPENAI_BASE_URL"].rstrip("/").removesuffix("/v1")
    return {
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_AUTH_TOKEN": os.environ["OPENAI_API_KEY"],
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_SMALL_FAST_MODEL": model,
        "CLAUDE_CONFIG_DIR": _CONFIG_DIR,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",  # no memory instructions injected into the conversation
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",  # beta headers break non-Anthropic upstreams
        # the CLI otherwise probes its surroundings (git status, CLAUDE.md files, background shells, checkpoints)
        "HOME": _HOME,
        "SHELL": "/bin/sh",
        "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        "CLAUDE_CODE_DISABLE_FILE_CHECKPOINTING": "1",
        "CLAUDE_CODE_DISABLE_CRON": "1",
        "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
        "CLAUDE_CODE_DISABLE_WORKFLOWS": "1",
    }


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    model = os.environ.get("MODEL", "mock")
    options = ClaudeAgentOptions(
        model=model,
        system_prompt={"type": "preset", "preset": "claude_code", "append": tools_canary.SYSTEM_PROMPT,
                       "exclude_dynamic_sections": True},
        tools=[],
        mcp_servers={"canary": _SERVER},
        allowed_tools=[f"{_PREFIX}{n}" for n in tools_canary.ENABLED],
        strict_mcp_config=True,
        setting_sources=[],
        max_turns=tools_canary.MAX_TURNS,
        cwd=_WORKDIR,
        env=_cli_env(model),
        settings='{"autoMemoryEnabled": false}',
        # claude-docker runtime: its pinned, scanned CLI instead of the SDK's bundled copy
        cli_path=shutil.which(os.environ["CLAUDE_CLI_PATH"]) if os.environ.get("CLAUDE_CLI_PATH") else None,
    )
    tool_calls, output, usage, subtype, error, refused, detail = [], "", None, None, None, False, None
    with _span(f"invoke_agent {HARNESS}", **{"session.id": session_id, "user.id": user,
                                             "gen_ai.request.model": model}):
        try:
            async with ClaudeSDKClient(options) as client:
                await client.query(prompt)
                try:
                    async for msg in client.receive_response():
                        if isinstance(msg, AssistantMessage):
                            for block in msg.content:
                                if isinstance(block, ToolUseBlock):
                                    tool_calls.append({"name": block.name.removeprefix(_PREFIX),
                                                       "args": dict(block.input)})
                        elif isinstance(msg, ResultMessage):
                            output, usage = msg.result or "", msg.usage
                            subtype = msg.subtype if msg.is_error else None
                            # an API error (429, budget, overload) ends as subtype "success" + is_error; the reason
                            # is only in the result text, e.g. "API Error: 429 ..."
                            detail = (msg.result or "")[:300] if msg.is_error else None
                            refused = msg.stop_reason == "refusal"  # litellm's mapping of content_filter
                except asyncio.CancelledError:
                    # timeout / client gone: stop the CLI's turn now. Closing the client alone gives the CLI a 5 s
                    # grace period after stdin EOF, during which it keeps calling the model.
                    with contextlib.suppress(Exception):
                        async with asyncio.timeout(2):
                            await client.interrupt()
                    raise
        except ProcessError as e:  # also raised after an error ResultMessage: keep what the run did so far
            error = str(e)
    if refused:
        stop_reason, error = "content_filter", None
    elif subtype == "error_max_turns":
        stop_reason, error = "max_turns", None
    elif subtype or error:
        stop_reason, error = "error", detail or error or subtype
    else:
        stop_reason = "end_turn"
    return {
        "output": output.strip() if stop_reason == "end_turn" else "",
        "tool_calls": tool_calls,
        "usage": {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                  "cache_read_tokens": usage.get("cache_read_input_tokens"),
                  "cache_write_tokens": usage.get("cache_creation_input_tokens")} if usage else None,
        "stop_reason": stop_reason,
        "error": error,
    }
