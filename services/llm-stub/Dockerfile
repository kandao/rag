FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir "fastapi==0.111.*" "uvicorn[standard]==0.29.*" "pydantic==2.*"
COPY services/llm-stub /app
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
