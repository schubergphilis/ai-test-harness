import re
from collections import Counter


def _digits(s: str) -> list[int]:
    # accept 8888888, 8,888,888, 8.888.888, 8 888 888
    return [int(re.sub(r"[,.\s]", "", m)) for m in re.findall(r"\d[\d,.\s]*\d|\d", s)]


def test_canary_answer(canary_run, canary):
    body = canary_run["response"].json()
    assert canary["expected_total"] in _digits(body["output"]), body["output"]


def test_canary_tools(canary_run, canary):
    body = canary_run["response"].json()
    counts = Counter(tc["name"] for tc in body["tool_calls"])
    for name, n in canary["expected_tools"].items():
        assert counts[name] >= n, f"expected >= {n} x {name}, got {dict(counts)}"


def test_report(canary_run, record_property):
    body = canary_run["response"].json()
    record_property("harness", body.get("harness"))
    record_property("model", body.get("model"))
    record_property("latency_s", round(canary_run["elapsed"], 2))
    record_property("input_tokens", (body.get("usage") or {}).get("input_tokens"))
    record_property("output_tokens", (body.get("usage") or {}).get("output_tokens"))
