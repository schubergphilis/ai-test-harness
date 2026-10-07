# build context: repo root
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY harnesses/__HARNESS__/pyproject.toml harnesses/__HARNESS__/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY harnesses/__HARNESS__/*.py ./
COPY compat/fixtures/canary.json /app/canary.json
RUN useradd -r -u 10001 agent && chown agent /app
USER agent
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
