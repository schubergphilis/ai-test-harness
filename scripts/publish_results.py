"""Publish a sanitized snapshot of a QA run.

    python3 scripts/publish_results.py [runs/<run_id>] [--out published-results]

Writes <out>/<run_id>/ with:
  run.json      scrubbed: repo path -> ".", host platform dropped, URL- and key-looking strings redacted
                (model alias -> upstream model name is kept)
  report.html   re-rendered from the scrubbed run.json
  quality/<suite>/summary.md   copies of the track summaries (scrubbed the same way)

Deliberately NOT copied: garak hitlogs/reports (attack prompts + model replies), Inspect .eval logs, OTel traces,
process logs, raw SBOM/OSV/Scorecard JSON (their counts are in run.json).

Afterwards the output is verified: no absolute paths, no non-allowlisted URLs, no key-like strings, and
gitleaks (if installed) must report no leaks. Exit 1 on any finding; the output is left in place for
inspection but must not be committed.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qa"))

URL_ALLOWED = r"(?:localhost|127\.0\.0\.1|github\.com|docs\.|www\.contributor-covenant\.org)"
URL_BAD = re.compile(rf"https?://(?!{URL_ALLOWED})[^\s\"'<>)]+")
KEY_LIKE = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|AKIA[0-9A-Z]{16}|pk-lf-[A-Za-z0-9\-]{8,}|sk-lf-[A-Za-z0-9\-]{8,}|"
                      r"gh[pousr]_[A-Za-z0-9]{30,}|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,})")
# /home/agent is the scenarios' fake home directory (compat/fixtures/scenarios), not a real path
LOCAL_PATH = re.compile(r"(?:/Users/|/private/|/var/folders/|/home/(?!agent\b))[^\s\"'<>]*")
# non-loopback IPv4 (with optional :port): proxy, cluster and LAN addresses
IP_ADDR = re.compile(r"\b(?!127\.)(?!0\.0\.0\.0\b)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}"
                     r"(?::\d{1,5})?\b")


def scrub_text(s: str) -> str:
    s = s.replace(str(ROOT), ".")
    s = LOCAL_PATH.sub("[path]", s)
    s = URL_BAD.sub("[url]", s)
    s = IP_ADDR.sub("[ip]", s)
    return KEY_LIKE.sub("[redacted]", s)


def scrub(obj):
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


def verify(out: pathlib.Path) -> list[str]:
    problems = []
    for f in out.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(errors="replace")
        for label, rx in [("absolute path", LOCAL_PATH), ("url", URL_BAD), ("ip address", IP_ADDR),
                          ("key-like string", KEY_LIKE)]:
            m = rx.search(text)
            if m:
                problems.append(f"{f.relative_to(out)}: {label}: {m.group(0)[:60]}")
    if shutil.which("gitleaks"):
        r = subprocess.run(["gitleaks", "dir", str(out), "--no-banner", "--redact", "--exit-code", "3"],
                           capture_output=True, text=True)
        if r.returncode == 3:
            problems.append("gitleaks: leaks found\n" + (r.stdout + r.stderr)[-1500:])
        elif r.returncode != 0:
            problems.append(f"gitleaks failed to run (exit {r.returncode}): {(r.stderr or r.stdout)[-300:]}")
    else:
        print("warning: gitleaks not installed; only the built-in pattern checks ran", file=sys.stderr)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", nargs="?", help="run directory (default: latest in runs/)")
    ap.add_argument("--out", default=str(ROOT / "published-results"))
    a = ap.parse_args()

    runs = sorted((ROOT / "runs").glob("*/run.json"))
    src = pathlib.Path(a.run).resolve() if a.run else (runs[-1].parent if runs else None)
    if src is None or not (src / "run.json").exists():
        sys.exit("no run found; pass runs/<run_id>")
    run = json.loads((src / "run.json").read_text())
    out = pathlib.Path(a.out).resolve() / run["run_id"]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    run = scrub(run)
    run["host"] = {"python": run.get("host", {}).get("python")}  # platform/OS detail is not needed publicly
    run["published"] = {"by": "scripts/publish_results.py", "excluded": [
        "garak transcripts", "Inspect .eval logs", "OTel traces", "process logs", "raw SBOM/OSV/Scorecard"]}
    (out / "run.json").write_text(json.dumps(run, indent=1) + "\n")

    import report  # qa/report.py
    # issues.html quotes transcripts and red-team prompts: not published, so no link to it
    (out / "report.html").write_text(report.render(run, None, issues=False) + "\n")

    for summary in sorted((ROOT / "quality").glob("*/summary.md")):
        dest = out / "quality" / summary.parent.name / "summary.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(scrub_text(summary.read_text()))

    problems = verify(out)
    if problems:
        print(f"NOT SAFE TO PUBLISH: {out}", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"published (sanitized): {out}")
    for f in sorted(out.rglob("*")):
        if f.is_file():
            print("  " + str(f.relative_to(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
