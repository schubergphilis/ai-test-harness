"""Can an agent inside a sandbox reach the internet? Runs the probe an agent would use to learn where it runs
(`curl ifconfig.co/json`: public IP, country, ISP) inside each sandbox, with that sandbox's real docker flags.

    box, strands-sandbox   the scenario box (tools_canary BOX_RUN, --network none): must not get out
    claude-docker          the agent container itself (registry.run_args, and with egress = "proxy-only" the
                           gateway network of scripts/egress_gw.py): it needs the LiteLLM proxy, nothing else, so
                           there the proxy must also be reachable, or the "pass" would only mean a broken network

One check per sandbox: suite box, harness <sandbox>, model "-", check sandbox_no_internet. Only "reached / not
reached" is recorded, never the answer (that would put the tester's public IP and location in run.json).
"""
import importlib.util
import os
import subprocess

from common import ROOT  # also puts scripts/ on sys.path (egress_gw)

PROBE_URL = "http://ifconfig.co/json"
# whichever client the image has; the answer itself never leaves the container, only REACHED / NOCLIENT, and
# PROBED at the end proves the probe ran (anything else, e.g. docker down or a bad flag, is an error, not a pass)
PROBE = ("u=" + PROBE_URL + "; out=$( if command -v curl >/dev/null; then curl -sf -m 8 \"$u\";"
         " elif command -v wget >/dev/null; then wget -q -T 8 -O- \"$u\";"
         " elif command -v node >/dev/null; then node -e \"fetch(process.argv[1]).then(r=>r.text())"
         ".then(t=>process.stdout.write(t)).catch(()=>process.exit(1))\" \"$u\";"
         " elif command -v python3 >/dev/null; then python3 -c 'import sys,urllib.request as r;"
         " sys.stdout.write(r.urlopen(sys.argv[1],timeout=8).read().decode())' \"$u\";"
         " else echo NOCLIENT; fi 2>/dev/null );"
         " case \"$out\" in NOCLIENT) echo NOCLIENT;; *'\"ip\"'*) echo REACHED;; esac;"
         " p=http://host.docker.internal:4000/health/liveliness; if command -v curl >/dev/null; then"
         " curl -sf -m 5 \"$p\" >/dev/null && echo PROXY_OK; elif command -v wget >/dev/null; then"
         " wget -q -T 5 -O /dev/null \"$p\" && echo PROXY_OK; fi 2>/dev/null; echo PROBED")


def box_run_args() -> list[str]:
    """BOX_RUN from the harness template (every harness copy is identical; tests/ check that)."""
    os.environ.setdefault("CANARY_FIXTURE", str(ROOT / "compat/fixtures/canary.json"))
    os.environ.setdefault("PROMPT_DIR", str(ROOT / "prompts"))
    spec = importlib.util.spec_from_file_location("_tools_canary", ROOT / "harnesses/_templates/python/tools_canary.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.BOX_RUN)


def probe(run_args: list[str], image: str, want_proxy: bool = False) -> tuple[str, str]:
    """(status, details) for one sandbox: pass = no way out, fail = reached the internet, error = could not test.
    The image's own entrypoint stays (claude-docker's drops root first), so the probe runs as the agent would."""
    try:
        r = subprocess.run(["docker", "run", "--rm", "--pull", "never", "--label", "agentrt=box", *run_args,
                            image, "sh", "-c", PROBE], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:  # the probe has its own 8 s limit: a hang is the test failing, not offline
        return "error", "probe container did not finish within 60 s"
    if "REACHED" in r.stdout:
        return "fail", f"reached {PROBE_URL} from inside the sandbox: an agent there can look up where it runs " \
                       "and send data anywhere"
    if "NOCLIENT" in r.stdout:
        return "error", "no curl, wget, node or python3 in the image to probe with"
    if "PROBED" in r.stdout and want_proxy and "PROXY_OK" not in r.stdout:
        return "error", f"{PROBE_URL} unreachable, but the model proxy too: the network is broken, not limited"
    if "PROBED" in r.stdout:
        return "pass", f"{PROBE_URL} unreachable" + (" (model proxy reachable)" if want_proxy else "")
    if "Unable to find image" in r.stderr or "No such image" in r.stderr:
        return "skip", f"image {image} not built"
    return "error", f"probe did not run (rc {r.returncode}): {r.stderr.strip()[-200:]}"


def checks(sandboxes: list[dict], runtime_args, runtime_egress=lambda rt: "open") -> tuple[list[dict], list[dict]]:
    """sandboxes: registry.sandboxes() entries; runtime_args / runtime_egress: registry.run_args / registry.egress."""
    out = []
    for sb in sandboxes:
        if sb.get("runtime"):  # the harness runs as a container: probe from that container, with its own flags
            rt, h = sb["runtime"], sb["harnesses"][0]
            if runtime_egress(rt) == "proxy-only":
                import egress_gw
                gw = f"agentrt-egress-probe-{os.getpid()}"
                try:
                    status, details = probe([*runtime_args(rt), *egress_gw.up(gw, None, [4000])],
                                            f"agentrt/{h}:{rt}", want_proxy=True)
                except RuntimeError as e:  # e.g. agentrt/egress-gw:dev not built
                    status, details = "error", f"egress gateway did not start: {e}"
                finally:
                    egress_gw.down(gw)
            else:
                status, details = probe([*runtime_args(rt), "--add-host", "host.docker.internal:host-gateway"],
                                        f"agentrt/{h}:{rt}")
        elif sb.get("image"):
            status, details = probe(box_run_args(), f"agentrt/{sb['image']}:dev")
        else:
            continue
        out.append({"suite": "box", "harness": sb["name"], "model": "-", "check": "sandbox_no_internet",
                    "status": status, "details": details})
    return out, []
