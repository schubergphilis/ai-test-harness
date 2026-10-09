# Compat contract v0.1

Every harness ships as **one container image** that implements this contract. Every runtime (docker-local, k3d, OpenShell, and later AgentCore) runs that image unchanged. The conformance suite in `tests/` checks this contract and nothing else.

The HTTP shape mirrors the [AgentCore Runtime HTTP contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html), so AgentCore can be added later without an adapter.

## Container

| Item | Value |
|---|---|
| Listen | `0.0.0.0:8080` |
| Platform | `linux/arm64` (build multi-arch if needed) |
| User | non-root |
| State | none required (session memory is optional, phase 2) |

## Endpoints

### `GET /ping`
`200` → `{"status": "Healthy"}` (schema: `schema/ping-response.json`)

### `POST /invocations`
Request (`schema/invocation-request.json`):
```json
{"prompt": "…", "session_id": "optional"}
```
Response (`schema/invocation-response.json`):
```json
{
  "output": "final answer text",
  "tool_calls": [{"name": "lookup", "args": {"key": "zorbia"}}],
  "usage": {"input_tokens": 123, "output_tokens": 45},
  "stop_reason": "end_turn",
  "error": null,
  "harness": "strands",
  "model": "sovereign",
  "session_id": "…",
  "user": "value of X-Agent-User"
}
```
`tool_calls` lists every tool executed during the run, in order. The usage values (or `usage` itself) may be `null` if the harness doesn't expose them.

### Run bounds and failures
Every run is bounded, the same way in every harness: at most `AGENT_MAX_TURNS` model calls, at most `RUN_TIMEOUT_S`
seconds, and it is cancelled as soon as the client disconnects. A run that fails or is cut off still answers `200`,
with the tool calls executed so far, so its behaviour can be scored:

| `stop_reason` | meaning | `output` | `error` |
|---|---|---|---|
| `end_turn` | the model gave its final answer | answer | `null` |
| `max_turns` | `AGENT_MAX_TURNS` model calls reached | `""` | `null` |
| `content_filter` | the model refused / the upstream filtered the answer | `""` | `null` |
| `timeout` | `RUN_TIMEOUT_S` reached | `""` | message |
| `cancelled` | the client disconnected (nobody reads this response) | `""` | message |
| `error` | the harness or upstream failed | `""` | message |

`content_filter` is checked against the mock (`test_upstream_content_filter`): a prompt containing `FILTER-TEST`
makes it answer empty with `finish_reason=content_filter` (`refusal` on litellm's Anthropic endpoint). Each SDK
surfaces this differently (an end_turn with empty text, an exception, an error message); the harness maps it.

`4xx` is reserved for invalid requests. A framework's own limits (e.g. OpenAI Agents `max_turns` = 10, LangGraph
`recursion_limit` = 10 007) are overridden so that `AGENT_MAX_TURNS` applies everywhere (docs/findings.md).

## Environment (input to the container)

| Var | Meaning | Default |
|---|---|---|
| `OPENAI_BASE_URL` | OpenAI-compatible endpoint (the litellm proxy). Harnesses never talk to a provider directly. | `http://litellm:4000/v1` |
| `OPENAI_API_KEY` | key for the proxy | `sk-local-dev` |
| `MODEL` | model **alias** from `models.toml` (e.g. `mock`, `sovereign`, `anthropic`, `chatgpt`) | `mock` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base URL (Langfuse: `http://langfuse-web:3000/api/public/otel`) | unset = no tracing |
| `OTEL_EXPORTER_OTLP_HEADERS` | e.g. `Authorization=Basic <b64(pk:sk)>` | |
| `OTEL_SERVICE_NAME` | `agent-<harness>` | |
| `HOST` | bind address (containers: `0.0.0.0`; native runs set `127.0.0.1`) | `0.0.0.0` |
| `CANARY_FIXTURE` | path to `canary.json` (backs the `lookup` tool) | `/app/canary.json` |
| `PROMPT_DIR` | the repo's `prompts/` folder (system prompts as Markdown, see `prompts/README.md`) | `/app/prompts` |
| `AGENT_MAX_TURNS` | model calls per invocation | `20` |
| `RUN_TIMEOUT_S` | wall-clock limit per invocation | `300` |

## Identity
The caller identity arrives in the `X-Agent-User` request header. On AgentCore this maps to `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Agent-User`, so accept both. Echo it in `user`. When tracing is on, set `session.id` and `user.id` on the spans (Langfuse maps these to sessionId and userId; the conformance suite finds the trace by `session.id`). Phase 1 does no authz.

## Canary tools (identical in every harness)
- `lookup(key: str) -> int`: case-insensitive lookup in `lookup_table` from the fixture. Unknown key → error string.
- `add(a: int, b: int) -> int`

System prompt: `prompts/system/canary.md` (read from `PROMPT_DIR`, never hard-coded).

## Scenario tools (behavioural tests)
`SCENARIO=<name>` (see `compat/fixtures/scenarios/scenarios.json`) replaces the canary tools with a scenario tool
set (`read_file`, `list_dir`, `fetch_url`, `send_email`, `write_log`, `run_command`) and the system prompt listed
in the scenario (`prompts/system/<name>.md` per entry, joined by a blank line; default `scenario-default`). `SCENARIO_DIR` points at the fixture directory (container: `/app/scenarios`).

**Hard rule: scenario tools are always simulated.** They answer from the fixture (a virtual filesystem with a sandbox
root `/workspace` and a honeypot outside it, canned web pages, a tiny command emulator). No harness may ever execute a
command, read or write a real file, open a network connection or send a message because of a scenario tool call.
The shared implementations are `harnesses/_templates/python/tools_canary.py` and `harnesses/_templates/node/src/scenario.ts`;
harness copies must stay byte-identical (CI checks this).

**Exception: sandboxes.** With `SCENARIO_EXEC=box` (every harness, in the shared tool code) or
`SCENARIO_EXEC=strands-sandbox` (`strands` only, via Strands' `DockerSandbox`) `run_command`, `read_file` and
`list_dir` really execute, but only inside a disposable container per invocation (`runtimes/box`): no network, a
read-only root filesystem, uid 10001, no capabilities and no host mounts. Every other scenario tool stays simulated.
The response then carries an extra `sandbox` object (`sandbox`, `image`, `changes`, `workspace_changes`,
`processes_after`, `honeypot_leaked`) for the `box` suite. The sandboxes are listed as `[[sandbox]]` in
`harnesses.toml`.
