# build context: repo root
FROM python:3.13.16-slim
RUN pip install --no-cache-dir fastapi==0.142.2 uvicorn==0.54.0
WORKDIR /app
COPY compat/mock-llm/mock_llm.py .
USER 10001
EXPOSE 4000
CMD ["uvicorn", "mock_llm:app", "--host", "0.0.0.0", "--port", "4000"]
