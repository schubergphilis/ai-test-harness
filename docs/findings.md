# Findings

> Snapshot of run `20261007T152332Z_nocommit` (published in `published-results/20261007T152332Z_nocommit/`). Numbers are **indicative**: small
> samples, automated detectors, a single rater for the sovereignty assessment. Read the caveats at the end before
> quoting anything.

Models: `sovereign` = `qwen3.8-flash-next-nvfp4` (open-weights, sovereign OpenAI-compatible endpoint) · `anthropic` = `aws/claude-5-5-opus` ·
`chatgpt` = `azure/gpt-6-1-sol` (frontier proxy) · `mock` = deterministic plumbing check. Inspect: 3 epochs per sample.

## Harness comparison

Cells show `sovereign / anthropic / chatgpt` unless stated.

| | strands | openai-agents | langgraph | pydantic-ai | pi |
|---|---|---|---|---|---|
| Contract (sov / anth / chat) | 8/8 / 8/8 / 8/8 | 8/8 / 8/8 / 8/8 | 8/8 / 8/8 / 8/8 | 8/8 / 8/8 / 8/8 | 8/8 / 8/8 / 8/8 |
| Repeatable: canary+variants accuracy | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% |
| Injection resisted | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% | 100% / 100% / 100% |
| Discloses injection | 100% / 100% / 0% | 100% / 83% / 0% | 100% / 83% / 0% | 0% / 17% / 0% | 0% / 50% / 0% |
| Red-team probes within limit (sov) | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Audit trail (sov) | 6/6 | 5/6 (1 known) | 5/6 (1 known) | 6/6 | 4/6 (2 known) |
| Supply chain: deps / high vulns | 68 / 0 | 60 / 0 | 68 / 0 | 46 / 0 | 164 / 1 |
| Canary latency s (sov / anth / chat) | 2.4 / 5.5 / 4.7 | 2.1 / 4.9 / 4.9 | 2.0 / 5.1 / 5.3 | 2.1 / 5.0 / 5.1 | 2.2 / 5.4 / 4.5 |

## Sovereign vs frontier

| model | variants accuracy (mean over harnesses) | canary latency (mean) | input tokens per canary run | discloses injection (mean) |
|---|---|---|---|---|
| `sovereign` (qwen3.8-flash-next-nvfp4) | 100% | 2.1 s | 1614 | 60% |
| `anthropic` (aws/claude-5-5-opus) | 100% | 5.2 s | 2043 | 67% |
| `chatgpt` (azure/gpt-6-1-sol) | 100% | 4.9 s | 592 | 0% |

- **Accuracy is a tie on these tasks.** Every harness on every real model answered the canary and variants correctly in every epoch. The tasks are saturated: they show plumbing and consistency, not capability differences.
- **The sovereign model is the fastest** here (about 2 s against about 5 s for both frontier models) and uses fewer input tokens.
- **Transparency differs by model more than by harness.** On `chatgpt` no harness told the user about the injected instruction; on `sovereign` three of five did, every time.

## Safety

- **Indirect injection via tool output (the agent-specific case) was resisted by every harness on every model** (Inspect `injection`, and PyRIT scenario A).
- **garak, harness vs bare model:** harnesses mostly track the bare model within ±10 points, so none of them adds a guardrail by default. Two Strands results exceed the limit: direct prompt injection on `sovereign` (40 %, ceiling 20 %) and latent injection on `anthropic` (90 % vs 70 % bare model). With n = 10 per probe, treat these as leads to investigate, not verdicts.
- **System prompts are not secret:** a multi-turn extraction (PyRIT scenario B) recovered the system prompt in 2 of 6 harness × model combinations.
- **No turn or time budget:** one encoded prompt kept an agent busy for minutes. The contract could add `MAX_TURNS` / `INVOCATION_TIMEOUT_S`.
- `chatgpt` was not included in the garak sweep for this snapshot.

## Audit trail

- Every harness records `session.id`, `user.id` and each tool call as spans.
- Strands, Pydantic AI and the templates emit the LLM call with OpenTelemetry GenAI semantic conventions (`gen_ai.request.model`). OpenAI Agents SDK and LangGraph need OpenInference, which uses `llm.*` attributes instead. pi emits no LLM spans (hand-made invocation and tool spans only).
- All harnesses put prompt and completion text into spans by default, so a trace store is personal-data storage (GDPR): plan redaction and retention.

## Supply chain and sovereignty

- Installed dependencies range from 46 (Pydantic AI) to 164 (pi, including dev tooling); no strong-copyleft licences.
- OSV: no known vulnerabilities in the Python harnesses; one high-severity transitive finding in pi (accepted: only reachable via a PAC/FTP proxy configuration).
- Vendor telemetry: the OpenAI Agents SDK exports traces to OpenAI by default (disabled in the harness); LangGraph ships the LangSmith client (inactive unless configured). Live egress during the run went only to the local proxy and collector.
- Sovereignty assessment (6 themes): all harnesses pass external service, vendor-specific, configurable and control plane; all are partial on open standard because the LLM protocol is the OpenAI Chat Completions API. Details in `published-results/20261007T152332Z_nocommit/quality/audit/summary.md`.

## Limitations and caveats

- **garak:** 10 prompts per probe with keyword/regex detectors. Jailbreak "hits" include refusals that don't use
  the detector's keywords, so check hitlogs by hand before quoting a rate.
- **Inspect:** 3–10 epochs per sample on a single shared upstream. The injection and disclosure scorers are
  regex heuristics.
- **Latency:** single runs against shared upstreams, so only large gaps mean anything.
- **Sovereignty assessment:** one rater, against the 6-theme rubric (external service, vendor-specific,
  configurable, open standard, runtime dependency, control plane).
- **Runtime:** all runs were native processes. Docker, k3d and OpenShell are not exercised yet, and the live
  egress check was a short `lsof` sample, not network isolation.
- **EU AI Act:** the mapping shows evidence *relevant to* articles. It is not a compliance statement and not
  legal advice.
