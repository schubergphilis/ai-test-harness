"""Helpers to read OTLP-JSON lines written by the collector's file exporter."""
import json
import pathlib


def _val(v: dict):
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            return v[k]
    if "arrayValue" in v:
        return [_val(x) for x in v["arrayValue"].get("values", [])]
    return None


def load_spans(path: str | pathlib.Path) -> list[dict]:
    """Flatten to [{service, trace_id, span_id, parent, name, attrs}]."""
    spans = []
    p = pathlib.Path(path)
    if not p.exists():
        return spans
    lines = p.read_text().splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            batch = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:  # the collector may still be writing its last line; the poll retries
                continue
            raise
        for rs in batch.get("resourceSpans", []):
            res = {a["key"]: _val(a["value"]) for a in rs.get("resource", {}).get("attributes", [])}
            for ss in rs.get("scopeSpans", []):
                scope = ss.get("scope", {}).get("name", "")
                for s in ss.get("spans", []):
                    spans.append({
                        "service": res.get("service.name"),
                        "scope": scope,
                        "trace_id": s.get("traceId"),
                        "span_id": s.get("spanId"),
                        "parent": s.get("parentSpanId"),
                        "name": s.get("name", ""),
                        "attrs": {a["key"]: _val(a["value"]) for a in s.get("attributes", [])},
                        "events": [e.get("name", "") for e in s.get("events", [])],
                    })
    return spans


def spans_for_session(spans: list[dict], session_id: str) -> list[dict]:
    """All spans in any trace where at least one span carries session.id == session_id."""
    traces = {s["trace_id"] for s in spans if s["attrs"].get("session.id") == session_id}
    return [s for s in spans if s["trace_id"] in traces]


def tool_name(span: dict) -> str | None:
    """Tool name per OTel GenAI semconv, with OpenInference / name-based fallbacks."""
    a = span["attrs"]
    if a.get("gen_ai.tool.name"):
        return a["gen_ai.tool.name"]
    if a.get("gen_ai.operation.name") == "execute_tool":
        return span["name"].removeprefix("execute_tool").strip() or None
    if a.get("openinference.span.kind") == "TOOL":
        return a.get("tool.name") or span["name"]
    return None


def is_llm_span(span: dict) -> bool:
    return "gen_ai.request.model" in span["attrs"]


def is_llm_span_any_convention(span: dict) -> bool:
    a = span["attrs"]
    return is_llm_span(span) or a.get("openinference.span.kind") == "LLM" or "llm.model_name" in a
