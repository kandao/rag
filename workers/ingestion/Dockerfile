FROM python:3.11-slim

WORKDIR /app

COPY packages/rag-common /app/packages/rag-common
RUN pip install --no-cache-dir /app/packages/rag-common

COPY workers/ingestion /app
RUN pip install --no-cache-dir \
    "aiokafka==0.10.*" \
    "pydantic-settings==2.*" \
    "elasticsearch[async]==8.*" \
    "redis[asyncio]==5.*" \
    "httpx==0.27.*" \
    "tiktoken==0.7.*" \
    "pymupdf==1.24.*" \
    "pyyaml==6.*"

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
