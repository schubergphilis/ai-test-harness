import base64
import json
import os
import pathlib
import time
import uuid

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPAT = ROOT / "compat"


def _load(p):
    return json.loads((COMPAT / p).read_text())


@pytest.fixture(scope="session")
def target_url():
    return os.environ.get("TARGET_URL", "http://localhost:18081").rstrip("/")


@pytest.fixture(scope="session")
def canary():
    return _load("fixtures/canary.json")


@pytest.fixture(scope="session")
def schemas():
    return {
        "request": _load("schema/invocation-request.json"),
        "response": _load("schema/invocation-response.json"),
        "ping": _load("schema/ping-response.json"),
    }


@pytest.fixture(scope="session")
def client():
    with httpx.Client(timeout=float(os.environ.get("INVOKE_TIMEOUT", "300"))) as c:
        yield c


@pytest.fixture(scope="session")
def canary_run(client, target_url, canary):
    """Invoke the canary once per session; most tests assert on this single result."""
    session_id = f"conformance-{uuid.uuid4().hex[:12]}"
    started = time.time()
    r = client.post(
        f"{target_url}/invocations",
        json={"prompt": canary["prompt"], "session_id": session_id},
        headers={"X-Agent-User": "conformance-tester"},
    )
    return {"response": r, "session_id": session_id, "started": started, "elapsed": time.time() - started}


@pytest.fixture(scope="session")
def langfuse():
    host = os.environ.get("LANGFUSE_HOST")
    pk, sk = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    if not (host and pk and sk):
        pytest.skip("LANGFUSE_HOST/LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set")
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    return {"host": host.rstrip("/"), "headers": {"Authorization": f"Basic {auth}"}}
