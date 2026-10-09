"""OpenAI Agents SDK harness: canary agent over an OpenAI-compatible (Chat Completions) endpoint."""
import json
import os

from agents import Agent, FunctionTool, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from agents.items import ToolCallItem
from agents.run_error_handlers import RunErrorHandlerInput, RunErrorHandlerResult
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


def _make_tool(name: str) -> FunctionTool:
    """FunctionTool from the shared JSON-schema spec; dispatches to tools_canary.call."""
    description, schema = tools_canary.TOOL_SPECS[name]

    async def _invoke(_ctx, args_json: str) -> str:
        return str(tools_canary.call(name, _args(args_json)))

    # strict mode would require additionalProperties=false and every property required; specs are plain JSON schema
    return FunctionTool(name=name, description=description, params_json_schema=schema, on_invoke_tool=_invoke,
                        strict_json_schema=False)


def _args(args_json: str | None) -> dict:
    try:
        args = json.loads(args_json or "{}")
    except json.JSONDecodeError:  # malformed arguments from the model: keep them visible instead of failing the run
        return {"_raw": args_json}
    return args if isinstance(args, dict) else {"_raw": args}


TOOLS = [_make_tool(n) for n in tools_canary.ENABLED]


_client = AsyncOpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])
_agent = Agent(
    name="canary",
    instructions=tools_canary.SYSTEM_PROMPT,
    tools=TOOLS,
    model=OpenAIChatCompletionsModel(model=os.environ.get("MODEL", "sovereign"), openai_client=_client),
)


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    stop = {"reason": "end_turn"}

    def _stopped(reason: str):
        def handler(_input: RunErrorHandlerInput) -> RunErrorHandlerResult:
            stop["reason"] = reason  # keep the partial run instead of raising (the SDK default)
            return RunErrorHandlerResult(final_output="", include_in_history=False)
        return handler

    kwargs = {"max_turns": tools_canary.MAX_TURNS,
              "error_handlers": {"max_turns": _stopped("max_turns"), "model_refusal": _stopped("content_filter")}}
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from openinference.instrumentation import using_attributes

        with using_attributes(session_id=session_id or "", user_id=user or ""):
            result = await Runner.run(_agent, prompt, **kwargs)
    else:
        result = await Runner.run(_agent, prompt, **kwargs)
    tool_calls = []
    for item in result.new_items:
        if isinstance(item, ToolCallItem) and getattr(item.raw_item, "type", None) == "function_call":
            tool_calls.append({"name": item.raw_item.name, "args": _args(item.raw_item.arguments)})
    usage = result.context_wrapper.usage
    return {
        "output": str(result.final_output or "").strip(),
        "tool_calls": tool_calls,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
        "stop_reason": stop["reason"],
    }
