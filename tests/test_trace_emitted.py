import datetime as dt
import time


def test_trace_in_langfuse(canary_run, langfuse, client):
    """The canary run shows up in Langfuse under its session id (ingestion is async, so poll)."""
    since = dt.datetime.fromtimestamp(canary_run["started"] - 5, tz=dt.UTC).isoformat()
    deadline = time.time() + 60
    traces = []
    while time.time() < deadline:
        r = client.get(
            f"{langfuse['host']}/api/public/traces",
            params={"fromTimestamp": since, "sessionId": canary_run["session_id"], "limit": 50},
            headers=langfuse["headers"],
        )
        r.raise_for_status()
        traces = r.json().get("data", [])
        if traces:
            break
        time.sleep(3)
    assert traces, f"no Langfuse trace with sessionId={canary_run['session_id']}"
