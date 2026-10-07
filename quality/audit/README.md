# Audit + supply chain track

Covers audit trail completeness (OTel), SBOM/licences/vulnerabilities, upstream project health, egress (calling home) and the 6-theme sovereignty assessment. Results: [summary.md](summary.md).

## Tools (all native, no Docker)
| tool | version | source |
|---|---|---|
| OpenTelemetry Collector contrib | 0.162.0 | GitHub release `otelcol-contrib_0.162.0_darwin_arm64.tar.gz`, sha256 verified → `bin/` (gitignored) |
| Syft | brew | Anchore |
| OSV-Scanner | brew | Google |
| OpenSSF Scorecard | 5.5.0 (brew) | OpenSSF; uses `GITHUB_AUTH_TOKEN=$(gh auth token)` |
| sovereignty-assessment | skill | in-house 6-theme rubric |

## Rerun
Requires shared litellm on :4000 (and mock-llm on :14000 for `mock`); see the root README.
```bash
cd quality/audit
TRACE_FILE=$PWD/results/traces-mock.jsonl bin/otelcol-contrib --config otelcol.yaml &
./start_harnesses.sh mock /tmp                   # every harness on its `audit` port (harnesses.toml), OTLP → :4318
./egress_sample.sh > /tmp/egress-raw.txt &       # optional live egress sampling
uv run pytest --junitxml=results/trace-completeness-mock.xml
python3 attr_table.py > results/attr-table-mock.md
./stop_harnesses.sh /tmp; kill %1 %2               # stops only the PIDs start_harnesses.sh recorded

# supply chain
for h in strands openai-agents langgraph pydantic-ai pi; do syft scan dir:../../harnesses/$h -o cyclonedx-json=results/sbom-$h.cdx.json -q; done
python3 sbom_summary.py > results/licences.md
osv-scanner scan source -L ../../harnesses/strands/uv.lock --format json > results/osv-strands.json   # per harness; pi: package-lock.json
python3 egress_static.py ../.. > results/egress-static.md
GITHUB_AUTH_TOKEN=$(gh auth token) scorecard --repo=github.com/strands-agents/sdk-python --format=json > results/scorecard-strands-agents_sdk-python.json
```
For `sovereign`: set `TRACE_FILE=results/traces-sovereign.jsonl`, use `./start_harnesses.sh sovereign`, and run with the `.env` loaded.

## Caps / cost
The trace runs make one canary invocation per harness per model (about 1.6k input tokens each on `sovereign`). There were no `anthropic` runs in this track.
