"""Compat contract HTTP surface: GET /ping, POST /invocations on :8080.

With SCENARIO_EXEC=box each invocation gets its own box container (tools_canary.box_start), removed afterwards;
the response then carries a `sandbox` report of what the runtime saw.

Every run is bounded: AGENT_MAX_TURNS model calls (the harness) and RUN_TIMEOUT_S wall clock (here). A run is
cancelled when the client disconnects. A failed or cut-off run still answers 200, with `stop_reason`, `error` and
the tool calls executed so far, so callers can score partial behaviour.
"""
import asyncio
import contextlib
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import agent
import tools_canary

app = FastAPI()
log = logging.getLogger("uvicorn.error")


class InvocationRequest(BaseModel):
    prompt: str
    session_id: str | None = None


@app.get("/ping")
def ping():
    return {"status": "Healthy"}


async def _disconnected(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.5)


async def _bounded(prompt: str, session_id: str | None, user: str | None, request: Request) -> dict:
    tools_canary.record_calls()
    if not tools_canary.box_wanted():
        return await _run(prompt, session_id, user, request)
    try:
        box = await asyncio.to_thread(tools_canary.box_start)
    except RuntimeError as e:
        return tools_canary.partial("error", str(e))
    tools_canary.bind_box(box)  # here, not in the thread: the agent task copies this context
    try:
        result = await _run(prompt, session_id, user, request)
    finally:  # shielded: the box is removed even when this request is cancelled
        report = await asyncio.shield(asyncio.to_thread(tools_canary.box_finish, box))
    return {**result, "sandbox": report}


async def _run(prompt: str, session_id: str | None, user: str | None, request: Request) -> dict:
    task = asyncio.create_task(agent.run(prompt, session_id=session_id, user=user))
    gone = asyncio.create_task(_disconnected(request))
    done, _ = await asyncio.wait({task, gone}, timeout=tools_canary.RUN_TIMEOUT_S,
                                 return_when=asyncio.FIRST_COMPLETED)
    gone.cancel()
    if task in done:
        try:
            return task.result()
        except Exception as e:
            log.exception("run failed")
            return tools_canary.partial("error", f"{type(e).__name__}: {e}")
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
    if gone in done:
        return tools_canary.partial("cancelled", "client disconnected")
    return tools_canary.partial("timeout", f"run exceeded RUN_TIMEOUT_S={tools_canary.RUN_TIMEOUT_S:g}")


@app.post("/invocations")
async def invocations(req: InvocationRequest, request: Request):
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    user = request.headers.get("x-agent-user") or request.headers.get(
        "x-amzn-bedrock-agentcore-runtime-custom-agent-user"
    )
    result = await _bounded(req.prompt, req.session_id, user, request)
    return {
        "stop_reason": "end_turn",
        "error": None,
        **result,
        "harness": agent.HARNESS,
        "model": os.environ.get("MODEL", "sovereign"),
        "session_id": req.session_id,
        "user": user,
    }
