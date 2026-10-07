"""Summarize Inspect logs in results/logs -> markdown table (harness x alias x task)."""
import statistics
import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

log_dir = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "results" / "logs")
rows = {}
for info in list_eval_logs(log_dir):
    log = read_eval_log(info, header_only=False)
    if log.status != "success" or not log.results:
        continue
    harness, _, alias = log.eval.model.split("/", 1)[1].partition("@")
    key = (harness, alias, log.eval.task.split("@")[-1].split("/")[-1])
    metrics = {}
    for s in log.results.scores:  # one EvalScore per reducer
        metrics[s.reducer or s.name] = s.metrics["accuracy"].value
    lat, tin, tout, errors = [], 0, 0, 0
    for sample in log.samples or []:
        for sc in (sample.scores or {}).values():
            m = sc.metadata or {}
            if m.get("latency_s") is not None:
                lat.append(m["latency_s"])
            tin += m.get("input_tokens") or 0
            tout += m.get("output_tokens") or 0
            errors += bool(m.get("error"))
    p95 = sorted(lat)[max(0, int(round(0.95 * len(lat))) - 1)] if lat else None
    rows[key] = (log.eval.created, log.eval.config.epochs, len(log.samples or []), metrics,
                 statistics.mean(lat) if lat else None, p95, tin, tout, errors)

print("| harness | model | task | epochs | runs | accuracy | pass^3 | all epochs pass | mean s | p95 s | in tok | out tok | errors |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
tot_in = tot_out = tot_runs = 0
for (h, a, t), (_, ep, n, m, mean, p95, tin, tout, err) in sorted(rows.items()):
    allp = next((v for k, v in m.items() if k.startswith("at_least")), None)
    pk = next((v for k, v in m.items() if k.startswith("pass_k") or k.startswith("pass^")), None)
    f = lambda v: "" if v is None else f"{v:.2f}"
    print(f"| {h} | {a} | {t} | {ep} | {n} | {f(m.get('mean'))} | {f(pk)} | {f(allp)} | {f(mean)} | {f(p95)} | {tin} | {tout} | {err} |")
    tot_in, tot_out, tot_runs = tot_in + tin, tot_out + tout, tot_runs + n
print(f"\nTotal: {tot_runs} agent runs, {tot_in} input tokens, {tot_out} output tokens (latest log per harness/model/task).")
