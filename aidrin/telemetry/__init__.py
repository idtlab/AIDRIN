"""Optional OpenTelemetry instrumentation for AIDRIN.

If the ``opentelemetry`` packages are installed (``pip install aidrin[telemetry]``),
this package initialises tracing and exposes a tracer for manual spans.  When the
packages are **not** installed everything degrades to silent no-ops — zero
overhead, zero behaviour change.

This lives under ``aidrin/`` rather than ``web/`` so the CLI and the MCP server can
use it without importing Flask.  ``web/telemetry.py`` re-exports it and adds the
Flask-specific instrumentation.
"""

import contextlib
import logging
import os

from aidrin.telemetry.otel import build_provider

logger = logging.getLogger(__name__)

# Sentinel: set to True once init() succeeds
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

    def record_exception(self, *args, **kwargs):
        pass


class _NoOpTracer:
    """Returned by ``get_tracer()`` when OpenTelemetry is not installed."""

    def start_as_current_span(self, name, **kwargs):
        return _NoOpSpan()


def init(service_name=None):
    """Initialise tracing.  Returns True when OpenTelemetry is active.

    Safe to call more than once and safe to call when the extra is absent, in
    which case it returns False and leaves everything as no-ops.
    """
    global _otel_available, _tracer

    provider = build_provider(service_name)
    if provider is None:
        return False

    from opentelemetry import trace

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(
        "aidrin", schema_url="https://opentelemetry.io/schemas/1.11.0"
    )
    _otel_available = True
    return True


def get_tracer():
    """Return the AIDRIN tracer, or a no-op if OTel is not available."""
    if _tracer is not None:
        return _tracer
    return _NoOpTracer()


def _log_dataset_details():
    """Shared with the MLflow sink; see ``mlflow_sink._log_data_details``."""
    return os.environ.get("AIDRIN_MLFLOW_LOG_DATA_DETAILS", "1").strip() not in (
        "0", "false", "False", "no",
    )


class _SafeSpan:
    """Wraps a span so a telemetry failure can never reach the caller's code.

    Every AIDRIN interface funnels through ``run_metric``; an exception escaping
    from instrumentation there would destroy a computed result.
    """

    def __init__(self, span=None):
        self._span = span

    def set_attribute(self, key, value):
        if self._span is None:
            return
        try:
            self._span.set_attribute(key, value)
        except Exception:  # pragma: no cover - defensive
            logger.debug("telemetry: dropping attribute %s", key, exc_info=True)

    def mark_error(self, exc):
        """Record that the span failed, by exception **type only**.

        Never records ``str(exc)`` and never calls ``record_exception``: metric
        errors routinely interpolate column names and cell values (pandas and
        numpy messages especially), and OTLP ships span data off-box with no
        redaction.
        """
        if self._span is None:
            return
        try:
            from opentelemetry.trace import Status, StatusCode

            self._span.set_attribute("error.type", type(exc).__name__)
            self._span.set_status(Status(StatusCode.ERROR))
        except Exception:  # pragma: no cover - defensive
            logger.debug("telemetry: could not mark span as failed", exc_info=True)


@contextlib.contextmanager
def _span(name):
    """Open a span that can never raise into the caller.

    Instrumentation sits around real work on every interface; an exception
    escaping it would destroy a computed result.
    """
    ctx = None
    handle = _SafeSpan()
    try:
        ctx = get_tracer().start_as_current_span(name)
        handle = _SafeSpan(ctx.__enter__())
    except Exception:
        logger.debug("telemetry: could not start span", exc_info=True)
        ctx = None
        handle = _SafeSpan()

    try:
        yield handle
    except BaseException as exc:
        handle.mark_error(exc)
        raise
    finally:
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensive
                logger.debug("telemetry: could not close span", exc_info=True)


@contextlib.contextmanager
def metric_span(metric_name, category=None, file_path=None, file_type=None):
    """Span enclosing one metric evaluation.

    The span must wrap the work; a span opened afterwards measures nothing.
    Yields a :class:`_SafeSpan`, which is inert when OpenTelemetry is absent or
    when anything about the tracer misbehaves.
    """
    with _span(f"metric.{metric_name}") as handle:
        handle.set_attribute("metric.name", metric_name)
        if category:
            handle.set_attribute("metric.category", category)
        if file_path:
            # The file name identifies the dataset, so it follows the same
            # opt-out as MLflow's dataset details; otherwise turning details off
            # would still export it to the collector. The extension is not
            # identifying and stays.
            if _log_dataset_details():
                handle.set_attribute("file.name", os.path.basename(file_path))
            handle.set_attribute(
                "file.type", file_type or os.path.splitext(file_path)[1].lower()
            )
        yield handle


@contextlib.contextmanager
def trace_metric(name, pillar, file_name=None, file_type=None, **extra_attrs):
    """Span for a metric evaluation in the web app.

    Kept distinct from :func:`metric_span` because the web routes use
    ``metric.pillar`` with its own vocabulary, and take a file name rather than
    a path. Both are guarded the same way: these spans now enclose the work, so
    an unguarded tracer failure would lose the metric and fail the request.

    Usage::

        with trace_metric("data_quality", "data_quality", file_name="data.csv"):
            # ... compute metric ...
    """
    with _span(f"metric.{name}") as handle:
        handle.set_attribute("metric.name", name)
        handle.set_attribute("metric.pillar", pillar)
        if file_name:
            handle.set_attribute("file.name", file_name)
        if file_type:
            handle.set_attribute("file.type", file_type)
        for key, value in extra_attrs.items():
            handle.set_attribute(key, value)
        yield handle
