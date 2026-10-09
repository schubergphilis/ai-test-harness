import re
import subprocess
import types

import egress
import pytest

from common import ROOT

COPIES = [*sorted(ROOT.glob("harnesses/*/tools_canary.py")), *sorted(ROOT.glob("harnesses/*/src/scenario.ts"))]


@pytest.mark.parametrize("path", COPIES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_box_has_no_network(path):
    """The box egress self-test probes one copy of BOX_RUN; every harness must use the same isolation."""
    m = re.search(r"BOX_RUN\s*=\s*\[(.*?)\];?\n", path.read_text(), re.S)
    assert m, "no BOX_RUN"
    flags = re.findall(r"""["']([^"']+)["']""", m.group(1))
    assert "--network" in flags and flags[flags.index("--network") + 1] == "none"
    assert "--privileged" not in flags and not any(f.startswith(("-v", "--volume", "--mount")) for f in flags)


def test_box_run_args_from_template():
    assert egress.box_run_args()[:3] == ["--init", "--network", "none"]


@pytest.mark.parametrize(("stdout", "stderr", "status"), [
    ("REACHED\nPROBED\n", "", "fail"),
    ("PROBED\n", "", "pass"),
    ("NOCLIENT\nPROBED\n", "", "error"),
    ("", "Cannot connect to the Docker daemon", "error"),
    ("", "Unable to find image 'agentrt/x:y' locally", "skip"),
])
def test_probe_status(monkeypatch, stdout, stderr, status):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    got, _ = egress.probe(["--network", "none"], "agentrt/box:dev")
    assert got == status
    assert seen["cmd"][-3:-1] == ["sh", "-c"] and "--entrypoint" not in seen["cmd"]


def test_checks_one_per_sandbox(monkeypatch):
    calls = []
    monkeypatch.setattr(egress, "probe", lambda args, image: calls.append((args, image)) or ("pass", "ok"))
    sbs = [{"name": "box", "harnesses": ["*"], "image": "box"},
           {"name": "cd", "harnesses": ["claude-code"], "runtime": "claude-docker"},
           {"name": "sim", "harnesses": ["x"]}]
    checks, metrics = egress.checks(sbs, lambda rt: ["--rt", rt])
    assert [(c["harness"], c["model"], c["check"]) for c in checks] == [
        ("box", "-", "sandbox_no_internet"), ("cd", "-", "sandbox_no_internet")]
    assert calls[0][1] == "agentrt/box:dev" and "none" in calls[0][0]
    assert calls[1] == (["--rt", "claude-docker", "--add-host", "host.docker.internal:host-gateway"],
                        "agentrt/claude-code:claude-docker")
    assert metrics == []
