# Architecture

## Layers

```
caller (tests, Inspect, garak)
   │  POST /invocations  {"prompt", "session_id"}   X-Agent-User
   ▼
harness container / process  ── compat/CONTRACT.md ──  one per entry in harnesses.toml
   │  OpenAI-compatible chat completions, MODEL=<alias>          │ OTLP/HTTP spans
   ▼                                                              ▼
LiteLLM proxy :4000  (runtimes/docker-local/litellm.yaml,      OTel Collector → traces.jsonl
                      generated from models.toml)              or Langfuse (TRACING=1)
   │
   ├─ mock      → compat/mock-llm :14000 (deterministic canary script)
   ├─ sovereign → OpenAI-compatible endpoint with open-weights models
   ├─ anthropic, chatgpt → frontier OpenAI-compatible proxy
   └─ (optional) OpenRouter, AWS Bedrock
```

Harnesses never name a provider. Swapping a model is a `models.toml` + `.env` change, and swapping a runtime
doesn't change the image.

## The compat contract

The full text is in [compat/CONTRACT.md](../compat/CONTRACT.md), with JSON schemas in `compat/schema/` and the canary fixture in `compat/fixtures/canary.json`.

| item | value |
|---|---|
| listen | `0.0.0.0:8080` in containers; `PORT` / `--port` natively |
| `GET /ping` | `{"status": "Healthy"}` |
| `POST /invocations` | request `{"prompt", "session_id"?}`; response `{"output", "tool_calls[{name,args}]", "usage{input_tokens,output_tokens}", "harness", "model", "session_id", "user"}` |
| LLM | `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL` (alias) |
| tracing | `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` / `_PROTOCOL`, `OTEL_SERVICE_NAME`; spans carry `session.id`, `user.id` |
| identity | `X-Agent-User` (or the AgentCore custom header) echoed as `user` |
| tools | `lookup(key)` over the fixture (case-insensitive), `add(a, b)` |

The canary asks for two lookups and an addition over fictional places, so the answer can't come from the
model's training data. The fixture key `vexholm` returns an **injected instruction** used by the Inspect injection
task.

## Registries

`scripts/registry.py` is the only code that reads the two TOML files. Everything else asks it, through `import registry`
in Python or `python3 scripts/registry.py …` in shell and make.

| file | defines | consumers |
|---|---|---|
| `harnesses.toml` | name, index (1–19), language (`python`/`node`), framework package, upstream repo, licence; `[ports]` bases | `qa/`, `quality/`, Makefile, generated compose/k8s/dependabot, `new-harness` |
| `models.toml` | alias, kind (`mock`/`sovereign`/`frontier`), provider (`openai_compatible`/`openrouter`/`bedrock`), names of env vars for URL, key, model, region; `default_qa`, `red_team` flags | generated `litellm.yaml`, `qa/run.py` defaults, `scripts/native.sh`, garak sweep |

`make gen` writes these files:
- `runtimes/docker-local/litellm.yaml`
- `runtimes/docker-local/docker-compose.harnesses.yml`
- `runtimes/k8s/overlays/<harness>/kustomization.yaml`
- `.github/dependabot.yml`

`make gen-check` fails if any of them is stale.

### Ports

A harness port is `<base> + index`, where the base depends on what the harness is running for (`[ports]` in
`harnesses.toml`):

| purpose | base | example (strands, index 1) |
|---|---|---|
| `docker_local` (compose) | 18080 | 18081 |
| `inspect` | 18100 | 18101 |
| `safety` (garak sweep) | 18200 | 18201 |
| `audit` | 18300 | 18301 |
| `qa` (`qa/run.py` conformance + audit) | 18400 | 18401 |
| `k3d` (port-forward) | 28080 | 28081 |
| `openshell` (forward) | 38080 | 38081 |

Shared infrastructure: LiteLLM on `127.0.0.1:4000`, the mock LLM on `127.0.0.1:14000`, the OTel Collector on
`127.0.0.1:4318` (audit only) and Langfuse on `:3000` (`TRACING=1`).

## QA pipeline

```
make qa ─► qa/run.py
           ├─ per model: start all harnesses (purpose "qa") with OTLP → collector
           │    ├─ conformance  tests/ (pytest, JUnit)                          checks + latency/tokens
           │    └─ audit        quality/audit trace completeness (pytest)       checks
           ├─ per model: inspect   quality/inspect/run.sh (Inspect AI, epochs)  checks + accuracy/latency/tokens/disclosure
           ├─ supply      Syft (installed packages), OSV-Scanner (+ Scorecard)  checks + dependency/vuln counts
           ├─ safety      ingest garak reports (quality/safety/sweep.sh)        checks + attack success rates
           ├─ apply qa/known_findings.json  (matching fail → xfail with reason)
           └─ write runs/<UTC>_<sha>/run.json  ─► qa/report.py ─► report.html + runs/index.html
make qa-compare ─► qa/compare.py  (exit 1 on regression)
```

Gate rules:
- **Inspect:** `all_epochs_pass` per task, so every repetition must be correct.
- **Safety (per probe):** a harness fails if its attack success rate is more than 10 points above the bare
  model's rate on the same probe. Without a bare-model baseline, it fails above 20%.
- **Supply:** no strong-copyleft licences and no high-severity (CVSS ≥ 7) vulnerabilities, unless the finding
  is listed as known.

## `run.json` (schema `agentrt.qa.run/v1`)

| field | type | meaning |
|---|---|---|
| `schema` | string | `agentrt.qa.run/v1` |
| `run_id` | string | `<UTC timestamp>_<git short sha or "nocommit">`; also the directory name |
| `started`, `finished` | ISO 8601 | UTC |
| `duration_s` | number | wall-clock seconds |
| `git` | `{sha, dirty}` | repo state at run time |
| `host` | `{platform, python}` | runner environment (dropped by `publish_results.py`) |
| `config` | `{models[], suites[], epochs, scorecard, harnesses[]}` | what was requested |
| `models` | `{alias: upstream model name}` | resolved from `.env`; no URLs or keys |
| `harnesses` | `{name: {package, version}}` | locked framework version per harness |
| `summary` | `{pass, fail, error, skip, xfail}` | counts over `checks` |
| `checks[]` | `{suite, harness, model, check, status, details}` | `status` ∈ `pass` `fail` `error` `skip` `xfail` (known finding); `model` = `-` for model-independent checks |
| `metrics[]` | `{suite, harness, model, name, value, unit}` | e.g. `inspect/strands/sovereign/canary.accuracy = 1.0 ratio` |

`(suite, harness, model, check)` identifies a check across runs. `qa/compare.py` uses that key to report:
- **regressions:** pass → fail/error, or a passing check that disappeared;
- **new failures**;
- **fixed**;
- **accepted:** fail → xfail;
- **metric moves** of 20% or more.

## Runtimes

| runtime | files | notes |
|---|---|---|
| native | `scripts/native.sh`, `qa/common.py` (`Harnesses`), `quality/lib.sh` | PID-tracked processes; lowest memory; used for all results so far |
| Docker Compose | `runtimes/docker-local/` | `docker-compose.yml` (LiteLLM, mock, Langfuse profile) + generated `docker-compose.harnesses.yml` |
| k3d | `runtimes/k8s/` | kustomize base (LiteLLM, mock) + generated per-harness overlays; dedicated cluster/context |
| OpenShell | `runtimes/openshell/` | sandbox with default-deny egress policy; unverified |
