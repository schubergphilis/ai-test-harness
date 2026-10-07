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
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import registry  # noqa: E402  (harnesses.toml / models.toml)

HARNESSES = registry.names()


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
    """Start every registered harness natively on registry.port(name, purpose) and stop them (by PID) on exit."""

    def __init__(self, model: str, purpose: str, log_dir: pathlib.Path, otel_endpoint: str | None = None,
                 only: list[str] | None = None):
        self.model, self.purpose, self.log_dir, self.otel = model, purpose, log_dir, otel_endpoint
        self.names = only or HARNESSES
        self.procs: list[subprocess.Popen] = []

    def url(self, harness: str) -> str:
        return f"http://localhost:{registry.port(harness, self.purpose)}"

    def __enter__(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for spec in registry.harnesses():
            built = (ROOT / f"harnesses/{spec['name']}/dist/server.js").exists()
            if spec["name"] in self.names and spec["language"] == "node" and not built:
                subprocess.run(["npm", "run", "-s", "build"], cwd=ROOT / "harnesses" / spec["name"], check=True)
        base_env = {
            **os.environ,
            "CANARY_FIXTURE": str(ROOT / "compat/fixtures/canary.json"),
            "OPENAI_BASE_URL": "http://127.0.0.1:4000/v1",
            "OPENAI_API_KEY": os.environ.get("LITELLM_MASTER_KEY", "sk-local-dev"),
            "MODEL": self.model,
            "HOST": "127.0.0.1",  # native runs stay on loopback (containers bind 0.0.0.0)
        }
        if self.otel:
            base_env |= {"OTEL_EXPORTER_OTLP_ENDPOINT": self.otel, "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}
        for h in self.names:
            port = registry.port(h, self.purpose)
            env = {**base_env, "OTEL_SERVICE_NAME": f"agent-{h}", "PORT": str(port)}
            cmd = registry.start_command(h, port)
            log = open(self.log_dir / f"{h}.log", "w")
            self.procs.append(subprocess.Popen(cmd, cwd=ROOT / "harnesses" / h, env=env, stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=True))
        for h in self.names:
            if not wait_http(self.url(h) + "/ping"):
                raise RuntimeError(f"harness {h} did not start; see {self.log_dir}/{h}.log")
        return self

    def __exit__(self, *exc):
        for p in self.procs:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGTERM)
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
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
