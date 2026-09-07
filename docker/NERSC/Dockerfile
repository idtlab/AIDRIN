# AIDRIN image for NERSC Spin: web + worker + beat under supervisord; Redis is separate.
# Build from repo root: docker build -f docker/NERSC/Dockerfile -t aidrin:latest .
# Runs Celery beat, so deploy with exactly ONE replica.
FROM python:3.13.11-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /uvx /bin/

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
# supervisor 4.2.5 imports pkg_resources at startup; setuptools>=82 removed it,
# so pin setuptools below 82 for the runtime tooling.
RUN uv pip install gunicorn==23.0.0 supervisor==4.2.5 "setuptools<82"

FROM python:3.13.11-slim-bookworm

# libgomp1: OpenMP runtime for scikit-learn/scipy. The rest are
# WeasyPrint's native dependencies (Pango/HarfBuzz/gdk-pixbuf) plus a base
# font, needed for PDF export.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    GUNICORN_WORKERS=2 \
    GUNICORN_TIMEOUT=120 \
    HOME=/tmp \
    MPLCONFIGDIR=/tmp/matplotlib \
    PGEOCODE_DATA_DIR=/app/.cache/pgeocode \
    FLASK_CELERY__broker_url=redis://redis:6379/0 \
    FLASK_CELERY__result_backend=redis://redis:6379/0

WORKDIR /app
COPY --from=builder /app /app

# Pre-fetch pgeocode's GeoNames data into PGEOCODE_DATA_DIR (under /app) so the HIPAA
# postal-code check works for the arbitrary non-root UID on Spin: HOME=/tmp/.cache is
# root-owned and unwritable there, and Spin may block egress. Best-effort at build.
RUN mkdir -p /app/.cache/pgeocode \
    && python -c "import pgeocode; pgeocode.Nominatim('us')" \
    || echo "pgeocode prefetch skipped (offline build); will download at runtime"

# Group-writable (GID 0) so Spin's arbitrary non-root UID can write.
RUN chgrp -R 0 /app && chmod -R g=u /app

EXPOSE 5000
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/inspector', timeout=4).status==200 else 1)"

CMD ["supervisord", "-c", "/app/docker/NERSC/supervisord.conf"]
