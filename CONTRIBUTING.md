# Contributing

Thanks for helping. The project is small on purpose: one contract (`compat/CONTRACT.md`), two registries
(`harnesses.toml`, `models.toml`) and a QA runner (`qa/`). Most contributions are a new harness, a new model or
provider, or a new quality suite.

## Development setup

Requirements: Python ≥ 3.11 with [uv](https://docs.astral.sh/uv/), Node 22, `make`. Optional: `syft`,
`osv-scanner`, `shellcheck`, the OpenTelemetry Collector contrib binary (see `quality/audit/README.md`).

```bash
cp .env.example .env                 # mock needs nothing else
make native-up                       # LiteLLM :4000 + mock LLM :14000 (PIDs in .run/)
make test-native HARNESS=strands     # compat contract on the mock model
uv run --no-project --with pytest pytest qa/tests   # unit tests for qa/ and scripts/registry.py
pre-commit install                   # ruff, shellcheck, gitleaks, yaml/json/toml checks, registry gen --check
make native-down
```

CI (`.github/workflows/ci.yml`) runs lint, the unit tests, the QA suites on the mock model, gitleaks, OSV-Scanner
and the image builds. It needs no secrets.

## Ground rules

- **The registries are the source of truth.** Harnesses live in `harnesses.toml`, model aliases in `models.toml`.
  Never hardcode a harness list, port or model alias elsewhere. Read them through `scripts/registry.py` (Python:
  `import registry`; shell: `python3 scripts/registry.py names|port|get|models`).
- **Generated files are not edited by hand:** `runtimes/docker-local/litellm.yaml`,
  `runtimes/docker-local/docker-compose.harnesses.yml`, `runtimes/k8s/overlays/*` and `.github/dependabot.yml`.
  Run `make gen` after a registry change. `make gen-check` (and CI) fails if they are stale.
- **Python harnesses share `app.py` and `tools_canary.py` byte for byte** with `harnesses/_templates/python/`.
  CI checks for drift. Change the template and every copy together, or not at all.
- **Harness code never names a provider.** It reads `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `MODEL` (an alias).
- **No secrets in the repo.** `.env` is gitignored; `models.toml` only names environment variables.
- **No generated results in commits.** `runs/` and `quality/*/results/` are gitignored. Publish a run with
  `scripts/publish_results.py`, which scrubs it first.
- Kill only processes you started (track PIDs). Never `pkill -f` by name.

## Adding a harness

1. `make new-harness NAME=foo LANG=python` (or `LANG=node`). This copies `harnesses/_templates/<lang>/`, picks the
   next free index, appends an entry to `harnesses.toml`, locks dependencies and runs `make gen`. The result is a
   framework-free tool loop that already passes the contract.
2. Check it: `make test-native HARNESS=foo` should give 8 passed, 1 skipped (the Langfuse test).
3. Replace `agent.py` (or `src/agent.ts`) with your framework. Keep the `run(prompt, session_id, user)` return
   shape: `output`, `tool_calls[{name, args}]`, `usage{input_tokens, output_tokens}`. Keep `app.py` /
   `tools_canary.py` unchanged.
4. Tracing: when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, emit spans with `session.id` and `user.id`, one span per
   tool call, and an LLM span with `gen_ai.request.model` (OTel GenAI semantic conventions). Prefer the
   framework's native OTel support. Make sure it doesn't export to a vendor by default.
5. Fill in `package`, `repo` and `licence` in `harnesses.toml` (the `TODO` placeholders).
6. Run `make gen`, then `make test-native HARNESS=foo` and `make test-native HARNESS=foo MODEL=sovereign` (or any
   configured model). Then do a QA run: `python3 qa/run.py --harnesses foo --epochs 1`.
7. If the harness has a known, accepted gap (e.g. no LLM spans), add it to `qa/known_findings.json` with a reason
   and date instead of weakening a test.
8. Update the harness table in `README.md`.

## Adding a model or provider

1. Add a `[[model]]` entry to `models.toml`:
   - `alias` and `kind` (`sovereign` | `frontier`);
   - `provider`, one of:
     - `openai_compatible`: needs `base_url`, `api_key`, `model`
     - `openrouter`: needs `api_key`, `model`
     - `bedrock`: needs `model`, `region`, optionally `aws_profile`
   - the provider fields hold **names of environment variables**, never values;
   - `default_qa` / `red_team` flags.

   Commented examples sit at the end of the file.
2. Put the values in `.env` (and document the variable names in `.env.example`).
3. Run `make gen` and restart with `make native-down && make native-up`.
4. Check with `make test-native HARNESS=strands MODEL=<alias>`. `make qa` picks up the alias automatically once
   its variables are set.

## Adding a quality suite

A suite is a function in `qa/run.py` that runs a tool and returns `(checks, metrics)` in the
`agentrt.qa.run/v1` shape (see `docs/architecture.md`):

```python
checks  = [{"suite": "mysuite", "harness": "strands", "model": "sovereign", "check": "some_check",
            "status": "pass" | "fail" | "error" | "skip" | "xfail", "details": "short reason"}]
metrics = [{"suite": "mysuite", "harness": "strands", "model": "sovereign", "name": "some_metric",
            "value": 0.93, "unit": "ratio" | "s" | "tokens" | "count"}]
```

- Use `"-"` as `model` for model-independent checks.
- Put the tool and its scripts under `quality/<suite>/` with a README (what it measures, caps, what is
  unverified). Keep raw output in `quality/<suite>/results/` or the run directory.
- Prefer established, reputable tools over home-grown scoring.
- To surface the suite in the report, add a dimension to `DIMENSIONS` in `qa/report.py`, plus an EU AI Act mapping
  only where it is defensible ("maps to", never "complies").
- Add unit tests for any parsing or scoring logic in `qa/tests/`.

## Pull requests

- Keep PRs focused. Include the `make test-native` output, and for behaviour changes a `make qa-compare` against
  a baseline run.
- Lint must pass: `pre-commit run -a`.
- By contributing you agree that your contribution is licensed under Apache-2.0 (see `LICENSE`).
- Follow the [code of conduct](CODE_OF_CONDUCT.md).
