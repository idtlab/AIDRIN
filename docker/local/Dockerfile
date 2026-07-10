# AIDRIN local dev image (build context = repo root); web/worker/beat run as separate compose services.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra llm --extra globus --extra telemetry
COPY . .
RUN uv sync --frozen --no-dev --extra llm --extra globus --extra telemetry
RUN uv pip install gunicorn==23.0.0

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app
COPY --from=builder /app /app

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/inspector', timeout=4).status==200 else 1)"
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "web:create_app()"]
