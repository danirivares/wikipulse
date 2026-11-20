# Single lean multi-service image shared by ingestor, analyzer, and api.
FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

# Install locked runtime dependencies first so code edits reuse the dependency layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY wikipulse ./wikipulse
RUN uv sync --frozen --no-dev --no-editable

RUN useradd --create-home --shell /bin/bash wikipulse
USER wikipulse

EXPOSE 8000

CMD ["uvicorn", "wikipulse.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
