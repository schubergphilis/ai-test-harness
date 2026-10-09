# Agent runtime × harness test bed

A test bed for comparing **agent harnesses** (the frameworks that run the tool-calling loop) on **agent runtimes** (where the agent container runs), with **sovereign** (open-weights, self-hosted) and **frontier** (commercial) models side by side.

Every harness implements the same small HTTP contract and the same canary task. The same tests then run against every harness × model, and every run produces a machine-readable `run.json` plus a one-page HTML report.

```
┌─ App layer ─────────── chat · cognitive backbone · team brain          (out of scope, phase 2)
├─ Compat layer ──────── compat/CONTRACT.md: one container, GET /ping + POST /invocations,
│                        OpenAI-compatible LLM via a model alias, OTLP traces       ← what this repo tests
└─ Infrastructure ───── LLM (sovereign endpoint / frontier proxy / OpenRouter / Bedrock)
                         agent runtime (native · Docker · k3d · OpenShell · AgentCore later)
                         audit/tracing (OpenTelemetry → Langfuse or a file)
```

The question it answers: *can we swap the harness, the runtime or the model without rewriting the agent, and what do we gain or lose on quality, safety, auditability and sovereignty when we do?*

![Report summary: failing, weak and known findings](docs/img/report-attention.png)

## What's in the box

| | |
|---|---|
| **Harnesses** (`harnesses.toml`) | [Strands Agents](https://github.com/strands-agents/sdk-python) · [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) · [LangGraph](https://github.com/langchain-ai/langgraph) · [Pydantic AI](https://github.com/pydantic/pydantic-ai) · [pi](https://github.com/badlogic/pi-mono) (TypeScript) · **Claude Code** via the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python); plus Python/Node templates for adding your own |
| **Models** (`models.toml`) | `mock` (deterministic, no tokens) · `sovereign` (open-weights on an OpenAI-compatible endpoint) · `anthropic` and `chatgpt` (frontier, via an OpenAI-compatible proxy) · `nemotron-free` (`nvidia/nemotron-3.5-lightning:free` on OpenRouter, short matrix only, `make qa-free`). Providers: `openai_compatible`, `openrouter`, `bedrock`, all through [LiteLLM](https://github.com/BerriAI/litellm) |
| **Runtimes** | generic, every harness: native processes (default, lowest memory) · Docker Compose · k3d (Kubernetes) · [NVIDIA OpenShell](https://docs.nvidia.com/openshell) sandbox. Harness-specific: [claude-docker](https://github.com/schubergphilis/claude-docker) for Claude Code (hardened image, dropped privileges, masked credentials) · **sandboxes** for the agent's commands (`box` for every harness, `strands-sandbox` via Strands' own `DockerSandbox`): they really run in a throwaway, network-less container |
| **Quality suites** | compat contract (pytest) · repeatability and prompt injection ([Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai), UK AISI) · red-team ([garak](https://github.com/NVIDIA/garak), NVIDIA; [PyRIT](https://github.com/Azure/PyRIT), Microsoft) · audit trail ([OpenTelemetry Collector](https://opentelemetry.io/docs/collector/), GenAI semantic conventions) · supply chain ([Syft](https://github.com/anchore/syft), [OSV-Scanner](https://github.com/google/osv-scanner), [OpenSSF Scorecard](https://github.com/ossf/scorecard)) |
| **Report** | `runs/<id>/run.json` (schema `agentrt.qa.run/v1`) + `report.html`: needs-attention list, harness × model matrix, EU AI Act evidence map, diff against the previous run |

## Quick start (native, no Docker)

Requirements: Python ≥ 3.11 with [uv](https://docs.astral.sh/uv/), Node 22, `make`. Optional for the supply/audit suites: `syft`, `osv-scanner`, and the OpenTelemetry Collector contrib binary in `quality/audit/bin/` (see [quality/audit/README.md](quality/audit/README.md)).

```bash
cp .env.example .env          # mock works with the defaults; fill in endpoints for real models
make native-up                # LiteLLM proxy :4000 + mock LLM :14000 as local processes
make test-native HARNESS=strands            # compat contract for one harness on the mock model
make qa                       # all configured models × all harnesses × all suites
make qa-full                  # short behaviour grid, box and garak, side by side (QA_ARGS=--quick: 1 epoch; --scenarios all for the old grid)
open runs/index.html          # history of runs; each links to its report.html and issues.html
make qa-compare               # previous vs latest run; exits 1 on a regression (CI gate)
make native-down
```

`make qa` only includes models whose `.env` variables are set, so a fresh clone runs on `mock` alone. That costs no tokens and needs no network access to a model.

Speed: `qa/run.py` runs each model in its own process, side by side. Each process gets its own port range (`AGENTRT_PORT_SHIFT` 0/20/40/60) and its own OTel collector port. Scenario concurrency per model comes from `concurrency` in `models.toml`, or from `--scenario-concurrency`. Box runs default to `--box-concurrency 2`, and the same harness never runs two box tasks at once. Conformance/audit and Inspect results are saved per model in `runs/<id>/<model>/checkpoints/`, so `--resume <id>` after a crash only redoes what is missing. `--redo inspect` forces a suite to run again, and `--serial` restores the old one-model-at-a-time loop. `quality/safety/sweep.sh` runs aliases side by side in the same way, with `SWEEP_JOBS` targets per alias (default 3). `qa/full.sh` runs the garak sweep at the same time as QA, through a second litellm on :4001 (`scripts/native.sh up-safety`), so garak tokens never count in the QA totals.

## The compat contract

[compat/CONTRACT.md](compat/CONTRACT.md) in short:

- One container per harness, `0.0.0.0:8080`, linux/arm64 or amd64, non-root.
- `GET /ping` returns `{"status": "Healthy"}`. `POST /invocations` takes `{"prompt", "session_id"}` and returns `{"output", "tool_calls", "usage", "harness", "model", "session_id", "user"}`.
- The LLM is reached only through `OPENAI_BASE_URL` with `MODEL=<alias>`, so harness code never names a provider.
- Tracing goes through the standard `OTEL_EXPORTER_OTLP_*` variables, with `session.id` and `user.id` on spans.
- The caller identity arrives in the `X-Agent-User` header.

The HTTP shape follows the AWS Bedrock AgentCore runtime contract, so AgentCore can be added as a runtime without an adapter.

The canary task is two tools (`lookup`, `add`) over fictional data, so models can't answer from memory. The Inspect suite adds reworded variants and an **indirect prompt injection**: one lookup result contains instructions the agent must not follow.

## Runtimes

| runtime | how | status |
|---|---|---|
| native | `make native-up`, `make test-native`, `make qa` | used for all results so far |
| Docker Compose | `make up HARNESS=strands [MODEL=…] [TRACING=1]`, then `make test HARNESS=strands` | compose files and Dockerfiles written; images are built in CI but have not been run end to end locally |
| k3d | `make k3d-up`, `make k3d-deploy HARNESS=x`, `make k3d-forward HARNESS=x`, `make test RUNTIME=k3d HARNESS=x` | manifests written (kustomize); not yet run. Uses its own cluster and context and never touches other kube contexts |
| claude-docker (claude-code only) | `make up-claude-docker`, [runtimes/claude-docker/README.md](runtimes/claude-docker/README.md): the `claude-code` harness on the claude-docker image with its guardrail flags (compose service and k8s overlay `claude-docker`) | image built in CI; not yet run locally |
| box sandboxes (harness × sandbox × model) | `make qa-box`, [runtimes/box/README.md](runtimes/box/README.md): `run_command`/`read_file`/`list_dir` really execute in a throwaway container per invocation (no network, read-only, root-only honeypots); `box` for every harness, `strands-sandbox` for strands, `claude-docker` runs the claude-code container itself (agentrt/claude-code:claude-docker, its guardrail flags) | verified on real Docker (mock: 148/148 checks, no leftover containers) |
| OpenShell | [runtimes/openshell/README.md](runtimes/openshell/README.md) | **unverified**: run script and default-deny egress policy written from the v0.1.x docs |
| AWS AgentCore | — | deferred; the contract is compatible |

`TRACING=1` adds a local [Langfuse](https://langfuse.com) stack (MIT core). It needs several GB of RAM.

## Results

What a run checks, per harness × model:

| dimension | evidence | EU AI Act article it maps to |
|---|---|---|
| Contract | compat test suite | — |
| Audit trail | OTel spans with session, user, tool calls, LLM call | Art. 12 record-keeping |
| Repeatable | every epoch correct (canary and variants) | Art. 15 accuracy |
| Injection | resists instructions hidden in tool output | Art. 15 robustness |
| Discloses | tells the user about the injected instruction | Art. 13 / 50 transparency |
| Red-team | garak attack success, harness vs bare model | Art. 15 robustness |
| Supply chain | known vulnerabilities, licences, upstream repo health | Art. 15 cybersecurity |

The article mapping shows where a test produces *evidence relevant to* an obligation. It is **not a compliance statement and not legal advice**. Harnesses are components, not AI systems.

### Example report

A full run (6 harnesses × 4 models, 8 suites, 2,931 checks), published in
[`published-results/20261009T161823Z_8ed7ced/`](published-results/20261009T161823Z_8ed7ced/):

- [**issues.md**](published-results/20261009T161823Z_8ed7ced/issues.md): what the tests found, in plain English, with the harness × model grid and transcript evidence per issue
- [**report.md**](published-results/20261009T161823Z_8ed7ced/report.md): the full report (every check, metric and suite)
- the same two pages as HTML: [`issues.html`](published-results/20261009T161823Z_8ed7ced/issues.html), [`report.html`](published-results/20261009T161823Z_8ed7ced/report.html) (download and open them, or view via htmlpreview: [issues](https://htmlpreview.github.io/?https://github.com/schubergphilis/ai-test-harness/blob/main/published-results/20261009T161823Z_8ed7ced/issues.html), [report](https://htmlpreview.github.io/?https://github.com/schubergphilis/ai-test-harness/blob/main/published-results/20261009T161823Z_8ed7ced/report.html))
- the machine-readable result: [`run.json`](published-results/20261009T161823Z_8ed7ced/run.json)

![At a glance: harness × model matrix](docs/img/report-glance.png)

<details><summary>More screenshots: summary tiles, EU AI Act evidence map, full page</summary>

![Summary tiles](docs/img/report-tiles.png)
![EU AI Act evidence map and changes since the previous run](docs/img/report-ai-act.png)
![Full report](docs/img/report.png)

</details>

A sanitized snapshot of a full run is published in `published-results/` (see `scripts/publish_results.py`). [docs/findings.md](docs/findings.md) summarizes what it shows; [docs/issues-explained.md](docs/issues-explained.md) explains each issue in plain English (what happened, what it could lead to, how sure, what to do). Every run also gets `runs/<id>/issues.html` (`qa/issues.py`): the same issues with that run's harness × model grid and evidence from its transcripts (the task, the commands the agent ran, its answer, what the sandbox saw). The published copy is scrubbed (paths, IPs, URLs, keys) and leaves out the garak hit transcripts (red-team prompts and the model's replies); `report.md`/`issues.md` are made from the HTML with pandoc. Generated output (`runs/`, `quality/*/results/`) is not committed: it can hold local paths, traces and red-team transcripts.

## Extending

- **Add a harness:** `make new-harness NAME=foo HARNESS_LANG=python|node` scaffolds a working framework-free harness from `harnesses/_templates/` and registers it. Swap in your framework, then run `make test-native HARNESS=foo`.
- **Add a model or provider:** add an entry to `models.toml` (OpenAI-compatible, OpenRouter or Bedrock), set its variables in `.env`, then run `make gen && make native-down && make native-up` (litellm only reads its config at start).
- **Add a quality suite:** write a collector that emits `checks`/`metrics` records for `qa/run.py`.

Details and checklists are in [CONTRIBUTING.md](CONTRIBUTING.md). Architecture, ports and the `run.json` schema are in [docs/architecture.md](docs/architecture.md).

## Status and limitations

- This is a **test bed, not a product**. The agent endpoints have no authentication and the local Langfuse uses fixed dev secrets; see [SECURITY.md](SECURITY.md).
- Results come from small samples. Inspect uses 3–10 epochs per sample, garak 10 prompts per probe with keyword/regex detectors, and the sovereignty assessment has a single rater. Treat them as indicative, and read the transcripts before quoting a number.
- All results so far come from native processes. The Docker, k3d and OpenShell paths are written but not yet exercised end to end.
- The mock LLM checks the plumbing only; it says nothing about model quality.

## License

[Apache-2.0](LICENSE). The third-party frameworks, tools and models used here keep their own licences.
