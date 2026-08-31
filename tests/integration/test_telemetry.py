"""Tests for OpenTelemetry integration (works with or without OTel installed)."""

from web.telemetry import get_tracer, trace_metric, init_telemetry, _NoOpTracer, _NoOpSpan

# Detect whether the real OTel SDK is available
try:
    from opentelemetry.sdk.trace import Tracer as _OTelTracer
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


def test_get_tracer_returns_valid_tracer():
    """get_tracer returns a no-op when OTel is absent, or a real tracer when present."""
    tracer = get_tracer()
    if _HAS_OTEL:
        assert isinstance(tracer, _OTelTracer)
    else:
        assert isinstance(tracer, _NoOpTracer)


def test_tracer_span():
    """Tracer creates spans that support set_attribute without raising."""
    tracer = get_tracer()
    with tracer.start_as_current_span("test") as span:
        if _HAS_OTEL:
            assert not isinstance(span, _NoOpSpan)
        else:
            assert isinstance(span, _NoOpSpan)
        span.set_attribute("key", "value")  # should not raise


def test_trace_metric_context_manager():
    """trace_metric works as a context manager with or without OTel."""
    with trace_metric("test_metric", "test_pillar", file_name="test.csv") as span:
        span.set_attribute("metric.duration_ms", 123.4)
        # should not raise


def test_init_telemetry_noop(app):
    """init_telemetry should not crash regardless of OTel availability."""
    # Already called during create_app, just verify app works
    assert app is not None


def test_trace_metric_with_extra_attrs():
    """trace_metric accepts extra keyword attributes."""
    with trace_metric("test", "pillar", file_name="f.csv", file_type=".csv", custom="val") as span:
        span.set_attribute("extra", True)
