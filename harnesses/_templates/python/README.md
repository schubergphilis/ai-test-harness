# __HARNESS__ harness

Scaffolded by `make new-harness`. It already implements the compat contract (`compat/CONTRACT.md`) with a
framework-free tool loop over the OpenAI SDK, so `make test-native HARNESS=__HARNESS__` passes before you change anything.

To turn it into a real harness:
1. Add the framework to `pyproject.toml` (`uv add <framework>`).
2. Replace `run()` in `agent.py` with the framework's agent. Keep the return shape
   `{"output", "tool_calls": [{"name", "args"}], "usage": {"input_tokens", "output_tokens"}}`.
   Register the canary tools `lookup` and `add` from `tools_canary.py`, and use `tools_canary.SYSTEM_PROMPT`.
3. Tracing: when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, emit OTel spans carrying `session.id` and `user.id`,
   and ideally `gen_ai.request.model` on the LLM span (the audit suite checks for it).
4. Fill `package`, `repo` and `licence` for this harness in `harnesses.toml`.
5. `make test-native HARNESS=__HARNESS__`, then `make qa`.

Don't edit `app.py` or `tools_canary.py`: they are shared verbatim by every Python harness, and CI checks they stay identical.
