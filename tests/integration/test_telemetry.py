"""Tests for OpenTelemetry integration (no-op when not installed)."""

from web.telemetry import get_tracer, trace_metric, init_telemetry, _NoOpTracer, _NoOpSpan


def test_get_tracer_returns_noop():
    """Without OTel installed, get_tracer returns a no-op."""
    tracer = get_tracer()
    assert isinstance(tracer, _NoOpTracer)


def test_noop_tracer_span():
    """No-op tracer creates spans that do nothing."""
    tracer = get_tracer()
    with tracer.start_as_current_span("test") as span:
        assert isinstance(span, _NoOpSpan)
        span.set_attribute("key", "value")  # should not raise


def test_trace_metric_context_manager():
    """trace_metric works as a context manager without OTel."""
    with trace_metric("test_metric", "test_pillar", file_name="test.csv") as span:
        span.set_attribute("metric.duration_ms", 123.4)
        # should not raise


def test_init_telemetry_noop(app):
    """init_telemetry should not crash when OTel is not installed."""
    # Already called during create_app, just verify app works
    assert app is not None


def test_trace_metric_with_extra_attrs():
    """trace_metric accepts extra keyword attributes."""
    with trace_metric("test", "pillar", file_name="f.csv", file_type=".csv", custom="val") as span:
        span.set_attribute("extra", True)
