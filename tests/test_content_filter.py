import os

import pytest
from conftest import ROOT

# must contain FILTER-TEST: the mock then answers empty with finish_reason=content_filter
FILTER_PROMPT = (ROOT / "prompts/content-filter.md").read_text().removesuffix("\n")


@pytest.mark.skipif(os.environ.get("MODEL", "mock") != "mock", reason="needs the mock LLM's FILTER-TEST trigger")
def test_upstream_content_filter(client, target_url):
    """An upstream guardrail block is reported as stop_reason=content_filter, not as an error or an empty answer."""
    r = client.post(f"{target_url}/invocations", json={"prompt": FILTER_PROMPT, "session_id": "content-filter"})
    assert r.status_code == 200, r.text
    body = r.json()
    got = (body["stop_reason"], body["error"], body["output"], body["tool_calls"])
    assert got == ("content_filter", None, "", []), body
