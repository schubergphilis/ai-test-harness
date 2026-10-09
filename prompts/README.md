# Prompts

Every prompt the test bed sends lives here as Markdown, not in code. Edit a file, rerun, and compare runs
(`make qa-compare`): a prompt change shows up in the diff like any other change.

| folder | used by | read as |
|---|---|---|
| `canary.md` | conformance tests, audit suite, Inspect `canary` task | user prompt |
| `content-filter.md` | conformance test `test_upstream_content_filter` (mock only) | user prompt; must contain `FILTER-TEST` (the mock answers empty with `finish_reason=content_filter`) |
| `system/` | every harness (`PROMPT_DIR`, container: `/app/prompts`) | system prompt: `canary.md` for the canary; for a scenario, the files listed in its `system_prompt` in `scenarios.json`, joined by a blank line (default `scenario-default.md`; the bold SnitchBench variants add `snitchbench-bold-suffix.md`) |
| `scenarios/<name>.md` | `qa/scenarios.py` | user prompt per scenario (or the files listed in its `prompt`, joined by a blank line); tools and the system-prompt list stay in `compat/fixtures/scenarios/scenarios.json` |
| `scenarios/snitchbench/` | SnitchBench scenarios | the four documents (MIT, see `LICENSE`), sent verbatim (trailing newline kept) as one message |
| `inspect/<task>/<id>.md` | Inspect `variants` / `injection` tasks | one sample per file; front matter `target`, `expected_tools` |
| `perf/` | `qa/perf.py` | latency prompt; `runaway.md` must contain `RUNAWAY-TEST` (the mock's never-ending-loop trigger), `runaway-slow.md` also `RUNAWAY-SLOW` (0.5 s per model call) |
| `safety/` | PyRIT scenarios | attack objectives |

Front matter (optional) is a `---` block of `key: value` lines; the rest of the file is the prompt, with the
trailing newline removed.

Rules: prompts stay fictional (no real people, companies or data), the canary answers must remain computable
from `compat/fixtures/canary.json`, and changing a prompt changes results, so note it in the commit message.
