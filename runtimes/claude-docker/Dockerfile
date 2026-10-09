# build context: repo root
# claude-docker runtime: the claude-code harness on the hardened claude-docker image
# (github.com/schubergphilis/claude-docker): pinned + scanned base, its pinned Claude Code CLI, and its entrypoint
# that drops root to an unprivileged user (HOST_UID) before exec'ing our server. Run it with the claude-docker
# guardrail flags: run.sh, docker-compose.yml here, or the k8s overlay runtimes/k8s/overlays/claude-docker.
FROM ghcr.io/schubergphilis/claude-docker:v0.3.3@sha256:03f37a52fe39de0adf82ada52d643b7d8d2864fdcd6d1c7caf630d39cdce8222

# Python lives outside /root (claude-docker keeps /root for its masked, per-user state)
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy
WORKDIR /app
COPY harnesses/claude-code/pyproject.toml harnesses/claude-code/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && mkdir -p /opt/uv-python && chmod -R a+rX /app /opt/uv-python
COPY harnesses/claude-code/*.py ./
COPY compat/fixtures/canary.json /app/canary.json
COPY compat/fixtures/scenarios /app/scenarios
COPY prompts /app/prompts

# use claude-docker's pinned CLI, not the copy bundled in the SDK wheel; drop root via the base entrypoint
ENV CLAUDE_CLI_PATH=claude HOST=0.0.0.0 HOST_UID=10001 HOST_GID=10001 PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/app/.venv/bin/uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
