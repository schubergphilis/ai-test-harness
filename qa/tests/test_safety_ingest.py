import json

import run


def _report(path, probe, detector, prompts, hits):
    lines = [{"entry_type": "attempt", "status": 2, "probe_classname": probe,
              "prompt": {"turns": [{"role": "user", "content": {"text": p}}]}} for p in prompts]
    lines.append({"entry_type": "eval", "probe": probe, "detector": detector, "fails": hits,
                  "total_evaluated": len(prompts)})
    with path.open("a") as f:
        f.writelines(json.dumps(x) + "\n" for x in lines)


def _checks(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    return {(c["harness"], c["check"]): c for c in run.suite_safety(out, tmp_path / "src")[0]}


def test_gate_against_baseline_on_same_prompts(tmp_path):
    (tmp_path / "src").mkdir()
    same = [f"doc {i}" for i in range(10)]
    _report(tmp_path / "src/model-alpha.report.jsonl", "latent.X", "base.T", same, 5)
    _report(tmp_path / "src/h-alpha.report.jsonl", "latent.X", "base.T", same, 9)
    c = _checks(tmp_path)[("h", "latent.X/base.T")]
    assert c["status"] == "fail" and "bare model 50%" in c["details"]


def test_baseline_on_other_prompts_is_not_compared(tmp_path):
    (tmp_path / "src").mkdir()
    _report(tmp_path / "src/model-alpha.report.jsonl", "latent.X", "base.T", [f"a {i}" for i in range(10)], 5)
    _report(tmp_path / "src/h-alpha.report.jsonl", "latent.X", "base.T", [f"b {i}" for i in range(10)], 9)
    c = _checks(tmp_path)[("h", "latent.X/base.T")]
    assert c["status"] == "error" and "different prompts (0/10 shared)" in c["details"]


def test_model_only_part_counts_as_baseline(tmp_path):
    (tmp_path / "src").mkdir()
    same = [f"doc {i}" for i in range(10)]
    _report(tmp_path / "src/model-alpha~extra.report.jsonl", "enc.B", "base.T", same, 2)
    _report(tmp_path / "src/h-alpha.report.jsonl", "enc.B", "base.T", same, 2)
    assert _checks(tmp_path)[("h", "enc.B/base.T")]["status"] == "pass"


def test_informational_detector_does_not_gate(tmp_path):
    (tmp_path / "src").mkdir()
    same = [f"dan {i}" for i in range(10)]
    _report(tmp_path / "src/model-alpha.report.jsonl", "dan.D", "mitigation.MitigationBypass", same, 4)
    _report(tmp_path / "src/h-alpha.report.jsonl", "dan.D", "mitigation.MitigationBypass", same, 6)
    c = _checks(tmp_path)[("h", "dan.D/mitigation.MitigationBypass")]
    assert c["status"] == "skip" and "60%" in c["details"] and "informational" in c["details"]


def _blocked_report(path, probe, detector, prompts, hits, empty, text):
    """garak report where `empty` replies were blocked by the provider: `text` is "" (harness) or None (bare model)."""
    lines = [{"entry_type": "attempt", "status": 2, "probe_classname": probe,
              "prompt": {"turns": [{"role": "user", "content": {"text": p}}]},
              "outputs": [{"text": text if i < empty else "answer"}],
              # the phrase-list detector scores a blocked (empty) reply as a hit too; hits go on the answered ones
              "detector_results": {detector: [1.0 if i < empty or i - empty < hits else 0.0]}}
             for i, p in enumerate(prompts)]
    n = len(prompts) - (empty if text is None else 0)  # garak drops None outputs, scores "" as resisted
    lines.append({"entry_type": "eval", "probe": probe, "detector": detector, "fails": hits, "total_evaluated": n})
    with path.open("a") as f:
        f.writelines(json.dumps(x) + "\n" for x in lines)


def test_provider_blocked_replies_are_not_counted_as_resisted(tmp_path):
    (tmp_path / "src").mkdir()
    same = [f"doc {i}" for i in range(10)]
    _blocked_report(tmp_path / "src/model-alpha.report.jsonl", "latent.X", "base.T", same, 2, 4, None)
    _blocked_report(tmp_path / "src/h-alpha.report.jsonl", "latent.X", "base.T", same, 5, 4, "")
    c = _checks(tmp_path)[("h", "latent.X/base.T")]
    # 5 hits over 6 answered (83%) against 2/6 (33%): over the limit; counting the 4 empty replies would hide it (50%)
    assert c["status"] == "fail" and "5/6" in c["details"] and "4 blocked by the provider" in c["details"]


def test_too_few_answered_is_skipped(tmp_path):
    (tmp_path / "src").mkdir()
    same = [f"doc {i}" for i in range(12)]
    _blocked_report(tmp_path / "src/h-alpha.report.jsonl", "web.M", "web.D", same, 1, 11, "")
    c = _checks(tmp_path)[("h", "web.M/web.D")]
    assert c["status"] == "skip" and "1/1" in c["details"] and "too few answered" in c["details"]
