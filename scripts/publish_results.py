"""Publish a sanitized snapshot of a QA run.

    python3 scripts/publish_results.py [runs/<run_id>] [--out published-results]

Writes <out>/<run_id>/ with:
  run.json      scrubbed: repo path -> ".", host platform dropped, URL- and key-looking strings redacted
                (model alias -> upstream model name is kept)
  report.html   re-rendered from the scrubbed run.json
  issues.html   the issues in plain English with scenario/box evidence (scrubbed); garak hits are left out
  report.md, issues.md   the same two pages as Markdown (pandoc), readable on GitHub
  quality/<suite>/summary.md   copies of the track summaries (scrubbed the same way)

Deliberately NOT copied: garak hitlogs/reports (attack prompts + model replies, also not quoted in issues.html),
Inspect .eval logs, OTel traces, process logs, raw SBOM/OSV/Scorecard JSON (their counts are in run.json).

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


# reference links the report code itself writes (OWASP, MITRE, papers): public, kept. Any other URL is scrubbed.
REFERENCE_URLS = {u for f in ("issues.py", "report.py")
                  for u in URL_BAD.findall((ROOT / "qa" / f).read_text())}


def is_reference(url: str) -> bool:  # a reference, or a page under one (OWASP = ".../llmrisk/" + the risk)
    return any(url == u or (u.endswith("/") and url.startswith(u)) for u in REFERENCE_URLS)


def keep_reference(m: re.Match) -> str:
    return m[0] if is_reference(m[0]) else "[url]"


def scrub_text(s: str) -> str:
    s = s.replace(str(ROOT), ".")
    s = LOCAL_PATH.sub("[path]", s)
    s = URL_BAD.sub(keep_reference, s)
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


def PublishedRun(src: pathlib.Path, run: dict):  # noqa: N802  (a factory for an issues.Run)
    """issues.Run over the source run's transcripts, with the scrubbed run.json and no garak hits: those quote
    attack prompts and the model's replies (jailbreaks, hate-speech strings), which stay out of a public repo."""
    import issues

    class _Run(issues.Run):
        def __init__(self):
            super().__init__(src)
            self.run, self.checks, self.metrics = run, run["checks"], run["metrics"]

        def hits(self, harness, model):
            return []

    return _Run()


CELL = re.compile(r"<(t[hd])\b([^>]*)>(.*?)</\1>", re.S)


def flat_cells(table: str) -> str:
    """A table GFM can hold: no rowspan (the cell is repeated on each row it spans) and no block content in cells
    (pandoc writes `[TABLE]` for those)."""
    rows, pending = [], {}  # pending: column -> [cell html, rows left]
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.S):
        cells, col = [], 0
        for tag, attrs, body in CELL.findall(row):
            while col in pending:
                cells.append(pending[col][0])
                pending[col][1] -= 1
                if not pending[col][1]:
                    del pending[col]
                col += 1
            body = re.sub(r"</?(?:div|p|ul|ol|details|summary)\b[^>]*>|<br\s*/?>", " ", body)
            body = re.sub(r"<li\b[^>]*>", " · ", body).replace("</li>", "")
            body = re.sub(r"<small\b[^>]*>", " — ", body)
            cell = f"<{tag}>{' '.join(body.split())}</{tag}>"
            span = re.search(r"rowspan=['\"]?(\d+)", attrs)
            if span and int(span[1]) > 1:
                pending[col] = [cell, int(span[1]) - 1]
            cells.append(cell)
            col += 1
        while col in pending:
            cells.append(pending[col][0])
            pending[col][1] -= 1
            if not pending[col][1]:
                del pending[col]
            col += 1
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def md_ready(html: str) -> str:
    html = re.sub(r"<table\b.*?</table>", lambda m: flat_cells(m[0]), html, flags=re.S)
    html = re.sub(r"(<span class=\"dot[^>]*>[^<]*</span>)", r"\1 ", html)  # "✕ 1. ..." not "✕1. ..."
    return re.sub(r"<span class=badge>", " · ", html)


def markdown(out: pathlib.Path) -> None:
    """report.md / issues.md next to the HTML, via pandoc (GitHub renders Markdown; it shows .html as source)."""
    if not shutil.which("pandoc"):
        print("warning: pandoc not installed; no Markdown versions written", file=sys.stderr)
        return
    for name in ("report", "issues"):
        r = subprocess.run(["pandoc", "-f", "html", "-t", "gfm-raw_html", "--wrap=none"], check=True,
                           input=md_ready((out / f"{name}.html").read_text()), capture_output=True, text=True)
        md = r.stdout.replace("(report.html)", "(report.md)").replace("(issues.html)", "(issues.md)")
        md = md.replace(" · [all runs](../index.html)", "")
        (out / f"{name}.md").write_text(md)


def verify(out: pathlib.Path) -> list[str]:
    problems = []
    for f in out.rglob("*"):
        if not f.is_file():
            continue
        text = f.read_text(errors="replace")
        for label, rx in [("absolute path", LOCAL_PATH), ("url", URL_BAD), ("ip address", IP_ADDR),
                          ("key-like string", KEY_LIKE)]:
            m = next((m for m in rx.finditer(text) if not (rx is URL_BAD and is_reference(m[0]))), None)
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
        "garak transcripts (also in issues.html)", "Inspect .eval logs", "OTel traces", "process logs",
        "raw SBOM/OSV/Scorecard"]}
    (out / "run.json").write_text(json.dumps(run, indent=1) + "\n")

    import issues  # qa/issues.py

    import report  # qa/report.py

    (out / "report.html").write_text(report.render(run, None) + "\n")
    (out / "issues.html").write_text(scrub_text(issues.render(PublishedRun(src, run))) + "\n")
    markdown(out)

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
