FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./

RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-emit-project | pip install --no-cache-dir -r /dev/stdin

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
