# __HARNESS__ harness (TypeScript)

Scaffolded by `make new-harness`. It already implements the compat contract (`compat/CONTRACT.md`) with a
framework-free tool loop over the `openai` npm SDK, so `make test-native HARNESS=__HARNESS__` passes before you change anything.

To turn it into a real harness:
1. `npm install <framework>`.
2. Replace `run()` in `src/agent.ts` with the framework's agent. Keep the return shape
   `{ output, tool_calls: [{ name, args }], usage: { input_tokens, output_tokens } }`, and use the canary tools
   and `SYSTEM_PROMPT` from `src/tools.ts`.
3. Tracing: `src/otel.ts` starts the OTel SDK when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Keep `session.id` and
   `user.id` on the spans, and ideally `gen_ai.request.model` on the LLM span.
4. Fill `package`, `repo` and `licence` for this harness in `harnesses.toml`.
5. `npm run build && make test-native HARNESS=__HARNESS__`, then `make qa`.
