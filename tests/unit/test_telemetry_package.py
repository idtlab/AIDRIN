"""Tests for the framework-agnostic ``aidrin.telemetry`` package.

The tracer used to live in ``web/telemetry.py``, which meant the CLI and the MCP
server could not use it without importing Flask.  These tests pin the two
properties that motivated the move: the package is importable on its own, and a
span produced by ``trace_metric`` *encloses* the work it measures rather than
trailing it.
"""

import subprocess
import sys
import time
import types
import unittest

if "pkg_resources" not in sys.modules:
    _pkg = types.ModuleType("pkg_resources")

    class _FakeDist:
        version = "0.0.0"

    _pkg.get_distribution = lambda _name: _FakeDist()
    sys.modules["pkg_resources"] = _pkg

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    HAS_OTEL = True
except ImportError:  # pragma: no cover - exercised in the no-extras CI leg
    HAS_OTEL = False


class TestPackageIsFrameworkAgnostic(unittest.TestCase):
    def test_importing_telemetry_does_not_import_flask(self):
        """The whole point of the move: aidrin/ must not depend on web/."""
        code = (
            "import sys; import aidrin.telemetry; "
            "print('flask' in sys.modules or 'web' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False", "aidrin.telemetry pulled in Flask")

    def test_public_api_is_exposed(self):
        from aidrin.telemetry import get_tracer, trace_metric

        self.assertTrue(callable(get_tracer))
        self.assertTrue(callable(trace_metric))


class TestNoOpWithoutExporter(unittest.TestCase):
    """Everything must work whether or not OpenTelemetry is installed."""

    def test_trace_metric_is_usable_as_a_context_manager(self):
        from aidrin.telemetry import trace_metric

        with trace_metric("probe", "data-quality", file_name="f.csv") as span:
            span.set_attribute("extra", "value")

    def test_get_tracer_always_returns_something_usable(self):
        from aidrin.telemetry import get_tracer

        with get_tracer().start_as_current_span("probe"):
            pass


@unittest.skipUnless(HAS_OTEL, "requires the [telemetry] extra")
class TestSpanEnclosesWork(unittest.TestCase):
    """The regression guard for the bug this work fixes.

    Seven call sites in ``web/routes/metrics.py`` opened their span *after* the
    work finished, producing zero-duration markers carrying a hand-computed
    duration.  A span must cover the work.
    """

    WORK_SECONDS = 0.05

    def setUp(self):
        from opentelemetry import trace

        import aidrin.telemetry as telem

        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        trace.set_tracer_provider(provider)
        telem._tracer = provider.get_tracer("aidrin-test")

    def test_trace_metric_span_covers_the_work(self):
        from aidrin.telemetry import trace_metric

        with trace_metric("probe", "data-quality"):
            time.sleep(self.WORK_SECONDS)

        spans = self.exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        elapsed_ns = spans[0].end_time - spans[0].start_time
        self.assertGreaterEqual(
            elapsed_ns,
            self.WORK_SECONDS * 1e9 * 0.9,
            "span did not enclose the work it measures",
        )

    def test_span_carries_metric_attributes(self):
        from aidrin.telemetry import trace_metric

        with trace_metric("probe", "data-quality", file_name="f.csv", file_type=".csv"):
            pass

        attrs = self.exporter.get_finished_spans()[0].attributes
        self.assertEqual(attrs["metric.name"], "probe")
        self.assertEqual(attrs["file.name"], "f.csv")


@unittest.skipUnless(HAS_OTEL, "requires the [telemetry] extra")
class TestWebShimSharesOneTracer(unittest.TestCase):
    """``web.telemetry`` re-exports; it must not keep a second ``_tracer``."""

    def test_web_and_aidrin_resolve_the_same_tracer(self):
        import aidrin.telemetry as core
        import web.telemetry as shim

        sentinel = object()
        original = core._tracer
        try:
            core._tracer = sentinel
            self.assertIs(shim.get_tracer(), sentinel)
        finally:
            core._tracer = original


if __name__ == "__main__":
    unittest.main()


class TestTracingNeverBreaksTheCaller(unittest.TestCase):
    """Both span helpers are used around real work and must be inert on failure.

    ``trace_metric`` wraps the body of seven web routes. Before this work its
    span trailed the work, so a tracer failure came after the metric had been
    computed; now the span encloses the work, so an unguarded failure would lose
    the result and 500 the request.
    """

    def setUp(self):
        import aidrin.telemetry as telem

        class _BrokenTracer:
            def start_as_current_span(self, *a, **k):
                raise RuntimeError("tracer is down")

        self._telem = telem
        self._original = telem._tracer
        telem._tracer = _BrokenTracer()

    def tearDown(self):
        self._telem._tracer = self._original

    def test_metric_span_survives_a_broken_tracer(self):
        from aidrin.telemetry import metric_span

        with metric_span("probe", category="data-quality"):
            pass

    def test_trace_metric_survives_a_broken_tracer(self):
        from aidrin.telemetry import trace_metric

        with trace_metric("probe", "data_quality", file_name="f.csv") as span:
            span.set_attribute("metric.duration_ms", 12.0)

    def test_the_work_still_happens_when_the_tracer_is_broken(self):
        from aidrin.telemetry import trace_metric

        done = []
        with trace_metric("probe", "data_quality"):
            done.append(True)
        self.assertEqual(done, [True])
