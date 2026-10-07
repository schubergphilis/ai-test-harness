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
  "harness": "strands",
  "model": "sovereign",
  "session_id": "…",
  "user": "value of X-Agent-User"
}
```
`tool_calls` lists every tool executed during the run, in order. The usage values may be `null` if the harness doesn't expose them.

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

## Identity
The caller identity arrives in the `X-Agent-User` request header. On AgentCore this maps to `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Agent-User`, so accept both. Echo it in `user`. When tracing is on, set `session.id` and `user.id` on the spans (Langfuse maps these to sessionId and userId; the conformance suite finds the trace by `session.id`). Phase 1 does no authz.

## Canary tools (identical in every harness)
- `lookup(key: str) -> int`: case-insensitive lookup in `lookup_table` from the fixture. Unknown key → error string.
- `add(a: int, b: int) -> int`

System prompt: `You are a precise assistant. Always use the provided tools for lookups and arithmetic; never guess numbers.`
