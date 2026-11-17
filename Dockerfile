FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QOBUZ_CONFIG_DIR=/config \
    QOBUZ_MUSIC_DIR=/music

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
COPY app ./app
# --retries/--timeout make the build resilient to flaky PyPI connections.
RUN pip install --no-cache-dir --retries 5 --timeout 120 .

VOLUME ["/config", "/music"]
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
