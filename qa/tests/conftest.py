"""Shared fixtures for the QA tooling tests (stdlib-only code under test; no network, no processes)."""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "qa"), str(ROOT / "scripts")]


def check(suite, harness, model, name, status="pass", details=None):
    return {"suite": suite, "harness": harness, "model": model, "check": name, "status": status, "details": details}


def metric(suite, harness, model, name, value, unit="ratio"):
    return {"suite": suite, "harness": harness, "model": model, "name": name, "value": value, "unit": unit}


def make_run(checks, metrics=(), models=("mock", "alpha"), suites=("conformance", "inspect", "supply", "safety"),
             harnesses=("h-one", "h-two"), run_id="20260101T000000Z_test"):
    summary = {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "fail", "error", "skip", "xfail")}
    return {
        "schema": "agentrt.qa.run/v1", "run_id": run_id, "started": "2026-01-01T00:00:00+00:00",
        "finished": "2026-01-01T00:01:00+00:00", "duration_s": 60.0, "git": {"sha": "abc1234", "dirty": False},
        "host": {"platform": "test", "python": "3.12"},
        "config": {"models": list(models), "suites": list(suites), "epochs": 1, "scorecard": False},
        "models": {m: f"upstream-{m}" for m in models},
        "harnesses": {h: {"package": f"pkg-{h}", "version": "1.0"} for h in harnesses},
        "summary": summary, "checks": list(checks), "metrics": list(metrics),
    }


@pytest.fixture
def mk():
    """Builders: mk.check(...), mk.metric(...), mk.run(...)."""
    class B:
        pass
    B.check, B.metric, B.run = staticmethod(check), staticmethod(metric), staticmethod(make_run)
    return B
