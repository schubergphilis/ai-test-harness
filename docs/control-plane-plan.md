# Control-plane track (plan)

Goal: rerun the same agents and scenarios **with and without an AI control plane** (A/B), and measure what the
control plane enforces regardless of agent behaviour, and what it costs (latency, tokens, false blocks).
Research date: 2026-10-07 (repo metadata via `gh api`; unverified items marked).

| area | primary | alternative | notes |
|---|---|---|---|
| MCP tool gateway + tool authorization | [agentgateway](https://github.com/agentgateway/agentgateway) (Apache-2.0, Linux Foundation, v1.6.0, native darwin-arm64 binary) | [IBM ContextForge](https://github.com/IBM/mcp-context-forge) (Apache-2.0, `uvx`) | CEL `mcpAuthorization` rules per tool and per agent (JWT `sub`), filtered `tools/list`, OTel, built-in fault injection. Gateway passes MCP elicitation through but does not create it. |
| Guardrails at the proxy | LiteLLM built-in OSS guardrails (`litellm_content_filter`, `tool_permission`, `block_code_execution`) + [Presidio](https://github.com/data-privacy-stack/presidio) (MIT) for PII | [NeMo Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) (Apache-2.0) via a custom guardrail | LLM Guard is **archived**, do not adopt. Exclude SaaS integrations (lakera, aporia, pangea, …). Verify on LiteLLM 1.103.1 (research checked 1.97). |
| Policy engine | none needed for the A/B (agentgateway CEL) | Cedar (Apache-2.0) via AuthZEN, or OPA (CNCF) | AuthZEN adapters unverified. |
| Human approval | native in every harness: OpenAI Agents `needs_approval`, LangGraph `interrupt()`, Pydantic AI `requires_approval`, Strands interrupts, Claude Agent SDK `can_use_tool`, pi `beforeToolCall` (block only) | — | One shared `approval_policy(tool, args)` per harness with an auto-approve/deny oracle so QA stays unattended; measure whether the agent waits, asks, or works around a denial. |
| Chaos / fault injection | mock LLM returns 429/500/timeout/`content_filter` on demand | agentgateway `directResponse` + `delay` in front of LiteLLM | LiteLLM proxy `mock_testing_*` flags were removed (v1.85). toxiproxy is TCP-level only. |
| Tamper-evident audit | local hash chain (`prev_sha256` per record) + offline `cosign sign-blob --tlog-upload=false` | self-hosted Rekor (needs Trillian + MySQL) | The public Rekor instance would break sovereignty. |

## Integration plan
1. **Shared MCP tool server**: move the simulated scenario tools into one Python MCP server (same fixture, still no real
   effects). Every harness has an MCP client: Strands `MCPClient`, OpenAI Agents `MCPServerStreamableHttp`, LangGraph
   `langchain` MCP namespace (langchain-mcp-adapters is archived), Pydantic AI `MCPServerStreamableHTTP`, Claude Agent
   SDK `mcp_servers`, pi `@earendil-works/pi-mcp` (needs a pi package bump).
   Arm A: harness → tool server directly. Arm B: harness → agentgateway (JWT per harness, CEL rules) → tool server.
   Measure: exfiltration / persistence / honeypot rates per arm; gateway denials; added latency.
2. **Approval gates**: high-risk tools (`send_email`, `run_command`, writes) require approval; oracle auto-denies in
   QA. Measure: does the agent stop, ask the user, or try another route?
3. **Guardrails A/B**: same scenarios with LiteLLM OSS guardrails + Presidio on vs off. Measure blocked attacks, false
   blocks on benign tasks, latency and token overhead. Also require harnesses to surface `content_filter` instead of
   an empty 200 (all six currently hide it).
4. **Chaos**: mock-injected 429/500/timeouts/`content_filter` per scenario; checks: retries with backoff, fallback,
   error surfaced to the caller, no runaway.
5. **Hash-chained audit**: `run.json` and transcripts chained and signed offline; `qa/verify_audit.py` checks the chain.

Unverified: LiteLLM 1.103.1 guardrail behaviour, Pydantic AI `ApprovalRequiredToolset` for MCP, MCP elicitation
support per client, AuthZEN adapters, CPU latency of guard models.
