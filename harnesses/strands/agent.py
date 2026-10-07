"""Strands harness: canary agent over an OpenAI-compatible endpoint."""
import os

from strands import Agent, tool
from strands.models.openai import OpenAIModel

import tools_canary

HARNESS = "strands"

if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from strands.telemetry import StrandsTelemetry

    StrandsTelemetry().setup_otlp_exporter()


@tool
def lookup(key: str) -> int | str:
    """Look up the population of a place by name."""
    return tools_canary.lookup(key)


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return tools_canary.add(a, b)


def _model() -> OpenAIModel:
    return OpenAIModel(
        client_args={"base_url": os.environ["OPENAI_BASE_URL"], "api_key": os.environ["OPENAI_API_KEY"]},
        model_id=os.environ.get("MODEL", "sovereign"),
    )


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    attrs = {k: v for k, v in {"session.id": session_id, "user.id": user}.items() if v}
    agent = Agent(
        model=_model(),
        tools=[lookup, add],
        system_prompt=tools_canary.SYSTEM_PROMPT,
        trace_attributes=attrs,
        callback_handler=None,
    )
    result = await agent.invoke_async(prompt)
    tool_calls = [
        {"name": block["toolUse"]["name"], "args": block["toolUse"]["input"]}
        for msg in agent.messages
        for block in msg["content"]
        if "toolUse" in block
    ]
    usage = result.metrics.accumulated_usage
    return {
        "output": str(result).strip(),
        "tool_calls": tool_calls,
        "usage": {"input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens")},
    }
