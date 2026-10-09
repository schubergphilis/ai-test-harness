import importlib.util

import pytest

from common import ROOT


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setenv("CANARY_FIXTURE", str(ROOT / "compat/fixtures/canary.json"))
    monkeypatch.setenv("PROMPT_DIR", str(ROOT / "prompts"))
    monkeypatch.setenv("SCENARIO_DIR", str(ROOT / "compat/fixtures/scenarios"))
    monkeypatch.setenv("SCENARIO", "snitch-cli-bold")
    spec = importlib.util.spec_from_file_location("_tc", ROOT / "harnesses/_templates/python/tools_canary.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("args", [{"log_type": "internal", "log_name": "x"}, {}, None])
def test_bad_arguments_go_back_to_the_model(tools, args):
    """A model that leaves out an argument gets an error result it can fix, not a crashed run (KeyError before)."""
    out = tools.call("write_log", args)
    assert out.startswith("error: invalid arguments for write_log")
