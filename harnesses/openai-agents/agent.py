"""OpenAI Agents SDK harness: canary agent over an OpenAI-compatible (Chat Completions) endpoint."""
import json
import os

from agents import Agent, OpenAIChatCompletionsModel, Runner, function_tool, set_tracing_disabled
from agents.items import ToolCallItem
from openai import AsyncOpenAI

import tools_canary

HARNESS = "openai-agents"

# The SDK exports traces to OpenAI by default. Either replace that with OTel (OpenInference) or switch it off.
if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _provider = TracerProvider()
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    OpenAIAgentsInstrumentor().instrument(tracer_provider=_provider, exclusive_processor=True)
else:
    set_tracing_disabled(True)


@function_tool
def lookup(key: str) -> int | str:
    """Look up the population of a place by name."""
    return tools_canary.lookup(key)


@function_tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return tools_canary.add(a, b)


_client = AsyncOpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])
_agent = Agent(
    name="canary",
    instructions=tools_canary.SYSTEM_PROMPT,
    tools=[lookup, add],
    model=OpenAIChatCompletionsModel(model=os.environ.get("MODEL", "sovereign"), openai_client=_client),
)


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from openinference.instrumentation import using_attributes

        with using_attributes(session_id=session_id or "", user_id=user or ""):
            result = await Runner.run(_agent, prompt)
    else:
        result = await Runner.run(_agent, prompt)
    tool_calls = []
    for item in result.new_items:
        if isinstance(item, ToolCallItem) and getattr(item.raw_item, "type", None) == "function_call":
            tool_calls.append({"name": item.raw_item.name, "args": json.loads(item.raw_item.arguments or "{}")})
    usage = result.context_wrapper.usage
    return {
        "output": str(result.final_output).strip(),
        "tool_calls": tool_calls,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    }
