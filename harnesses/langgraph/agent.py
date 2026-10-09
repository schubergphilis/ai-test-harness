"""LangGraph harness: canary agent (langchain create_agent, a LangGraph graph) over an OpenAI-compatible endpoint."""
import contextlib
import os

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError

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


def _make_tool(name: str) -> StructuredTool:
    """LangChain tool from the shared JSON-schema spec (dict args_schema); dispatches to tools_canary.call."""
    description, schema = tools_canary.TOOL_SPECS[name]

    def _run(**kwargs):
        return str(tools_canary.call(name, kwargs))

    return StructuredTool.from_function(func=_run, name=name, description=description, args_schema=schema)


TOOLS = [_make_tool(n) for n in tools_canary.ENABLED]


def _graph():
    model = ChatOpenAI(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.environ.get("MODEL", "sovereign"),
    )
    return create_agent(model, tools=TOOLS, system_prompt=tools_canary.SYSTEM_PROMPT)


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    ctx = using_attributes(session_id=session_id or "", user_id=user or "") if _TRACING else contextlib.nullcontext()
    # One model call + one tool step per turn. LangGraph's own default (10 000 steps) never stops a loop.
    config = {"recursion_limit": 2 * tools_canary.MAX_TURNS}
    state, stop_reason = {"messages": []}, "end_turn"
    with ctx:
        try:
            async for values in _graph().astream({"messages": [{"role": "user", "content": prompt}]}, config,
                                                 stream_mode="values"):
                state = values  # keep the last state: it survives a GraphRecursionError
        except GraphRecursionError:
            stop_reason = "max_turns"
    ai = [m for m in state["messages"] if isinstance(m, AIMessage)]
    if ai and ai[-1].response_metadata.get("finish_reason") == "content_filter":
        stop_reason = "content_filter"
    tool_calls = [{"name": tc["name"], "args": tc["args"]} for m in ai for tc in m.tool_calls]
    usage = [m.usage_metadata for m in ai if m.usage_metadata]
    return {
        "output": (ai[-1].text if ai and stop_reason == "end_turn" else "").strip(),
        "tool_calls": tool_calls,
        "usage": {
            "input_tokens": sum(u["input_tokens"] for u in usage) if usage else None,
            "output_tokens": sum(u["output_tokens"] for u in usage) if usage else None,
        },
        "stop_reason": stop_reason,
    }
