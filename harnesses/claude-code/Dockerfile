# build context: repo root
# Plain image: the SDK wheel bundles the Claude Code CLI (a native binary), so no Node is needed.
# The hardened variant (claude-docker base image + guardrail flags) is a runtime: runtimes/claude-docker.
FROM python:3.14.7-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
WORKDIR /app
COPY harnesses/claude-code/pyproject.toml harnesses/claude-code/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY harnesses/claude-code/*.py ./
COPY compat/fixtures/canary.json /app/canary.json
COPY compat/fixtures/scenarios /app/scenarios
COPY prompts /app/prompts
RUN useradd -r -m -u 10001 agent && chown agent /app
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
