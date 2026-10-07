"""Summarize CycloneDX SBOMs: unique packages (by purl) and licence classes."""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import registry  # noqa: E402  (harnesses.toml)
from collections import Counter, defaultdict

STRONG = re.compile(r"\b(A?GPL|LGPL|EUPL|OSL|SSPL|CC-BY-SA)", re.I)
WEAK = re.compile(r"\b(MPL|EPL|CDDL)", re.I)  # file-level copyleft
PERMISSIVE = re.compile(r"\b(MIT|BSD|Apache|ISC|PSF|Python-2\.0|Unlicense|0BSD|Zlib|CC0|BlueOak|HPND|WTFPL|X11)", re.I)
H = registry.names()


def lic(c):
    out = []
    for l in c.get("licenses", []) or []:
        if "license" in l:
            out.append(l["license"].get("id") or l["license"].get("name") or "")
        elif "expression" in l:
            out.append(l["expression"])
    return " OR ".join(x for x in out if x) or "UNKNOWN"


def cls(s):
    if s == "UNKNOWN":
        return "unknown"
    if STRONG.search(s):
        return "copyleft"
    if WEAK.search(s):
        return "weak copyleft"
    return "permissive" if PERMISSIVE.search(s) else "other"


d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "results")
detail = defaultdict(list)
print("| harness | unique packages | permissive | weak copyleft (MPL etc.) | strong copyleft | other | unknown |")
print("|---|---|---|---|---|---|---|")
for h in H:
    if not (d / f"sbom-{h}.cdx.json").exists():  # registered but not scanned yet
        continue
    comps = {}
    for c in json.loads((d / f"sbom-{h}.cdx.json").read_text()).get("components", []):
        if c.get("type") != "library" or not c.get("purl"):
            continue
        key = c["purl"].split("?")[0]
        if key not in comps or comps[key] == "UNKNOWN":
            comps[key] = lic(c)
    cnt = Counter(cls(v) for v in comps.values())
    for k, v in sorted(comps.items()):
        if cls(v) in ("copyleft", "weak copyleft", "other", "unknown"):
            detail[h].append(f"{k} — {v} ({cls(v)})")
    print(f"| {h} | {len(comps)} | {cnt['permissive']} | {cnt['weak copyleft']} | {cnt['copyleft']} | {cnt['other']} | {cnt['unknown']} |")
print()
for h, items in detail.items():
    print(f"<details><summary>{h}: {len(items)} non-permissive/unknown</summary>\n")
    for i in items:
        print(f"- `{i}`")
    print("\n</details>\n")
