"""Deterministic OpenAI-compatible chat completions server that plays the canary script.

Turn logic (based on how many tool results are already in the conversation):
  0 -> call lookup(zorbia)   1 -> call lookup(quellmark)   2 -> call add(a, b)   3 -> final answer
Supports stream and non-stream. For plumbing tests only: it says nothing about model quality.
"""
import asyncio
import json
import os
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
STATS = {"chat_calls": 0}  # read by the perf suite's runaway test (GET /stats, POST /stats/reset)


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


def _minimal_args(tool: dict) -> dict:
    """Plausible arguments from a tool's JSON schema (scenario plumbing in the mock)."""
    samples = {"path": "/workspace", "url": "https://docs.example/log-rotation", "command": "ls",
               "to": "me@corp.example", "subject": "mock", "body": "mock", "log_type": "internal",
               "log_name": "mock", "log_data": "mock"}
    props = tool.get("function", {}).get("parameters", {}).get("properties", {})
    return {k: samples.get(k, 1 if v.get("type") == "integer" else "x") for k, v in props.items()}


def _user_marker(messages, marker: str) -> bool:
    for m in messages:
        c = m.get("content")
        text = " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else str(c or "")
        if m.get("role") == "user" and marker in text:
            return True
    return False


def _runaway(messages) -> bool:
    """Prompt contains RUNAWAY-TEST: never give a final answer (tests whether the harness stops the loop)."""
    return _user_marker(messages, "RUNAWAY-TEST")


@app.get("/stats")
def stats():
    return STATS


@app.post("/stats/reset")
def stats_reset():
    STATS["chat_calls"] = 0
    return STATS


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in ("mock", "sovereign", "best")]}


@app.get("/health/liveliness")
def health():
    return "ok"


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    if os.environ.get("MOCK_DEBUG"):
        turns = [m for m in body.get("messages", []) if m.get("role") in ("tool", "assistant")]
        print(json.dumps(turns)[-3000:], flush=True)  # debug: what the harness sent back after tool calls
    STATS["chat_calls"] += 1
    if _user_marker(body.get("messages", []), "RUNAWAY-SLOW"):  # slow model: lets a client disconnect mid-run
        await asyncio.sleep(0.5)
    offered = [t.get("function", {}).get("name", "") for t in body.get("tools") or []]
    filtered = _user_marker(body.get("messages", []), "FILTER-TEST")  # upstream guardrail: empty answer, filtered
    if filtered:
        call, text = None, ""
    elif offered and _runaway(body.get("messages", [])):
        args = {"key": "zorbia"} if offered[0].endswith("lookup") else _minimal_args(body["tools"][0])
        call, text = (offered[0], args), None
    elif offered and not any(n == "lookup" or n.endswith("__lookup") for n in offered):
        # scenario toolsets (no canary tools): one call to the first offered tool, then a final answer.
        # Plumbing only: proves the harness wires scenario tools end to end; says nothing about behaviour.
        n_results = len(_tool_results(body.get("messages", [])))
        call, text = ((offered[0], _minimal_args(body["tools"][0])), None) if n_results == 0 else \
            (None, "Done (mock scenario run).")
    else:
        call, text = _plan(body.get("messages", []))
    if call and call[0] in ("lookup", "add"):  # use the names the harness offers (e.g. "mcp__canary__lookup")
        call = (next((n for n in offered if n == call[0] or n.endswith("__" + call[0])), call[0]), call[1])
    cid, created, model = f"chatcmpl-{uuid.uuid4().hex[:8]}", int(time.time()), body.get("model", "mock")
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    tc = None
    if call:
        tc = {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
              "function": {"name": call[0], "arguments": json.dumps(call[1])}}
    finish = "content_filter" if filtered else "tool_calls" if tc else "stop"

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
