"""Runtime footprint + process audit per harness, on the mock model (isolates harness overhead from the model).

Each harness is started alone, directly (`.venv/bin/uvicorn` or `node dist/server.js`, not via `uv run`), then:
  metrics  cold start to /ping, idle and peak RSS of the whole process tree, p50/p95 latency and CPU per canary
           invocation, number of processes spawned, install footprint on disk
  checks   no_lingering_children   no descendant process still alive after the requests finished (daemons)
           no_extra_listeners      the tree listens on no TCP port other than the harness port
           no_unexpected_egress    outbound TCP only to litellm (:4000) / the OTel collector (:4318)
           expected_executables    every executable in the tree is on the language allowlist
           no_host_probes          no OS keychain client (macOS `security`, libsecret) or hardware-id reader (`ioreg`)
           stops_runaway_loop      a prompt that makes the mock request tools forever: the harness ends the loop
                                   itself (turn limit / own timeout) within RUNAWAY_CLIENT_TIMEOUT_S
           respects_turn_limit     ...after at most AGENT_MAX_TURNS (+1) model calls, reporting stop_reason max_turns
           stops_after_client_disconnect  the same loop, client gives up after DISCONNECT_AFTER_S: the harness stops
                                   calling the model (skipped when the harness already finished by then)
Stdlib only (ps / lsof / du), macOS and Linux.
"""
import contextlib
import json
import os
import pathlib
import re
import signal
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request

from common import RUN_LIMITS, prompt

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED = {"python": {"python", "python3", "uvicorn"}, "node": {"node"}}
# the Agent SDK drives the Claude Code CLI as a child process; the CLI runs `git` in its (empty) cwd to look for a repo
# and settings, ripgrep for file search, and a shell for its helpers
EXTRA_ALLOWED = {"claude-code": {"claude", "git", "sh", "bash", "rg"}}
# host secrets and machine identity: OS keychain clients and hardware-id readers
HOST_PROBES = {"security", "secret-tool", "gnome-keyring-daemon", "kwallet-query", "ioreg", "system_profiler",
               "dmidecode"}
ALLOWED_REMOTE_PORTS = {4000, 4318}
MOCK = "http://127.0.0.1:14000"
RUNAWAY_CLIENT_TIMEOUT_S = 45
DISCONNECT_AFTER_S = 2
MAX_TURNS = int(RUN_LIMITS["AGENT_MAX_TURNS"])
RUNAWAY_PROMPT = prompt("perf/runaway")  # must contain RUNAWAY-TEST (the mock's endless-tool-loop trigger)
RUNAWAY_SLOW_PROMPT = prompt("perf/runaway-slow")  # + RUNAWAY-SLOW: the mock answers in 0.5 s, so the client can
CANARY_PROMPT = prompt("perf/canary")                # disconnect while the harness is still looping


def _ps() -> dict[int, dict]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss=,time=,comm="], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5:
            pid, ppid, rss, cpu, comm = parts
            procs[int(pid)] = {"ppid": int(ppid), "rss_kb": int(rss), "cpu_s": _cpu(cpu), "comm": comm}
    return procs


def _cpu(t: str) -> float:  # [[dd-]hh:]mm:ss[.ss]
    days, _, t = t.rpartition("-")
    secs = 0.0
    for part in t.split(":"):
        secs = secs * 60 + float(part)
    return secs + (int(days) * 86400 if days else 0)


def _tree(root: int, procs: dict) -> list[int]:
    pids, frontier = [], [root]
    while frontier:
        p = frontier.pop()
        if p in procs:
            pids.append(p)
            frontier += [c for c, v in procs.items() if v["ppid"] == p]
    return pids


def _exe(comm: str) -> str:
    """Executable name; '(name)' (exiting) -> name, '<defunct>' (zombie, not yet reaped) -> ''."""
    comm = comm.strip()
    if comm.startswith("<defunct>"):
        return ""
    return re.sub(r"\d+(\.\d+)*$", "", os.path.basename(comm.strip("()").split()[0]))


def _lsof(pids: list[int], *args) -> list[str]:
    if not pids:
        return []
    r = subprocess.run(["lsof", "-nP", "-a", "-p", ",".join(map(str, pids)), *args], capture_output=True, text=True)
    return r.stdout.splitlines()[1:]


def _post(url: str, body: dict, timeout=120) -> tuple[float, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read() or b"{}")
    return time.perf_counter() - t0, data


def _du_mb(*paths: pathlib.Path) -> float:
    total = 0
    for p in paths:
        if p.exists():
            total += int(subprocess.run(["du", "-sk", str(p)], capture_output=True, text=True).stdout.split()[0])
    return round(total / 1024, 1)


def _mock_calls() -> int:
    with urllib.request.urlopen(MOCK + "/stats", timeout=5) as r:
        return json.loads(r.read())["chat_calls"]


def _runaway_call(url: str, timeout: float, text: str = RUNAWAY_PROMPT) -> tuple[bool, float, dict]:
    urllib.request.urlopen(urllib.request.Request(MOCK + "/stats/reset", method="POST"), timeout=5).read()
    t0 = time.perf_counter()
    try:
        _, body = _post(url + "/invocations", {"prompt": text, "session_id": "runaway"}, timeout=timeout)
        returned = True
    except urllib.error.HTTPError as e:  # an error response still means the harness stopped the loop itself
        returned, body = True, {"stop_reason": f"HTTP {e.code}"}
    except Exception:  # client timeout: the harness was still looping
        returned, body = False, {}
    return returned, time.perf_counter() - t0, body


def runaway(url: str) -> dict:
    """Send a never-ending tool loop; see whether the harness stops it, and stops after the client disconnects."""
    returned, elapsed, body = _runaway_call(url, RUNAWAY_CLIENT_TIMEOUT_S)
    calls = _mock_calls()
    if not returned:  # the client gave up; let the harness wind down before the disconnect probe
        time.sleep(10)
    finished, _, _ = _runaway_call(url, DISCONNECT_AFTER_S, RUNAWAY_SLOW_PROMPT)
    after = None
    if not finished:  # the client has disconnected; does the harness keep calling the model?
        base = _mock_calls()
        time.sleep(10)
        after = _mock_calls() - base
    return {"returned": returned, "seconds": elapsed, "calls": calls, "stop_reason": body.get("stop_reason"),
            "calls_after_disconnect": after}


def measure(spec: dict, port: int, env: dict, invocations: int = 10) -> tuple[list[dict], list[dict]]:
    name, lang = spec["name"], spec["language"]
    hdir = ROOT / "harnesses" / name
    if lang == "node":
        cmd = ["node", "dist/server.js"]
    else:
        cmd = [str(hdir / ".venv/bin/uvicorn"), "app:app", "--host", "127.0.0.1", "--port", str(port)]
    base = {"suite": "perf", "harness": name, "model": "mock"}
    t0 = time.perf_counter()
    with open(ROOT / ".run" / f"perf-{name}.log", "w") as log:
        proc = subprocess.Popen(cmd, cwd=hdir, env={**env, "PORT": str(port), "HOST": "127.0.0.1"}, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    checks, metrics = [], []
    try:
        url = f"http://127.0.0.1:{port}"
        while True:
            try:
                urllib.request.urlopen(url + "/ping", timeout=1).read()
                break
            except Exception as err:
                if time.perf_counter() - t0 > 120 or proc.poll() is not None:
                    raise RuntimeError(f"{name} did not start") from err
                time.sleep(0.05)
        cold = time.perf_counter() - t0
        time.sleep(1)
        procs = _ps()
        idle_pids = _tree(proc.pid, procs)
        idle_rss = sum(procs[p]["rss_kb"] for p in idle_pids) / 1024
        cpu0 = sum(procs[p]["cpu_s"] for p in idle_pids)

        seen_exe, seen_pids, peak, egress = set(), set(idle_pids), [idle_rss], set()
        stop = threading.Event()

        def sampler():
            while not stop.is_set():
                ps = _ps()
                pids = _tree(proc.pid, ps)
                seen_pids.update(pids)
                seen_exe.update(_exe(ps[p]["comm"]) for p in pids)
                peak.append(sum(ps[p]["rss_kb"] for p in pids) / 1024)
                for line in _lsof(pids, "-iTCP", "-sTCP:ESTABLISHED"):
                    m = re.search(r":(\d+)->([\d.:\[\]a-f]+):(\d+)", line)
                    # skip inbound requests to the harness itself (local side = harness port)
                    if m and int(m.group(1)) != port and int(m.group(3)) not in ALLOWED_REMOTE_PORTS:
                        egress.add(f"{m.group(2)}:{m.group(3)}")
                time.sleep(0.1)

        th = threading.Thread(target=sampler, daemon=True)
        th.start()
        lat = [_post(url + "/invocations", {"prompt": CANARY_PROMPT, "session_id": f"perf-{i}"})[0]
               for i in range(invocations)]
        stop.set()
        th.join()
        procs = _ps()
        cpu1 = sum(procs[p]["cpu_s"] for p in _tree(proc.pid, procs))
        time.sleep(2)  # children of finished requests should be gone by now
        procs = _ps()
        after = _tree(proc.pid, procs)
        lingering = sorted({_exe(procs[p]["comm"]) or "zombie" for p in after if p not in idle_pids})
        listen = {m.group(1) for line in _lsof(after, "-iTCP", "-sTCP:LISTEN")
                  if (m := re.search(r":(\d+) \(LISTEN\)", line))}
        extra_listen = sorted(listen - {str(port)})
        allowed = ALLOWED[lang] | EXTRA_ALLOWED.get(name, set())
        probes = sorted(seen_exe & HOST_PROBES)
        unexpected = sorted(e for e in seen_exe if e and e not in allowed | HOST_PROBES)
        install = _du_mb(hdir / ".venv") if lang == "python" else _du_mb(hdir / "node_modules", hdir / "dist")

        ra = runaway(url)
        q = statistics.quantiles(lat, n=20) if len(lat) >= 2 else lat * 19
        for n, v, u in [("cold_start_s", cold, "s"), ("idle_rss_mb", idle_rss, "MB"), ("peak_rss_mb", max(peak), "MB"),
                        ("latency_p50_s", statistics.median(lat), "s"), ("latency_p95_s", q[18], "s"),
                        ("cpu_s_per_invocation", (cpu1 - cpu0) / len(lat), "s"),
                        ("processes_spawned", len(seen_pids - set(idle_pids)), "count"), ("install_mb", install, "MB"),
                        ("runaway_model_calls", ra["calls"], "count"), ("runaway_seconds", ra["seconds"], "s")]:
            metrics.append({**base, "name": n, "value": round(v, 3), "unit": u})
        for check, ok, detail in [
            ("no_lingering_children", not lingering, f"still running after requests: {', '.join(lingering)}"),
            ("no_extra_listeners", not extra_listen, f"also listening on: {', '.join(extra_listen)}"),
            ("no_unexpected_egress", not egress, f"outbound to: {', '.join(sorted(egress))}"),
            ("expected_executables", not unexpected, f"unexpected executables: {', '.join(unexpected)}"),
            ("no_host_probes", not probes, f"read host secrets / machine identity: {', '.join(probes)}"),
            ("stops_runaway_loop", ra["returned"], f"still looping after {RUNAWAY_CLIENT_TIMEOUT_S}s "
                                                   f"({ra['calls']} model calls); no turn limit or timeout"),
            ("respects_turn_limit", ra["calls"] <= MAX_TURNS + 1 and ra["stop_reason"] == "max_turns",
             f"{ra['calls']} model calls with AGENT_MAX_TURNS={MAX_TURNS}, stop_reason {ra['stop_reason']!r}"),
        ] + ([("stops_after_client_disconnect", ra["calls_after_disconnect"] <= 1,
               f"kept calling the model after the client gave up: {ra['calls_after_disconnect']} calls in 10 s")]
             if ra["calls_after_disconnect"] is not None else []):
            checks.append({**base, "check": check, "status": "pass" if ok else "fail",
                           "details": None if ok else detail})
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except Exception:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
    return checks, metrics
