"""Rebuild the Inspect and scenario records of an existing run from saved logs/transcripts (no model calls),
e.g. after a scorer fix:

    # re-score saved logs with the current scorer (Inspect Python API; the CLI prompts interactively):
    #   cd quality/inspect && uv run python -c "from inspect_ai import score; from inspect_ai.log import \
    #     read_eval_log, write_eval_log; from agentrt_inspect.tasks import resists_injection; f='<log.eval>'; \
    #     write_eval_log(score(read_eval_log(f), resists_injection(), action='overwrite', display='none'), f)"
    python3 qa/recollect.py runs/<run_id>                                 # refresh run.json + report.html

Replaces the run's `inspect` checks/metrics, re-applies qa/known_findings.json, recomputes the summary and
records the recollection in run.json["recollected"].
"""
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import ROOT  # noqa: E402


def main():
    run_dir = pathlib.Path(sys.argv[1]).resolve()
    run = json.loads((run_dir / "run.json").read_text())
    suites = {"inspect"} | ({"scenarios", "box"} & set(run["config"]["suites"]))
    checks = [c for c in run["checks"] if c["suite"] not in suites]
    metrics = [m for m in run["metrics"] if m["suite"] not in suites]
    if suites & {"scenarios", "box"}:
        import scenarios
        for model in run["config"]["models"]:
            c, m = scenarios.rescore(run_dir, model)
            checks += c
            metrics += m
    for model in run["config"]["models"]:
        log_dir = run_dir / model / "inspect"
        if not log_dir.exists():
            continue
        cmd = ["uv", "run", "--project", ROOT / "quality/inspect", "python", ROOT / "qa/collect_inspect.py", log_dir]
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        d = json.loads(r.stdout)
        checks += d["checks"]
        metrics += d["metrics"]
    known = json.loads((ROOT / "qa/known_findings.json").read_text())["findings"]
    for c in checks:
        for k in known:
            if c["status"] == "fail" and all(k[f] in ("*", c[f]) for f in ("suite", "harness", "model", "check")):
                c["status"], c["details"] = "xfail", f"known: {k['reason']} (since {k['since']})"
    run["checks"], run["metrics"] = checks, metrics
    run["summary"] = {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "fail", "error", "skip", "xfail")}
    stamp = dt.datetime.now(dt.UTC).isoformat()
    run.setdefault("recollected", []).append({"at": stamp, "suites": sorted(suites)})
    (run_dir / "run.json").write_text(json.dumps(run, indent=1))
    print(f"recollected {run_dir.name}: {run['summary']}")
    subprocess.run([sys.executable, ROOT / "qa/report.py", run_dir], check=True)


if __name__ == "__main__":
    main()
