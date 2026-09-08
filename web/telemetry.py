"""Flask-specific OpenTelemetry wiring for the AIDRIN web app.

The tracer itself lives in :mod:`aidrin.telemetry` so the CLI and the MCP server
can use it without importing Flask.  This module adds the one piece that is
genuinely Flask's — auto-instrumentation of the app — and re-exports the shared
API so existing imports keep working.

There is exactly one ``_tracer`` in the process, and it lives in
:mod:`aidrin.telemetry`.  Do not add another here.
"""

import logging
import os

from aidrin.telemetry import (  # noqa: F401  (re-exported for existing callers)
    _NoOpSpan,
    _NoOpTracer,
    get_tracer,
    trace_metric,
)
from aidrin.telemetry import init as _init_tracing

logger = logging.getLogger(__name__)

__all__ = [
    "_NoOpSpan",
    "_NoOpTracer",
    "get_tracer",
    "trace_metric",
    "init_telemetry",
]


def init_telemetry(app):
    """Initialise OpenTelemetry tracing for *app*.

    Call this once during ``create_app()``.  If the OTel SDK is not installed
    the function returns immediately with no side-effects.
    """
    service_name = os.environ.get("OTEL_SERVICE_NAME", "aidrin")

    if not _init_tracing(service_name):
        return

    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
    except ImportError:
        logger.warning(
            "OpenTelemetry Flask instrumentation not installed — "
            "request spans will not be recorded"
        )
        return

    FlaskInstrumentor().instrument_app(app)
    logger.info("OpenTelemetry: tracing enabled for service '%s'", service_name)
