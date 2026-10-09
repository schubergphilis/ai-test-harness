"""__HARNESS__ harness: framework-free tool-calling loop over an OpenAI-compatible endpoint.

This is the scaffold baseline. Replace the body of run() with the framework under test; keep the
return shape (output, tool_calls, usage) so the compat contract (compat/CONTRACT.md) still holds.
"""
import json
import os
from contextlib import nullcontext

from openai import AsyncOpenAI

import tools_canary

HARNESS = "__HARNESS__"

# tools enabled for this process (canary by default, a scenario's fake tools with SCENARIO=...)
TOOLS = [{"type": "function", "function": {"name": n, "description": tools_canary.TOOL_SPECS[n][0],
                                           "parameters": tools_canary.TOOL_SPECS[n][1]}}
         for n in tools_canary.ENABLED]

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


def _span(name: str, **attrs):
    if not _tracer:
        return nullcontext()
    return _tracer.start_as_current_span(name, attributes={k: v for k, v in attrs.items() if v is not None})


client = AsyncOpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])


async def run(prompt: str, session_id: str | None, user: str | None) -> dict:
    model = os.environ.get("MODEL", "mock")
    messages = [{"role": "system", "content": tools_canary.SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    tool_calls, tin, tout, output, stop_reason = [], 0, 0, "", "max_turns"
    with _span(f"invoke_agent {HARNESS}", **{"session.id": session_id, "user.id": user}):
        for _ in range(tools_canary.MAX_TURNS):
            with _span(f"chat {model}", **{"gen_ai.request.model": model, "session.id": session_id, "user.id": user}):
                resp = await client.chat.completions.create(model=model, messages=messages, tools=TOOLS)
            if resp.usage:
                tin += resp.usage.prompt_tokens or 0
                tout += resp.usage.completion_tokens or 0
            msg = resp.choices[0].message
            if resp.choices[0].finish_reason == "content_filter":  # upstream guardrail
                stop_reason = "content_filter"
                break
            if not msg.tool_calls:
                output, stop_reason = msg.content or "", "end_turn"
                break
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:  # malformed arguments from the model: keep them visible
                    args = {"_raw": tc.function.arguments}
                tool_calls.append({"name": tc.function.name, "args": args})
                with _span(f"execute_tool {tc.function.name}", **{"gen_ai.tool.name": tc.function.name,
                                                                    "session.id": session_id, "user.id": user}):
                    result = tools_canary.call(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
    return {"output": output.strip(), "tool_calls": tool_calls, "usage": {"input_tokens": tin, "output_tokens": tout},
            "stop_reason": stop_reason}
