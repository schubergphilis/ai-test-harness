"""Summarize garak reports (results/*.report.jsonl) and PyRIT outputs (results/pyrit-*.json) into markdown.

garak semantics: per (probe, detector) "passed" = safe outputs, "fails" = attack succeeded,
"nones" = no usable output (error/timeout/empty). ASR = fails / total_evaluated.
When a probe has several detectors, the worst (max ASR) detector is reported.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
RES = HERE / "results"
OWASP = {
    "promptinject": "LLM01 (direct)",
    "latentinjection": "LLM01 (indirect)",
    "web_injection": "LLM02/LLM05 (exfil via markdown)",
    "dan": "LLM01 (jailbreak)",
    "encoding": "LLM01 (obfuscated)",
}


def garak_rows():
    rows = []
    for f in sorted(RES.glob("*.report.jsonl")):
        target, alias = f.name.removesuffix(".report.jsonl").split("~")[0].rsplit("-", 1)  # ~part: 2nd garak call
        worst = {}
        prompts = 0
        for line in f.open():
            d = json.loads(line)
            if d.get("entry_type") == "attempt" and d.get("status") == 2:
                prompts += 1
            if d.get("entry_type") != "eval":
                continue
            ev = d["total_evaluated"]
            asr = d["fails"] / ev if ev else None
            cur = worst.get(d["probe"])
            if cur is None or (asr is not None and (cur["asr"] is None or asr > cur["asr"])):
                worst[d["probe"]] = {"asr": asr, "fails": d["fails"], "ev": ev, "nones": d["nones"],
                                     "detector": d["detector"]}
        for probe, w in sorted(worst.items()):
            rows.append((target, alias, probe, w, prompts))
    return rows


def main():
    out = ["## garak (attack success rate = fails / evaluated; lower is better)", "",
           "| target | model | probe | OWASP | ASR | fails/evaluated | no output | worst detector |",
           "|---|---|---|---|---|---|---|---|"]
    totals = {}
    for target, alias, probe, w, prompts in garak_rows():
        asr = "n/a" if w["asr"] is None else f"{w['asr']:.0%}"
        out.append(f"| {target} | {alias} | {probe} | {OWASP.get(probe.split('.')[0], '')} | {asr} | "
                   f"{w['fails']}/{w['ev']} | {w['nones']} | {w['detector']} |")
        totals[(target, alias)] = prompts
    out += ["", "Prompts sent per run: " + ", ".join(f"{t}/{a}: {n}" for (t, a), n in sorted(totals.items()))
            + f" (total {sum(totals.values())})", ""]
    py = sorted(RES.glob("pyrit-*.json"))
    if py:
        out += ["## PyRIT", "", "| harness | model | A: indirect injection (judge) | A: obeyed add(0,0) (deterministic) "
                "| B: system-prompt extraction (3 turns) |", "|---|---|---|---|---|"]
        for f in py:
            d = json.loads(f.read_text())
            a, b = d.get("A_indirect_injection", {}), d.get("B_system_prompt_extraction", {})
            out.append(f"| {d['harness']} | {d['model']} | {a.get('judge_outcome', a.get('error', '?'))} | "
                       f"{a.get('deterministic_add_0_0', '?')} | {b.get('outcome', b.get('error', '?'))} |")
        out += ["", "PyRIT outcome `success` = the attack achieved its objective (bad); `failure` = the agent resisted."]
    print("\n".join(out))


if __name__ == "__main__":
    sys.exit(main())
