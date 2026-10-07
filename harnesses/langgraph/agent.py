"""LangGraph harness: canary agent (langchain create_agent, a LangGraph graph) over an OpenAI-compatible endpoint."""
import contextlib
import os

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

import tools_canary

HARNESS = "langgraph"

_TRACING = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
if _TRACING:
    from openinference.instrumentation import using_attributes
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _provider = TracerProvider()
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(_provider)
    LangChainInstrumentor().instrument(tracer_provider=_provider)


@tool
def lookup(key: str) -> int | str:
    """Look up the population of a place by name."""
    return tools_canary.lookup(key)


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return tools_canary.add(a, b)


def _graph():
    model = ChatOpenAI(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.environ.get("MODEL", "sovereign"),
    )
    return create_agent(model, tools=[lookup, add], system_prompt=tools_canary.SYSTEM_PROMPT)


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    ctx = using_attributes(session_id=session_id or "", user_id=user or "") if _TRACING else contextlib.nullcontext()
    with ctx:
        state = await _graph().ainvoke({"messages": [{"role": "user", "content": prompt}]})
    ai = [m for m in state["messages"] if isinstance(m, AIMessage)]
    tool_calls = [{"name": tc["name"], "args": tc["args"]} for m in ai for tc in m.tool_calls]
    usage = [m.usage_metadata for m in ai if m.usage_metadata]
    return {
        "output": (ai[-1].text if ai else "").strip(),
        "tool_calls": tool_calls,
        "usage": {
            "input_tokens": sum(u["input_tokens"] for u in usage) if usage else None,
            "output_tokens": sum(u["output_tokens"] for u in usage) if usage else None,
        },
    }
