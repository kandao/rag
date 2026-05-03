FROM python:3.11-slim

WORKDIR /app

COPY packages/rag-common /app/packages/rag-common
RUN pip install --no-cache-dir /app/packages/rag-common

COPY services/query-service /app
RUN pip install --no-cache-dir fastapi==0.111.* "uvicorn[standard]==0.29.*" pydantic-settings==2.* "httpx==0.27.*" "redis[asyncio]==5.*" "elasticsearch[async]==8.*"

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
