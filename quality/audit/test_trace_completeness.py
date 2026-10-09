"""Audit-trail completeness (maps to EU AI Act Art. 12 record-keeping; does not show compliance).

One canary invocation per harness, with a unique session id. Its OTLP spans (received by the OTel
Collector's file exporter) must reconstruct who asked what, which tools ran, and which model answered.
"""
import json
import pathlib
import time
import uuid
from collections import Counter

import httpx
import pytest

from traces import is_llm_span, is_llm_span_any_convention, load_spans, spans_for_session, tool_name

_ROOT = pathlib.Path(__file__).parents[2]
CANARY_PROMPT = (_ROOT / "prompts/canary.md").read_text().removesuffix("\n")
KNOWN_NO_LLM_SPANS = {"pi"}  # pi-agent-core has no LLM instrumentation; spans are hand-built (known finding)
_cache: dict = {}


@pytest.fixture
def run(harness, target_url, trace_file):
    if harness in _cache:
        return _cache[harness]
    sid = f"audit-{harness}-{uuid.uuid4().hex[:8]}"
    r = httpx.post(f"{target_url}/invocations", json={"prompt": CANARY_PROMPT, "session_id": sid},
                   headers={"X-Agent-User": "audit-tester"}, timeout=300)
    r.raise_for_status()
    spans, deadline = [], time.time() + 45  # batch span processors flush every ~5 s
    while time.time() < deadline:
        spans = spans_for_session(load_spans(trace_file), sid)
        if any(tool_name(s) == "add" for s in spans) or (spans and time.time() > deadline - 30):
            time.sleep(6)  # let the remaining batches land
            spans = spans_for_session(load_spans(trace_file), sid)
            break
        time.sleep(2)
    _cache[harness] = {"sid": sid, "spans": spans, "response": r.json()}
    return _cache[harness]


def test_trace_exists(run):
    assert run["spans"], f"no spans with session.id={run['sid']}"


def test_user_id_recorded(run):
    assert any(s["attrs"].get("user.id") == "audit-tester" for s in run["spans"])


def test_tool_spans(run):
    counts = Counter(t for t in map(tool_name, run["spans"]) if t)
    assert counts["lookup"] >= 2 and counts["add"] >= 1, dict(counts)


def test_llm_span_any_convention(harness, run):
    """Audit question: is the model call recorded at all (GenAI semconv or OpenInference)?"""
    if harness in KNOWN_NO_LLM_SPANS:
        pytest.xfail("known finding: harness emits no LLM spans")
    assert any(is_llm_span_any_convention(s) for s in run["spans"])


def test_llm_span_genai_semconv(harness, run):
    """Standards question: is it recorded with OTel GenAI semantic conventions (gen_ai.request.model)?

    OpenInference (llm.*) is accepted as well: both are open conventions and a collector can map one to the other.
    Such a harness is skipped with the reason, so the convention stays visible in the report; no LLM span fails.
    """
    if harness in KNOWN_NO_LLM_SPANS:
        pytest.xfail("known finding: harness emits no LLM spans")
    if not any(is_llm_span(s) for s in run["spans"]) and any(map(is_llm_span_any_convention, run["spans"])):
        pytest.skip("accepted: OpenInference llm.* attributes instead of OTel GenAI gen_ai.*")
    assert any(is_llm_span(s) for s in run["spans"]), "no span with gen_ai.request.model or OpenInference llm.*"


def test_report(harness, run, record_property):
    keys = sorted({k for s in run["spans"] for k in s["attrs"] if k.startswith(("gen_ai.", "llm.", "openinference.", "session.", "user."))})
    record_property("spans", len(run["spans"]))
    record_property("attr_keys", ",".join(keys))
    pathlib.Path(__file__).with_name("results").joinpath(f"spans-{harness}.json").write_text(
        json.dumps({"session_id": run["sid"], "spans": run["spans"]}, indent=1))
