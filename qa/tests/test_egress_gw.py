import egress
import egress_gw
import pytest


def test_socat_forwards_only_listed_ports():
    s = egress_gw.socat_script([4000, 4318], "agent-1")
    assert s.count("TCP:host.docker.internal:") == 2 and "TCP:agent-1:8080" in s and s.endswith("wait")
    assert "agent-1" not in egress_gw.socat_script([4000], None)


def test_up_builds_internal_network(monkeypatch):
    calls = []

    def fake(*args, check=True):
        calls.append(args)
        return "172.30.0.2" if args[0] == "inspect" else ""
    monkeypatch.setattr(egress_gw, "_docker", fake)
    args = egress_gw.up("gw", "agent", [4000], publish=18799)
    assert args == ["--network", "gw-net", "--add-host", "host.docker.internal:172.30.0.2"]
    create = next(c for c in calls if c[:2] == ("network", "create"))
    assert "--internal" in create
    run = next(c for c in calls if c[0] == "run")
    assert "127.0.0.1:18799:8080" in run and "--read-only" in run and "ALL" in run


def test_up_without_address_fails_and_cleans_up(monkeypatch):
    calls = []
    monkeypatch.setattr(egress_gw, "_docker", lambda *a, check=True: calls.append(a) or "")
    with pytest.raises(RuntimeError):
        egress_gw.up("gw", None, [4000])
    assert calls[-2:] == [("rm", "-f", "gw"), ("network", "rm", "gw-net")]


@pytest.mark.parametrize(("stdout", "status"), [
    ("PROXY_OK\nPROBED\n", "pass"),
    ("PROBED\n", "error"),                 # proxy unreachable too: broken, not limited
    ("REACHED\nPROXY_OK\nPROBED\n", "fail"),
])
def test_proxy_only_probe(monkeypatch, stdout, status):
    monkeypatch.setattr(egress.subprocess, "run",
                        lambda cmd, **kw: type("R", (), {"stdout": stdout, "stderr": "", "returncode": 0})())
    assert egress.probe([], "img", want_proxy=True)[0] == status


def test_checks_use_gateway_for_proxy_only(monkeypatch):
    seen, downs = [], []
    monkeypatch.setattr(egress_gw, "up", lambda name, agent, ports, publish=None: ["--network", f"{name}-net"])
    monkeypatch.setattr(egress_gw, "down", downs.append)
    monkeypatch.setattr(egress, "probe", lambda args, image, want_proxy=False: seen.append((args, want_proxy))
                        or ("pass", "ok"))
    egress.checks([{"name": "cd", "harnesses": ["claude-code"], "runtime": "rt"}], lambda rt: ["--g"],
                  lambda rt: "proxy-only")
    assert seen[0][1] is True and "--network" in seen[0][0] and "host-gateway" not in " ".join(seen[0][0])
    assert len(downs) == 1
