"""Pydantic AI harness: canary agent over an OpenAI-compatible endpoint."""
import os
from contextlib import nullcontext

from pydantic_ai import Agent
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

import tools_canary

HARNESS = "pydantic-ai"

_tracer = None
_capabilities = []
if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    # Plain OTel SDK -> OTLP/HTTP (endpoint + headers from standard OTEL_* env). No Logfire.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from pydantic_ai.capabilities.instrumentation import Instrumentation
    from pydantic_ai.models.instrumented import InstrumentationSettings

    _provider = TracerProvider()
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _tracer = _provider.get_tracer(HARNESS)
    _capabilities = [Instrumentation(settings=InstrumentationSettings(tracer_provider=_provider))]

agent = Agent(
    OpenAIChatModel(
        os.environ.get("MODEL", "sovereign"),
        provider=OpenAIProvider(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"]),
    ),
    system_prompt=tools_canary.SYSTEM_PROMPT,
    capabilities=_capabilities,
)


@agent.tool_plain
def lookup(key: str) -> int | str:
    """Look up the population of a place by name."""
    return tools_canary.lookup(key)


@agent.tool_plain
def add(a: int, b: int) -> int:
    """Add two integers."""
    return tools_canary.add(a, b)


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    attrs = {k: v for k, v in {"session.id": session_id, "user.id": user}.items() if v}
    # Parent span carries session/user so Langfuse can group the trace; agent spans nest under it.
    span = _tracer.start_as_current_span("invocation", attributes=attrs) if _tracer else nullcontext()
    with span:
        result = await agent.run(prompt)
    tool_calls = [
        {"name": part.tool_name, "args": part.args_as_dict()}
        for msg in result.all_messages()
        for part in msg.parts
        if isinstance(part, ToolCallPart)
    ]
    usage = result.usage  # property in pydantic-ai v2 (was a method in v1)
    return {
        "output": str(result.output).strip(),
        "tool_calls": tool_calls,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
    }
