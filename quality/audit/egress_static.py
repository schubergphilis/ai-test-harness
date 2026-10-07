"""Static scan of installed harness dependencies for telemetry / phone-home endpoints.

A hit means the code *contains* the endpoint, not that it is called. Each hit needs a judgement
(default-on? opt-in? disabled by the harness?), recorded in summary.md.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import registry  # noqa: E402  (harnesses.toml)
from collections import defaultdict

PATTERNS = {
    "openai-traces": r"api\.openai\.com/v1/traces",
    "langsmith": r"api\.smith\.langchain\.com|smith\.langchain\.com",
    "logfire": r"logfire(-us|-eu)?\.pydantic\.dev|logfire-api\.pydantic\.dev",
    "posthog": r"(app|us|eu)\.posthog\.com|i\.posthog\.com",
    "sentry": r"ingest\.sentry\.io|\.ingest\.(us|de)\.sentry\.io",
    "segment": r"api\.segment\.io",
    "scarf": r"static\.scarf\.sh|scarf\.sh/a\.png",
}
# installed dependency tree per registered harness (harnesses.toml)
ROOTS = {h["name"]: f"harnesses/{h['name']}/" + ("node_modules" if h["language"] == "node" else ".venv/lib")
         for h in registry.harnesses()}
EXT = {".py", ".js", ".mjs", ".cjs", ".ts"}
SKIP = re.compile(r"/(tests?|__tests__|test_\w+\.py|examples?)/|\.d\.ts$|/(typescript|tsx|esbuild|@types)/")

repo = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
for h, root in ROOTS.items():
    hits = defaultdict(list)
    for f in (repo / root).rglob("*"):
        if f.suffix not in EXT or SKIP.search(str(f)) or not f.is_file():
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for name, pat in PATTERNS.items():
            if re.search(pat, text):
                for i, line in enumerate(text.splitlines(), 1):
                    m = re.search(pat, line)
                    if m and len(hits[name]) < 4:
                        rel = str(f.relative_to(repo / root)).replace("python3.13/site-packages/", "").replace("python3.14/site-packages/", "")
                        hits[name].append(f"{rel}:{i} `{m.group(0)}`")
    print(f"### {h}")
    if not hits:
        print("- no known telemetry endpoints found")
    for name, ev in hits.items():
        print(f"- **{name}**: " + "; ".join(ev))
    print()
