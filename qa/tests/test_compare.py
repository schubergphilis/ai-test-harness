from compare import diff


def keys(rows):
    return {"/".join(r["key"]) for r in rows}


def test_pass_to_fail_is_regression(mk):
    old = mk.run([mk.check("conformance", "h-one", "mock", "test_ping")])
    new = mk.run([mk.check("conformance", "h-one", "mock", "test_ping", "fail")])
    d = diff(old, new)
    assert keys(d["regressions"]) == {"conformance/h-one/mock/test_ping"}
    assert not d["fixed"] and not d["missing"]


def test_error_counts_as_regression(mk):
    old = mk.run([mk.check("conformance", "h-one", "mock", "x")])
    new = mk.run([mk.check("conformance", "h-one", "mock", "x", "error")])
    assert len(diff(old, new)["regressions"]) == 1


def test_fail_to_pass_is_fixed_and_fail_to_xfail_is_accepted(mk):
    old = mk.run([mk.check("audit", "h-one", "mock", "a", "fail"), mk.check("audit", "h-two", "mock", "b", "fail")])
    new = mk.run([mk.check("audit", "h-one", "mock", "a", "pass"), mk.check("audit", "h-two", "mock", "b", "xfail")])
    d = diff(old, new)
    assert keys(d["fixed"]) == {"audit/h-one/mock/a"}
    assert keys(d["accepted"]) == {"audit/h-two/mock/b"}
    assert not d["regressions"]


def test_new_failing_check_is_new_failure_not_regression(mk):
    old = mk.run([])
    new = mk.run([mk.check("safety", "h-one", "alpha", "probe", "fail")])
    d = diff(old, new)
    assert keys(d["new_failures"]) == {"safety/h-one/alpha/probe"}
    assert not d["regressions"]


def test_missing_only_counts_previously_passing_checks_in_scope(mk):
    old = mk.run([mk.check("inspect", "h-one", "alpha", "gone_pass"),
                  mk.check("inspect", "h-one", "alpha", "gone_fail", "fail"),
                  mk.check("inspect", "h-one", "beta", "other_model")], models=("alpha", "beta"))
    new = mk.run([], models=("alpha",))
    d = diff(old, new)
    # gone_fail was failing (not a loss); other_model's model was not run this time (out of scope)
    assert keys(d["missing"]) == {"inspect/h-one/alpha/gone_pass"}


def test_missing_ignores_suites_not_run(mk):
    old = mk.run([mk.check("supply", "h-one", "-", "no_high_vulns")], suites=("supply",))
    new = mk.run([], suites=("conformance",))
    assert not diff(old, new)["missing"]


def test_metric_threshold(mk):
    old = mk.run([], [mk.metric("inspect", "h-one", "alpha", "lat", 1.0, "s"),
                      mk.metric("inspect", "h-two", "alpha", "lat", 1.0, "s")])
    new = mk.run([], [mk.metric("inspect", "h-one", "alpha", "lat", 1.1, "s"),
                      mk.metric("inspect", "h-two", "alpha", "lat", 2.0, "s")])
    d = diff(old, new, threshold=0.2)
    assert [("/".join(r["key"]), r["rel"]) for r in d["metric_changes"]] == [("inspect/h-two/alpha/lat", 1.0)]
    assert len(diff(old, new, threshold=0.05)["metric_changes"]) == 2


def test_identical_runs_have_no_changes(mk):
    run = mk.run([mk.check("conformance", "h-one", "mock", "x")], [mk.metric("inspect", "h-one", "mock", "m", 1)])
    assert all(not v for v in diff(run, run).values())
