# AIDRIN image for NERSC Spin: web + worker + beat under supervisord; Redis is separate.
# Build from repo root: docker build -f docker/NERSC/Dockerfile -t aidrin:latest .
# Runs Celery beat, so deploy with exactly ONE replica.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Override to change extras (e.g. add --extra telemetry).
ARG AIDRIN_EXTRAS="--extra llm --extra globus"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev $AIDRIN_EXTRAS
COPY . .
RUN uv sync --frozen --no-dev $AIDRIN_EXTRAS
RUN uv pip install gunicorn==23.0.0 supervisor==4.2.5

FROM python:3.12-slim-bookworm

# libgomp1: OpenMP runtime for scikit-learn/scipy/shap.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    GUNICORN_WORKERS=2 \
    GUNICORN_TIMEOUT=120 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib \
    FLASK_CELERY__broker_url=redis://redis:6379/0 \
    FLASK_CELERY__result_backend=redis://redis:6379/0

WORKDIR /app
COPY --from=builder /app /app

# Group-writable (GID 0) so Spin's arbitrary non-root UID can write.
RUN chgrp -R 0 /app && chmod -R g=u /app

EXPOSE 5000
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/inspector', timeout=4).status==200 else 1)"

CMD ["supervisord", "-c", "/app/docker/NERSC/supervisord.conf"]
