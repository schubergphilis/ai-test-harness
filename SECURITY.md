# Security policy

## Scope and threat model

This repository is a **test bed** for comparing agent harnesses, runtimes and models. It is not a product and
is not meant to be exposed to untrusted networks.

- **No authentication on agent endpoints.** Harness containers and native processes serve `POST /invocations`
  without auth. Compose publishes ports on `127.0.0.1` only. Run natively, Python harnesses bind `127.0.0.1`, but
  Node harnesses bind `0.0.0.0` (the container contract), so on an untrusted network use a host firewall. Don't
  expose any of them publicly.
- **Local-only secrets in compose.** The Langfuse stack in `runtimes/docker-local/docker-compose.yml` uses fixed
  development secrets (database passwords, `ENCRYPTION_KEY` of zeros, `NEXTAUTH_SECRET`). They are for a local
  lab only and must be replaced for any shared deployment.
- **Credentials live in `.env` only.** `.env` is gitignored. `.env.example` contains placeholders. Model upstream
  URLs, keys and model names are read from environment variables (`models.toml` names the variables, never the
  values). `run.json` records alias → upstream model name, never URLs or keys. `scripts/publish_results.py` scrubs
  paths and URL- or key-looking strings and runs gitleaks before anything is published.
- **Red-team payloads are not stored in the repo.** garak and PyRIT transcripts (attack prompts and model
  replies) stay in `quality/safety/results/`, which is gitignored. Probes that write malware-like test payloads to
  disk (garak `malwaregen`, `av_spam_scanning`, exploitation) are deliberately not used, and the EU AI Act
  benchmark suite that bundles offensive-security datasets was dropped because endpoint protection flagged it.
- **Supply chain.** Lockfiles are committed. Container base images and CI actions are pinned (by tag or digest,
  and by commit SHA for actions). Dependabot proposes weekly updates. CI runs gitleaks and OSV-Scanner. Accepted
  findings are listed with a reason in `qa/known_findings.json`.
- **OpenShell policy.** `runtimes/openshell/policy.yaml` is a default-deny egress policy written from the
  v0.1.x documentation. It is not verified yet.

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting** (*Security* tab → *Report a vulnerability*) on this
repository. Don't open a public issue for security problems. Include what you found, how to reproduce it, and the
impact you expect. You can expect an acknowledgement within a week.

Findings in third-party frameworks or tools (Strands, OpenAI Agents SDK, LangGraph, Pydantic AI, pi, LiteLLM,
garak, Inspect, …) should go to those projects. A note here is still welcome if this repo's configuration makes
the issue worse.
