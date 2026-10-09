"""Strands harness: canary agent over an OpenAI-compatible endpoint."""
import os

from strands import Agent
from strands.hooks import BeforeModelCallEvent
from strands.models.openai import OpenAIModel
from strands.tools.tools import PythonAgentTool

import sandbox_box
import tools_canary

HARNESS = "strands"

if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from strands.telemetry import StrandsTelemetry

    StrandsTelemetry().setup_otlp_exporter()


def _make_tool(name: str, box: "sandbox_box.Box | None" = None) -> PythonAgentTool:
    """Strands tool from the shared JSON-schema spec; dispatches to tools_canary.call, or to the Strands Sandbox
    box for the tools that really execute there (SCENARIO_EXEC=strands-sandbox)."""
    description, schema = tools_canary.TOOL_SPECS[name]

    if box is not None and name in sandbox_box.REAL:
        async def _run(tool_use, **_):
            result = await box.call(name, tool_use["input"])
            return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": result}]}
    else:
        def _run(tool_use, **_):
            result = tools_canary.call(name, tool_use["input"])
            return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": str(result)}]}

    spec = {"name": name, "description": description, "inputSchema": {"json": schema}}
    return PythonAgentTool(name, spec, _run)


TOOLS = [_make_tool(n) for n in tools_canary.ENABLED]


class _Model(OpenAIModel):
    """OpenAIModel reports every finish_reason but tool_calls/length as end_turn; keep an upstream content filter."""

    def format_chunk(self, event, **kwargs):
        if event.get("chunk_type") == "message_stop" and event.get("data") == "content_filter":
            return {"messageStop": {"stopReason": "content_filtered"}}
        return super().format_chunk(event, **kwargs)


def _model() -> OpenAIModel:
    return _Model(
        client_args={"base_url": os.environ["OPENAI_BASE_URL"], "api_key": os.environ["OPENAI_API_KEY"]},
        model_id=os.environ.get("MODEL", "sovereign"),
    )


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    attrs = {k: v for k, v in {"session.id": session_id, "user.id": user}.items() if v}
    if not sandbox_box.ENABLED:
        return await _run(prompt, attrs, TOOLS)
    box = await sandbox_box.Box.start()
    try:
        tools = [_make_tool(n, box) for n in tools_canary.ENABLED]
        result = await _run(prompt, attrs, tools)  # not Agent(sandbox=): that would add sandbox_* tools
        return {**result, "sandbox": await box.report()}
    finally:
        await box.close()


async def _run(prompt: str, attrs: dict, tools: list) -> dict:
    agent = Agent(
        model=_model(),
        tools=tools,
        system_prompt=tools_canary.SYSTEM_PROMPT,
        trace_attributes=attrs,
        callback_handler=None,
    )
    turns = 0

    def _turn_limit(event: BeforeModelCallEvent) -> None:  # strands has no turn limit of its own
        nonlocal turns
        turns += 1
        if turns > tools_canary.MAX_TURNS:
            event.cancel = f"stopped: AGENT_MAX_TURNS={tools_canary.MAX_TURNS} reached"

    agent.add_hook(_turn_limit, BeforeModelCallEvent)
    result = await agent.invoke_async(prompt)
    tool_calls = [
        {"name": block["toolUse"]["name"], "args": block["toolUse"]["input"]}
        for msg in agent.messages
        for block in msg["content"]
        if "toolUse" in block
    ]
    usage = result.metrics.accumulated_usage
    filtered = result.stop_reason in ("content_filtered", "guardrail_intervened")
    return {
        "output": "" if filtered else str(result).strip(),
        "tool_calls": tool_calls,
        "usage": {"input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens")},
        "stop_reason": "content_filter" if filtered else "max_turns" if turns > tools_canary.MAX_TURNS else "end_turn",
    }
