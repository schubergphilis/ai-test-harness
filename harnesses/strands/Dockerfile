# build context: repo root
FROM python:3.13.16-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
WORKDIR /app
COPY harnesses/strands/pyproject.toml harnesses/strands/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY harnesses/strands/*.py ./
COPY compat/fixtures/canary.json /app/canary.json
RUN useradd -r -u 10001 agent && chown agent /app
USER agent
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
