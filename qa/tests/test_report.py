import report

EVIL = '<script>alert("x")</script>'


def full_run(mk, **kw):
    c, m = mk.check, mk.metric
    checks = [
        c("conformance", "h-one", "mock", "test_ping"), c("conformance", "h-two", "mock", "test_ping"),
        c("conformance", "h-one", "alpha", "test_canary_answer"),
        c("conformance", "h-two", "alpha", "test_canary_answer", "fail", EVIL),
        c("inspect", "h-one", "alpha", "canary.all_epochs_pass"),
        c("inspect", "h-one", "alpha", "variants.all_epochs_pass"),
        c("supply", "h-one", "-", "no_high_vulns"), c("supply", "h-two", "-", "no_high_vulns", "xfail", "known: cve"),
        c("safety", "h-one", "alpha", "dan.Dan/mitigation.X", "fail", "ASR 6/10 = 60% (limit: ceiling 20%)"),
    ]
    metrics = [
        m("inspect", "h-one", "alpha", "canary.accuracy", 1.0),
        m("inspect", "h-one", "alpha", "variants.accuracy", 0.9),
        m("inspect", "h-one", "alpha", "injection.accuracy", 1.0),
        m("inspect", "h-one", "alpha", "injection.injection_disclosed", 0.3),
        m("inspect", "h-one", "alpha", "canary.latency_mean", 2.5, "s"),
        m("supply", "h-one", "-", "dependencies", 40, "count"), m("supply", "h-one", "-", "vulns_high", 0, "count"),
        m("safety", "h-one", "alpha", "asr.dan.Dan/mitigation.X", 0.6),
        m("safety", "model", "alpha", "asr.dan.Dan/x", 0.5),
    ]
    return mk.run(checks, metrics, **kw)


def test_render_smoke(mk):
    html = report.render(full_run(mk), None)
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    for text in ("At a glance", "Needs attention", "EU AI Act evidence map", "Testing details", "h-one", "h-two"):
        assert text in html
    assert "First run" in html


def test_render_escapes_details(mk):
    html = report.render(full_run(mk), None)
    assert EVIL not in html
    assert "&lt;script&gt;" in html


def test_needs_attention_lists_failures_and_known(mk):
    html = report.render(full_run(mk), None)
    attention = html.split("Needs attention")[1].split("At a glance")[0]
    assert "Red-team" in attention and "ceiling 20%" in attention   # failing safety probe, with reason
    assert "Discloses" in attention                                 # 30% disclosure = weak
    assert "Supply chain" in attention                              # known finding


def test_render_with_previous_run_shows_changes(mk):
    prev = mk.run([mk.check("conformance", "h-two", "alpha", "test_canary_answer")], run_id="20250101T000000Z_prev")
    html = report.render(full_run(mk), prev)
    assert "Changes since previous run" in html and "regression" in html


def test_render_all_green(mk):
    run = mk.run([mk.check("conformance", h, "mock", "test_ping") for h in ("h-one", "h-two")],
                 suites=("conformance",), models=("mock",))
    assert "Everything green" in report.render(run, None)


def test_render_index(mk, tmp_path):
    import json
    for rid in ("20260101T000000Z_a", "20260102T000000Z_b"):
        (tmp_path / rid).mkdir()
        (tmp_path / rid / "run.json").write_text(json.dumps(full_run(mk, run_id=rid)))
    report.render_index(tmp_path)
    index = (tmp_path / "index.html").read_text()
    assert index.index("20260102T000000Z_b") < index.index("20260101T000000Z_a")  # newest first
