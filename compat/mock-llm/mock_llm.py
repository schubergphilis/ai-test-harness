"""Deterministic OpenAI-compatible chat completions server that plays the canary script.

Turn logic (based on how many tool results are already in the conversation):
  0 -> call lookup(zorbia)   1 -> call lookup(quellmark)   2 -> call add(a, b)   3 -> final answer
Supports stream and non-stream. For plumbing tests only: it says nothing about model quality.
"""
import json
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()


def _tool_results(messages):
    out = []
    for m in messages:
        if m.get("role") == "tool":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            out.append(str(c))
    return out


def _num(s):
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else 0


def _plan(messages):
    """Return (tool_call | None, text | None)."""
    results = _tool_results(messages)
    n = len(results)
    if n == 0:
        return ("lookup", {"key": "zorbia"}), None
    if n == 1:
        return ("lookup", {"key": "quellmark"}), None
    if n == 2:
        return ("add", {"a": _num(results[0]), "b": _num(results[1])}), None
    return None, f"The total population is {_num(results[-1])}."


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in ("mock", "sovereign", "best")]}


@app.get("/health/liveliness")
def health():
    return "ok"


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    call, text = _plan(body.get("messages", []))
    cid, created, model = f"chatcmpl-{uuid.uuid4().hex[:8]}", int(time.time()), body.get("model", "mock")
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    tc = None
    if call:
        tc = {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
              "function": {"name": call[0], "arguments": json.dumps(call[1])}}
    finish = "tool_calls" if tc else "stop"

    if not body.get("stream"):
        msg = {"role": "assistant", "content": text}
        if tc:
            msg["tool_calls"] = [tc]
        return JSONResponse({"id": cid, "object": "chat.completion", "created": created, "model": model,
                             "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": usage})

    def chunk(delta, finish_reason=None, with_usage=False):
        d = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
             "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
        if with_usage:
            d["choices"], d["usage"] = [], usage
        return f"data: {json.dumps(d)}\n\n"

    def gen():
        yield chunk({"role": "assistant", "content": ""})
        if tc:
            yield chunk({"tool_calls": [{"index": 0, **tc}]})
        else:
            yield chunk({"content": text})
        yield chunk({}, finish)
        if (body.get("stream_options") or {}).get("include_usage"):
            yield chunk({}, with_usage=True)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
