# Audit + supply chain: summary (2026-10-07)

Everything below **maps to** EU AI Act articles (Art. 12 record-keeping, Art. 15 cybersecurity). None of it shows compliance. See `../README.md`.

## A. Audit trail: OTel trace completeness (`test_trace_completeness.py`)
These runs used the OTel Collector contrib 0.162.0 (native binary, checksum verified) as an OTLP→JSON-file sink. There was one canary invocation per harness, with a unique `session.id`.

| check | strands | openai-agents | langgraph | pydantic-ai | pi |
|---|---|---|---|---|---|
| trace found by `session.id` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `user.id` recorded | ✅ | ✅ | ✅ | ✅ | ✅ |
| tool spans: lookup×2 + add | ✅ | ✅ | ✅ | ✅ | ✅ |
| LLM call recorded (any convention) | ✅ | ✅ | ✅ | ✅ | ❌ xfail (known: no LLM spans) |
| LLM call as OTel GenAI semconv (`gen_ai.request.model`) | ✅ | ❌ (OpenInference `llm.*`) | ❌ (OpenInference `llm.*`) | ✅ | ❌ xfail |

The results were identical on `mock` and on `sovereign` (qwen3.8-flash-next-nvfp4): 26 passed, 2 failed, 2 xfailed each. JUnit files: `results/trace-completeness-{mock,sovereign}.xml`.

### Attributes emitted (sovereign run)

| attribute | strands | openai-agents | langgraph | pydantic-ai | pi |
|---|---|---|---|---|---|
| spans per invocation | 28 | 16 | 34 | 12 | 4 |
| `session.id` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `user.id` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `gen_ai.request.model` | ✅ | — | — | ✅ | — |
| `gen_ai.usage.input_tokens` | ✅ | — | — | ✅ | ✅ |
| `gen_ai.tool.name` | ✅ | — | — | ✅ | ✅ |
| `gen_ai.operation.name` | ✅ | — | — | ✅ | — |
| `llm.model_name (OpenInference)` | — | ✅ | ✅ | — | — |
| `tool.name (OpenInference)` | — | ✅ | ✅ | — | — |
| `prompt/completion content captured` | ✅ | ✅ | ✅ | ✅ | ✅ |

**Privacy note:** all five harnesses put prompt and completion **content** into spans, as attributes or span events. That makes the audit trail personal data under GDPR. Retention, access control and redaction must be designed in; for example, the collector's `redaction`/`transform` processors could handle redaction.

## B. Supply chain

### Dependencies and licences (Syft → CycloneDX, `results/sbom-<h>.cdx.json`)
| harness | unique packages | permissive | weak copyleft (MPL etc.) | strong copyleft | other | unknown |
|---|---|---|---|---|---|---|
| strands | 72 | 65 | 2 | 0 | 1 | 4 |
| openai-agents | 63 | 59 | 1 | 0 | 0 | 3 |
| langgraph | 70 | 66 | 2 | 0 | 0 | 2 |
| pydantic-ai | 48 | 45 | 1 | 0 | 0 | 2 |
| pi | 164 | 161 | 0 | 0 | 0 | 3 |

- **Weak copyleft:** MPL-2.0 (`certifi`, `orjson` dual, `tqdm`). It is file-level copyleft, so it creates no obligation for unmodified use.
- **No strong copyleft anywhere.**
- **Unknowns:** mostly our own projects, Windows- or emscripten-only lock entries (`pywin32`, `httpx2-jsfetch` via the official `mcp` SDK), or metadata gaps (`colorama` is BSD).
- **pi count:** 164 includes dev tooling (typescript, tsx), because Syft scanned `node_modules`.

### Vulnerabilities (OSV-Scanner on the lockfiles, `results/osv-<h>.json`)
| strands | openai-agents | langgraph | pydantic-ai | pi |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 1 (high, 8.2) |

The pi finding is `basic-ftp@5.3.1`, GHSA-c475-qrg2-pj4r (CPU DoS in its directory-listing parser). The path is pi-ai → proxy-agent → pac-proxy-agent → get-uri → basic-ftp, so it is only reachable if a PAC or FTP proxy URL is configured. Low practical risk; fix by bumping upstream or overriding the dependency.

### Upstream project health (OpenSSF Scorecard v5.5.0, `results/scorecard.md`)
| | strands-agents/sdk-python | openai/openai-agents-python | langchain-ai/langgraph | pydantic/pydantic-ai | badlogic/pi-mono |
|---|---|---|---|---|---|
| aggregate | 5.4 | **7.9** | 7.1 | 5.7 | **3.9** |

Notable checks:
- **Strands:** Dangerous-Workflow 0, Token-Permissions 0, Pinned-Dependencies 2.
- **pi-mono:** Code-Review 0 (single maintainer), SAST 0, Dependency-Update-Tool 0, no signed releases.
- **All five:** Vulnerabilities 0, meaning open advisories across the whole repo (dev and example dependencies included), not our locked install set; and Fuzzing 0 / CII-Best-Practices 0.

### Egress (calling home)
- **Static** (`results/egress-static.md`): installed dependencies were scanned for known telemetry hosts.
  - openai-agents ships `api.openai.com/v1/traces/ingest` as the **default-on** trace exporter. The harness replaces or disables it.
  - langgraph ships the LangSmith client. It is **opt-in** through env vars, which are not set.
  - strands, pydantic-ai and pi: none found.
- **Live** (`results/egress-live-sovereign.txt`): during the sovereign run, `lsof` sampled each harness process every 0.5 s. The only remote endpoints were 127.0.0.1:4000 (litellm) and 127.0.0.1:4318 (collector).
  - Limits: short-lived connections between samples and UDP/DNS are not seen.
  - **The strong test (Docker `internal: true` network, harness still passes) is deferred** until Docker is available.

## C. Sovereignty assessment (6-theme rubric, `results/sovereignty/assessment-<h>.md`)
| theme | strands | openai-agents | langgraph | pydantic-ai | pi |
|---|---|---|---|---|---|
| External service | PASS | PASS¹ | PASS | PASS | PASS |
| Vendor-specific | PASS | PASS | PASS | PASS | PASS |
| Configurable | PASS | PASS | PASS | PASS | PASS |
| Open standard | PARTIAL² | PARTIAL² | PARTIAL² | PARTIAL² | PARTIAL² |
| Runtime dependency | PARTIAL³ | PARTIAL⁴ | PARTIAL⁵ | PASS | PASS⁶ |
| Control plane | PASS | PASS | PASS | PASS | PASS |

1. A default-on OpenAI trace export exists, mitigated in harness code. A stricter rule would give PARTIAL.
2. The LLM wire protocol is the OpenAI Chat Completions API: public and implemented by many servers, but controlled by a single vendor. HTTP/JSON and OTLP are open.
3. boto3 and botocore are hard-required and imported at runtime (Bedrock default model) though never used.
4. OpenAI's SaaS trace exporter is loaded and default-on inside the required SDK.
5. `langsmith` is hard-required by langchain-core and imported at runtime.
6. Anthropic, AWS, Google and Mistral SDKs are installed but loaded lazily and never loaded here. A stricter rule would give PARTIAL.

Consistency rule used: a vendor-service SDK **loaded** at runtime is PARTIAL; one only **installed** is a PASS with a note. No decision rules were supplied beyond the Defined Terms.

## Unverified / not done
- Egress isolation under Docker `internal: true` (deferred, no Docker).
- Langfuse ingestion of these spans: the collector file sink was verified, Langfuse was not.
- Sovereignty assessments are a single rater (this agent), with no inter-rater check.
- Scorecard measures the upstream repositories, not the exact released packages we install.
