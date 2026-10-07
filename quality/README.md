# Quality tracks

These tracks sit on top of the conformance suite and all run natively, without Docker. Each one uses an established, reputable project.

| track | dir | project(s) | targets |
|---|---|---|---|
| Repeatability | `inspect/` | Inspect AI (UK AISI) | the **agent** (`/invocations`) via a custom Inspect model provider |
| Safety | `safety/` | garak (NVIDIA), PyRIT (Microsoft) | the **agent** (`/invocations`) |
| ~~EU AI Act~~ | — | COMPL-AI: **dropped 2026-10-07**. Its `inspect-evals` dependency (security benchmark payloads) was flagged by endpoint protection, and the clone was removed. The EU AI Act mapping is now done in the summaries of the other tracks. | — |
| Audit + supply chain | `audit/` | OpenTelemetry Collector (CNCF), Syft, OSV-Scanner, OpenSSF Scorecard, `sovereignty-assessment` skill | traces, dependencies, egress |

## Conventions
- `quality/<track>/README.md`: what ran, the caps used, how to rerun, and what is unverified.
- `quality/<track>/results/`: the tool's native output (Inspect logs, garak reports, SBOMs…).
- `quality/<track>/summary.md`: one table that `docs/matrix.md` can lift.
- Cost caps: run `sovereign` first and `anthropic` only on a small subset. Concurrency against the sovereign server is ≤ 2.

## Disclaimer
These results **map to** EU AI Act articles (e.g. Art. 12 record-keeping, Art. 13/50 transparency, Art. 15 accuracy/robustness/cybersecurity). They do not show **compliance**. The harnesses are components, not high-risk AI systems; the test bed gathers evidence that supports deployer obligations. This is not legal advice.
