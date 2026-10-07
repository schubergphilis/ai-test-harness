"""Which audit-relevant attributes each harness emits (from results/spans-<h>.json)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import registry  # noqa: E402  (harnesses.toml)

ROWS = [
    ("session.id", lambda s: "session.id" in s["attrs"]),
    ("user.id", lambda s: "user.id" in s["attrs"]),
    ("gen_ai.request.model", lambda s: "gen_ai.request.model" in s["attrs"]),
    ("gen_ai.usage.input_tokens", lambda s: "gen_ai.usage.input_tokens" in s["attrs"]),
    ("gen_ai.tool.name", lambda s: "gen_ai.tool.name" in s["attrs"]),
    ("gen_ai.operation.name", lambda s: "gen_ai.operation.name" in s["attrs"]),
    ("llm.model_name (OpenInference)", lambda s: "llm.model_name" in s["attrs"]),
    ("tool.name (OpenInference)", lambda s: "tool.name" in s["attrs"]),
    ("prompt/completion content captured", lambda s: any(e.startswith("gen_ai.") for e in s.get("events", [])) or any(k.startswith(("gen_ai.input", "gen_ai.output", "gen_ai.prompt", "gen_ai.completion", "llm.input_messages", "llm.output_messages", "input.value", "output.value")) for k in s["attrs"])),
]
H = registry.names()
d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "results")
data = {h: json.loads((d / f"spans-{h}.json").read_text())["spans"] for h in H if (d / f"spans-{h}.json").exists()}
print("| attribute | " + " | ".join(data) + " |")
print("|---|" + "---|" * len(data))
print("| spans per invocation | " + " | ".join(str(len(v)) for v in data.values()) + " |")
for name, f in ROWS:
    print(f"| `{name}` | " + " | ".join("✅" if any(f(s) for s in v) else "—" for v in data.values()) + " |")
