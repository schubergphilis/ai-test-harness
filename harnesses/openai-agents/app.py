"""Compat contract HTTP surface: GET /ping, POST /invocations on :8080."""
import os

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import agent

app = FastAPI()


class InvocationRequest(BaseModel):
    prompt: str
    session_id: str | None = None


@app.get("/ping")
def ping():
    return {"status": "Healthy"}


@app.post("/invocations")
async def invocations(req: InvocationRequest, request: Request):
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    user = request.headers.get("x-agent-user") or request.headers.get(
        "x-amzn-bedrock-agentcore-runtime-custom-agent-user"
    )
    result = await agent.run(req.prompt, session_id=req.session_id, user=user)
    return {
        **result,
        "harness": agent.HARNESS,
        "model": os.environ.get("MODEL", "sovereign"),
        "session_id": req.session_id,
        "user": user,
    }
