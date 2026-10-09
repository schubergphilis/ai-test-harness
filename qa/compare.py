"""Diff two QA runs (run.json). Exit 1 on regressions (pass -> fail/error, or a passing check that disappeared).

    python3 qa/compare.py runs/<old> runs/<new> [--json] [--metric-threshold 0.2]

Metrics are reported when they move more than --metric-threshold (relative); they never fail the gate.
"""
import argparse
import json
import pathlib
import sys

OK = {"pass", "xfail", "skip"}


def load(p):
    p = pathlib.Path(p)
    return json.loads((p / "run.json" if p.is_dir() else p).read_text())


def key(r, field):
    return (r["suite"], r["harness"], r["model"], r[field])


def diff(old, new, threshold=0.2):
    oc = {key(c, "check"): c for c in old["checks"]}
    nc = {key(c, "check"): c for c in new["checks"]}
    shared_models = set(old["config"]["models"]) & set(new["config"]["models"])
    shared_suites = set(old["config"]["suites"]) & set(new["config"]["suites"])
    # runs restricted with --harness only cover those harnesses (box rows: <harness>@<sandbox>);
    # older run.json files have no config.harnesses
    harnesses = set(new["config"].get("harnesses") or ()) or None
    in_scope = lambda k: (k[0] in shared_suites and (k[2] in shared_models or k[2] == "-")  # noqa: E731
                          and (harnesses is None or k[1].split("@")[0] in harnesses or k[1] == "-"))
    out = {"regressions": [], "fixed": [], "accepted": [], "new_failures": [], "missing": [], "metric_changes": []}
    for k, c in nc.items():
        o = oc.get(k)
        if o is None:
            if c["status"] not in OK:
                out["new_failures"].append({"key": k, "status": c["status"], "details": c.get("details")})
        elif o["status"] in OK and c["status"] not in OK:
            out["regressions"].append({"key": k, "was": o["status"], "now": c["status"], "details": c.get("details")})
        elif o["status"] not in OK and c["status"] == "xfail":
            out["accepted"].append({"key": k, "was": o["status"], "now": c["status"], "details": c.get("details")})
        elif o["status"] not in OK and c["status"] in OK:
            out["fixed"].append({"key": k, "was": o["status"], "now": c["status"]})
    for k in oc:
        if k not in nc and in_scope(k) and oc[k]["status"] == "pass":
            out["missing"].append({"key": k, "was": oc[k]["status"]})
    om = {key(m, "name"): m["value"] for m in old["metrics"]}
    for m in new["metrics"]:
        k = key(m, "name")
        if k in om and isinstance(om[k], int | float) and om[k] != m["value"]:
            base = abs(om[k]) or 1.0
            rel = (m["value"] - om[k]) / base
            if abs(rel) >= threshold:
                out["metric_changes"].append({"key": k, "was": om[k], "now": m["value"], "rel": round(rel, 3),
                                              "unit": m.get("unit")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old", nargs="?", help="default: second-latest run in runs/")
    ap.add_argument("new", nargs="?", help="default: latest run in runs/")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--metric-threshold", type=float, default=0.2)
    a = ap.parse_args()
    runs = sorted((pathlib.Path(__file__).resolve().parent.parent / "runs").glob("*/run.json"))
    a.new = a.new or str(runs[-1])
    a.old = a.old or str(runs[-2])
    print(f"compare {pathlib.Path(a.old).parent.name if a.old.endswith('.json') else a.old} -> "
          f"{pathlib.Path(a.new).parent.name if a.new.endswith('.json') else a.new}")
    d = diff(load(a.old), load(a.new), a.metric_threshold)
    if a.json:
        print(json.dumps(d, indent=1, default=list))
    else:
        fmt = lambda k: "/".join(k)  # noqa: E731
        for name in ("regressions", "new_failures", "missing", "fixed", "accepted"):
            print(f"{name}: {len(d[name])}")
            for r in d[name]:
                print(f"  {fmt(r['key'])}: {r.get('was', '')} -> {r.get('now', r.get('status', 'gone'))}  "
                      f"{r.get('details') or ''}"[:200])
        print(f"metric_changes (>= {a.metric_threshold:.0%}): {len(d['metric_changes'])}")
        for r in d["metric_changes"]:
            print(f"  {fmt(r['key'])}: {r['was']} -> {r['now']} ({r['rel']:+.0%})")
    sys.exit(1 if d["regressions"] or d["missing"] else 0)


if __name__ == "__main__":
    main()
