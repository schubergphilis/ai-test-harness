"""Shared helpers for the QA runner: paths, .env loading, native harness lifecycle, JUnit parsing."""
import contextlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import egress_gw  # noqa: E402  (proxy-only network for container runtimes)

import registry  # noqa: E402  (harnesses.toml / models.toml)

HARNESSES = registry.names()
PROMPT_DIR = ROOT / "prompts"
# Run bounds every harness applies (compat/CONTRACT.md); recorded in run.json.
RUN_LIMITS = {"AGENT_MAX_TURNS": os.environ.get("AGENT_MAX_TURNS", "20"),
              "RUN_TIMEOUT_S": os.environ.get("RUN_TIMEOUT_S", "300")}
# Fixture + prompt paths for natively started harnesses (containers use the /app/... defaults).
FIXTURE_ENV = {"CANARY_FIXTURE": str(ROOT / "compat/fixtures/canary.json"),
               "SCENARIO_DIR": str(ROOT / "compat/fixtures/scenarios"), "PROMPT_DIR": str(PROMPT_DIR), **RUN_LIMITS}
# Host variables a natively started harness may see. Everything else (cloud credentials, tokens, the litellm key
# under its own name) stays out of the agent's environment.
_HOST_ENV = {"PATH", "HOME", "TMPDIR", "LANG", "SHELL", "USER", "LOGNAME", "TERM", "TZ",
             "DOCKER_HOST", "DOCKER_CONTEXT", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"}


def host_env() -> dict:
    return {k: v for k, v in os.environ.items() if k in _HOST_ENV or k.startswith("LC_")}


def prompt_meta(name: str) -> tuple[dict, str]:
    """prompts/<name>.md -> (front matter, text without the trailing newline). See prompts/README.md."""
    text, meta = (PROMPT_DIR / f"{name}.md").read_text(), {}
    if text.startswith("---\n"):
        head, text = text[4:].split("\n---\n", 1)
        meta = dict(line.split(":", 1) for line in head.splitlines() if line.strip())
        meta = {k.strip(): v.strip() for k, v in meta.items()}
    return meta, text.removesuffix("\n")


def prompt(name: str) -> str:
    return prompt_meta(name)[1]


def load_dotenv(path: pathlib.Path = ROOT / ".env") -> None:
    """Load KEY=VALUE lines into os.environ (existing env wins). Values never leave the process."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


def model_map() -> dict:
    """Alias -> upstream model name (no URLs or keys)."""
    return {m["alias"]: ("compat/mock-llm (deterministic)" if m["kind"] == "mock" else os.environ.get(m["model"], ""))
            for m in registry.models()}


def harness_versions() -> dict:
    out = {}
    for spec in registry.harnesses():
        h, pkg = spec["name"], spec["package"]
        if spec["language"] == "node":
            lock = json.loads((ROOT / f"harnesses/{h}/package-lock.json").read_text())
            out[h] = {"package": pkg, "version": lock["packages"].get(f"node_modules/{pkg}", {}).get("version")}
        else:
            lock = tomllib.loads((ROOT / f"harnesses/{h}/uv.lock").read_text())
            ver = next((p["version"] for p in lock.get("package", []) if p["name"] == pkg), None)
            out[h] = {"package": pkg, "version": ver}
    return out


def git_info() -> dict:
    def g(*a):
        r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"sha": g("rev-parse", "--short", "HEAD") or "nocommit", "dirty": bool(g("status", "--porcelain"))}


def wait_http(url: str, timeout: float = 90) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(1)
    return False


class Harnesses:
    """Start every registered harness natively on registry.port(name, purpose) and stop them (by PID) on exit.
    With `runtime` (a container [[runtime]], e.g. claude-docker) each harness runs instead as a container from
    agentrt/<harness>:<runtime> with that runtime's guardrail flags, on its own port range; removed on exit."""

    def __init__(self, model: str, purpose: str, log_dir: pathlib.Path, otel_endpoint: str | None = None,
                 only: list[str] | None = None, extra_env: dict | None = None, runtime: str | None = None):
        self.model, self.purpose, self.log_dir, self.otel = model, purpose, log_dir, otel_endpoint
        self.names = HARNESSES if only is None else only  # [] means none, not all
        self.extra_env = extra_env or {}
        self.runtime = runtime
        self.procs: list[subprocess.Popen] = []
        self.containers: list[str] = []
        self.gateways: list[str] = []  # egress gateways (scripts/egress_gw.py), removed after the containers

    def port(self, harness: str) -> int:
        if self.runtime:
            rt = next(r for r in registry.container_runtimes() if r["name"] == self.runtime)
            return registry.runtime_port(rt, harness)
        return registry.port(harness, self.purpose)

    def url(self, harness: str) -> str:
        return f"http://localhost:{self.port(harness)}"

    def __enter__(self):
        try:
            return self._start()
        except BaseException:
            self.__exit__()  # never orphan the harnesses that did start
            raise

    def _start(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        busy = [h for h in self.names if wait_http(self.url(h) + "/ping", timeout=0.5)]
        if busy:  # a leftover process would answer instead of the harness under test
            raise RuntimeError(f"port already in use for {', '.join(busy)}; stop the old harness first")
        for spec in registry.harnesses():
            hdir = ROOT / "harnesses" / spec["name"]
            dist = hdir / "dist/server.js"  # rebuild when missing or older than any source file
            built = dist.exists() and all(f.stat().st_mtime <= dist.stat().st_mtime for f in hdir.glob("src/**/*.ts"))
            if spec["name"] in self.names and spec["language"] == "node" and not built:
                subprocess.run(["npm", "run", "-s", "build"], cwd=ROOT / "harnesses" / spec["name"], check=True)
        base_env = {
            **host_env(),
            **FIXTURE_ENV,
            "OPENAI_BASE_URL": "http://127.0.0.1:4000/v1",
            "OPENAI_API_KEY": os.environ.get("LITELLM_MASTER_KEY", "sk-local-dev"),
            "MODEL": self.model,
            "HOST": "127.0.0.1",  # native runs stay on loopback (containers bind 0.0.0.0)
            **self.extra_env,
        }
        if self.otel:
            base_env |= {"OTEL_EXPORTER_OTLP_ENDPOINT": self.otel, "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}
        if self.runtime:
            return self._start_containers()
        for h in self.names:  # appended one by one: __exit__ must see every process started before a failure
            self.procs.append(self._spawn(h, base_env, "w"))
        for i, h in enumerate(self.names):  # one restart: a cold start can lose a race on a loaded machine
            for attempt in (1, 2):
                if self._ready(h, self.procs[i]):
                    break
                self._kill(self.procs[i])
                if attempt == 2:
                    raise RuntimeError(f"harness {h} did not start (2 attempts); see {self.log_dir}/{h}.log")
                print(f"  ! harness {h} not ready, restarting once")
                self.procs[i] = self._spawn(h, base_env, "a")
        return self

    def _spawn(self, h: str, base_env: dict, mode: str) -> subprocess.Popen:
        port = registry.port(h, self.purpose)
        env = {**base_env, "OTEL_SERVICE_NAME": f"agent-{h}", "PORT": str(port)}
        with open(self.log_dir / f"{h}.log", mode) as log:
            return subprocess.Popen(registry.start_command(h, port), cwd=ROOT / "harnesses" / h, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def _ready(self, h: str, p: subprocess.Popen | None = None) -> bool:
        """/ping answers within 180 s (cold imports are slow on a loaded machine) and the process still lives."""
        return wait_http(self.url(h) + "/ping", timeout=180) and (p is None or p.poll() is None)

    @staticmethod
    def _kill(p: subprocess.Popen) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            p.wait(timeout=10)

    def _start_containers(self):
        env = {  # only what the agent needs; fixtures and prompts are baked into the image under /app
            **RUN_LIMITS, "MODEL": self.model, "OPENAI_BASE_URL": "http://host.docker.internal:4000/v1",
            "OPENAI_API_KEY": os.environ.get("LITELLM_MASTER_KEY", "sk-local-dev"),
            **{k: v for k, v in self.extra_env.items() if k not in ("CANARY_FIXTURE", "SCENARIO_DIR", "PROMPT_DIR")},
        }
        if self.otel:
            env |= {"OTEL_EXPORTER_OTLP_ENDPOINT": self.otel.replace("localhost", "host.docker.internal")
                    .replace("127.0.0.1", "host.docker.internal"), "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}
        for h in self.names:
            self.containers.append(self._run_container(h, env))
        for i, h in enumerate(self.names):  # one restart, as for native harnesses
            for attempt in (1, 2):
                if self._ready(h):
                    break
                name = self.containers[i]
                logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=30)
                with open(self.log_dir / f"{h}.log", "a") as f:
                    f.write(logs.stdout + logs.stderr)
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
                for _ in range(30):  # --rm auto-removal can still hold the name for a moment
                    if subprocess.run(["docker", "inspect", name], capture_output=True).returncode:
                        break
                    time.sleep(0.5)
                if attempt == 2:
                    self.containers.pop(i)  # already removed; __exit__ must not overwrite the log just written
                    raise RuntimeError(f"harness {h} on {self.runtime} did not start (2 attempts); "
                                       f"see {self.log_dir}/{h}.log")
                print(f"  ! harness {h} on {self.runtime} not ready, restarting once")
                self.containers[i] = self._run_container(h, env)
        return self

    def _container_name(self, h: str) -> str:
        return f"agentrt-{h}-{self.runtime}-{os.getpid()}"

    def _harness_of(self, name: str) -> str:  # harness names contain dashes (openai-agents)
        return next((h for h in self.names if self._container_name(h) == name), name)

    def _run_container(self, h: str, env: dict) -> str:
        name = self._container_name(h)
        flags = [x for k, v in {**env, "OTEL_SERVICE_NAME": f"agent-{h}"}.items() for x in ("-e", f"{k}={v}")]
        if registry.egress(self.runtime) == "proxy-only":  # only LiteLLM (+ OTLP) reachable, via a gateway
            ports = [4000]
            if otel := env.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
                ports.append(urllib.parse.urlsplit(otel).port or 4318)
            gw = f"{name}-gw"
            net = egress_gw.up(gw, name, ports, publish=self.port(h))
            if gw not in self.gateways:
                self.gateways.append(gw)
        else:
            net = ["--add-host", "host.docker.internal:host-gateway", "-p", f"127.0.0.1:{self.port(h)}:8080"]
        # --pull never: only the locally built image
        r = subprocess.run(["docker", "run", "-d", "--rm", "--pull", "never", "--name", name, "--label",
                            f"agentrt=runtime-{self.runtime}", *registry.run_args(self.runtime), *flags, *net,
                            f"agentrt/{h}:{self.runtime}"], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise RuntimeError(f"{h} on {self.runtime} did not start: {r.stderr.strip()[:300]}")
        return name

    def __exit__(self, *exc):
        for name in self.containers:  # keep the container log next to the native ones
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=30)
                (self.log_dir / f"{self._harness_of(name)}.log").write_text(logs.stdout + logs.stderr)
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        for gw in self.gateways:
            with contextlib.suppress(OSError, subprocess.SubprocessError, RuntimeError):
                egress_gw.down(gw)
        for p in self.procs:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGTERM)
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)


def parse_junit(path: pathlib.Path) -> list[dict]:
    """JUnit XML -> [{name, classname, status, message, properties}]; status: pass|fail|error|skip|xfail."""
    root = ET.parse(path).getroot()  # noqa: S314  (our own pytest JUnit output, not untrusted input)
    out = []
    for case in root.iter("testcase"):
        status, message = "pass", None
        for tag in ("failure", "error", "skipped"):
            el = case.find(tag)
            if el is not None:
                message = (el.get("message") or "")[:500]
                status = {"failure": "fail", "error": "error", "skipped": "skip"}[tag]
                if tag == "skipped" and (el.get("type") == "pytest.xfail" or "xfail" in (message or "")):
                    status = "xfail"
        props = {p.get("name"): p.get("value") for p in case.iter("property")}
        out.append({"name": case.get("name"), "classname": case.get("classname"), "status": status,
                    "message": message, "properties": props, "time_s": float(case.get("time") or 0)})
    return out
