"""Inspect model provider that wraps an agent harness's POST /invocations (compat/CONTRACT.md).

Inspect thinks it is talking to a model; it is actually talking to the whole agent (harness + tools + LLM),
so the scores measure the harness. Usage:

    inspect eval agentrt_inspect/canary --model harness/strands@sovereign --model-base-url http://localhost:18101
"""
import time
import uuid

import httpx
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool import ToolChoice, ToolInfo


class HarnessAPI(ModelAPI):
    def __init__(self, model_name: str, base_url: str | None = None, api_key: str | None = None,
                 config: GenerateConfig = GenerateConfig(), **model_args):
        super().__init__(model_name=model_name, base_url=base_url, api_key=api_key, config=config)
        if not self.base_url:
            raise ValueError("harness provider needs --model-base-url http://host:port of the agent")
        self.timeout = float(model_args.get("timeout", 300))
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def aclose(self) -> None:
        await self.client.aclose()

    def max_connections(self) -> int:
        return 2

    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, (httpx.ConnectError, httpx.ReadTimeout))

    async def generate(self, input: list[ChatMessage], tools: list[ToolInfo], tool_choice: ToolChoice,
                       config: GenerateConfig) -> ModelOutput:
        prompt = next((m.text for m in reversed(input) if m.role == "user"), "")
        started = time.monotonic()
        r = await self.client.post(
            f"{self.base_url.rstrip('/')}/invocations",
            json={"prompt": prompt, "session_id": f"inspect-{uuid.uuid4().hex[:12]}"},
            headers={"X-Agent-User": "inspect-eval"},
        )
        elapsed = time.monotonic() - started
        if r.status_code != 200:
            return ModelOutput.from_content(self.model_name, "", stop_reason="unknown",
                                            error=f"HTTP {r.status_code}: {r.text[:500]}")
        body = r.json()
        usage = body.get("usage") or {}
        inp, out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
        meta = {"tool_calls": body.get("tool_calls", []), "harness": body.get("harness"),
                "alias": body.get("model"), "latency_s": round(elapsed, 3)}
        return ModelOutput(
            model=self.model_name,
            choices=[ChatCompletionChoice(message=ChatMessageAssistant(content=body.get("output", ""),
                                                                       model=self.model_name),
                                          stop_reason="stop")],
            usage=ModelUsage(input_tokens=inp, output_tokens=out, total_tokens=inp + out),
            time=elapsed,
            metadata=meta,
        )
