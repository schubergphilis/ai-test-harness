"""Parallel per-model runs: checkpoints for suites that cannot resume themselves, per-model concurrency."""
import json

import run


def _ok():
    return [{"id": "c/ok", "status": "pass"}], {"m": 1}


def test_checkpoint_saved_and_reused(tmp_path):
    windows = []
    calls = []

    def fn():
        calls.append(1)
        windows.append({"suite": "audit"})
        return _ok()

    assert run.checkpointed(tmp_path, "m", "conformance+audit", set(), fn, windows) == _ok()
    saved = json.loads((tmp_path / "m/checkpoints/conformance+audit.json").read_text())
    assert saved["windows"] == [{"suite": "audit"}]
    again = []
    assert run.checkpointed(tmp_path, "m", "conformance+audit", set(), fn, again) == _ok()
    assert len(calls) == 1
    assert again == [{"suite": "audit"}]


def test_checkpoint_redo_reruns(tmp_path):
    calls = []

    def fn():
        calls.append(1)
        return _ok()

    run.checkpointed(tmp_path, "m", "conformance+audit", set(), fn, [])
    run.checkpointed(tmp_path, "m", "conformance+audit", {"audit"}, fn, [])
    assert len(calls) == 2


def test_checkpoint_not_saved_on_error(tmp_path):
    def fn():
        return [{"id": "c/x", "status": "error"}], {}

    run.checkpointed(tmp_path, "m", "inspect", set(), fn, [])
    assert not (tmp_path / "m/checkpoints/inspect.json").exists()


def test_model_concurrency(monkeypatch):
    monkeypatch.setattr(run.registry, "models", lambda: [{"alias": "fast", "concurrency": 6}, {"alias": "slow"}])
    assert run.model_concurrency("fast", None) == 6
    assert run.model_concurrency("slow", None) == 2
    assert run.model_concurrency("fast", 3) == 3
