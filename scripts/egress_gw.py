"""Proxy-only egress for agent containers ([[runtime]] egress = "proxy-only" in harnesses.toml).

The agent container goes on its own `--internal` Docker network: no route anywhere, external names do not resolve.
A gateway container (runtimes/egress-gw, socat) sits on that network and on the default one and forwards a fixed
list of host ports (the LiteLLM proxy, the OTLP collector) and nothing else. Inside the agent container
host.docker.internal points at the gateway, so the agent's settings are the same as without it. The published API
port goes through the gateway too: Docker does not publish ports of containers on an internal network only.

    up(name, agent, [4000], publish=18706)  -> docker run args for the agent container
    down(name)                              -> remove gateway and network (idempotent)
    python3 scripts/egress_gw.py up|down NAME [--agent C] [--forward 4000 ...] [--publish PORT]
"""
import argparse
import subprocess
import sys

IMAGE = "agentrt/egress-gw:dev"
LABEL = "agentrt=egress"
GW_RUN = ["--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "32m",
          "--pids-limit", "64", "--add-host", "host.docker.internal:host-gateway"]


def _docker(*args: str, check: bool = True) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise RuntimeError(f"docker {args[0]} {args[1] if len(args) > 1 else ''}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def socat_script(forwards: list[int], agent: str | None) -> str:
    """One socat per allowed host port; the inbound one (8080 -> agent:8080) only when the API is published."""
    fw = [f"socat TCP-LISTEN:{p},fork,reuseaddr TCP:host.docker.internal:{p} &" for p in forwards]
    if agent:
        fw.append(f"socat TCP-LISTEN:8080,fork,reuseaddr TCP:{agent}:8080 &")
    return " ".join([*fw, "wait"])


def up(name: str, agent: str | None, forwards: list[int], publish: int | None = None) -> list[str]:
    down(name)
    net = f"{name}-net"
    _docker("network", "create", "--internal", "--label", LABEL, net)
    pub = ["-p", f"127.0.0.1:{publish}:8080"] if publish else []
    _docker("run", "-d", "--rm", "--pull", "never", "--name", name, "--label", LABEL, *GW_RUN, *pub, IMAGE,
            socat_script(forwards, agent if publish else None))
    _docker("network", "connect", net, name)
    ip = _docker("inspect", "-f", f'{{{{(index .NetworkSettings.Networks "{net}").IPAddress}}}}', name)
    if not ip:
        down(name)
        raise RuntimeError(f"egress gateway {name} has no address on {net}")
    return ["--network", net, "--add-host", f"host.docker.internal:{ip}"]


def down(name: str) -> None:
    _docker("rm", "-f", name, check=False)
    _docker("network", "rm", f"{name}-net", check=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["up", "down"])
    ap.add_argument("name")
    ap.add_argument("--agent", help="agent container name (for the published API port)")
    ap.add_argument("--forward", type=int, action="append", default=[], help="host port the agent may reach")
    ap.add_argument("--publish", type=int, help="host port for the agent's API (127.0.0.1)")
    a = ap.parse_args()
    if a.cmd == "up":
        print("\n".join(up(a.name, a.agent, a.forward, a.publish)))
    else:
        down(a.name)


if __name__ == "__main__":
    sys.exit(main())
