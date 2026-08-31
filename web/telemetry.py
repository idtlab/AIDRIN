"""Optional OpenTelemetry instrumentation for AIDRIN.

If the ``opentelemetry`` packages are installed (``pip install aidrin[telemetry]``),
this module initialises tracing for the Flask app and exposes a tracer for manual
spans in route handlers.  When the packages are **not** installed everything
degrades to silent no-ops — zero overhead, zero behaviour change.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Sentinel: set to True once init_telemetry() succeeds
_otel_available = False
_tracer = None


class _NoOpSpan:
    """Minimal stand-in so ``with get_tracer().start_as_current_span(...)`` works."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_attribute(self, key, value):
        pass

    def set_status(self, *args, **kwargs):
        pass


class _NoOpTracer:
    """Returned by ``get_tracer()`` when OpenTelemetry is not installed."""

    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()


def init_telemetry(app):
    """Initialise OpenTelemetry tracing for *app*.

    Call this once during ``create_app()``.  If the OTel SDK is not installed
    the function returns immediately with no side-effects.
    """
    global _otel_available, _tracer

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
    except ImportError:
        logger.debug("OpenTelemetry packages not installed — telemetry disabled")
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", "aidrin")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # Configure exporter
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry: exporting traces to %s", endpoint)
        except ImportError:
            logger.warning("OpenTelemetry OTLP exporter not installed — traces will not be exported")
    else:
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            logger.info("OpenTelemetry: exporting traces to console (set OTEL_EXPORTER_OTLP_ENDPOINT for production)")
        except ImportError:
            pass

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("aidrin", schema_url="https://opentelemetry.io/schemas/1.11.0")

    # Auto-instrument Flask
    FlaskInstrumentor().instrument_app(app)

    _otel_available = True
    logger.info("OpenTelemetry: tracing enabled for service '%s'", service_name)


def get_tracer():
    """Return the AIDRIN tracer, or a no-op if OTel is not available."""
    if _tracer is not None:
        return _tracer
    return _NoOpTracer()


def trace_metric(name, pillar, file_name=None, file_type=None, **extra_attrs):
    """Context manager that creates a span for a metric evaluation.

    Usage::

        with trace_metric("data_quality", "data_quality", file_name="data.csv"):
            # ... compute metric ...

    When OTel is not installed this is a no-op.
    """
    tracer = get_tracer()
    span_ctx = tracer.start_as_current_span(f"metric.{name}")
    span = span_ctx.__enter__()
    span.set_attribute("metric.name", name)
    span.set_attribute("metric.pillar", pillar)
    if file_name:
        span.set_attribute("file.name", file_name)
    if file_type:
        span.set_attribute("file.type", file_type)
    for k, v in extra_attrs.items():
        span.set_attribute(k, v)

    class _SpanContext:
        def __init__(self):
            self.span = span
            self._ctx = span_ctx

        def __enter__(self):
            return self.span

        def __exit__(self, *args):
            self._ctx.__exit__(*args)

    return _SpanContext()
