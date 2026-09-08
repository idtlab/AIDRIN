"""Telemetry emitted by ``aidrin.headless.api.run_metric``.

``run_metric`` is the single local entry point for the CLI, the MCP server and
batch runs, none of which had any instrumentation.  These tests pin what its span
must look like, including the two properties that are easy to get wrong: the span
has to *enclose* the work, and telemetry must never be able to break a metric.
"""

import os
import sys
import tempfile
import types
import unittest

import pandas as pd

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
except ImportError:  # pragma: no cover
    HAS_OTEL = False

from aidrin.headless.api import run_metric  # noqa: E402


def _write_csv() -> str:
    df = pd.DataFrame({"age": [31, 42, None, 25], "score": [0.5, 0.7, 0.2, 0.9]})
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


@unittest.skipUnless(HAS_OTEL, "requires the [telemetry] extra")
class TestRunMetricSpan(unittest.TestCase):
    def setUp(self):
        import aidrin.telemetry as telem

        self.csv = _write_csv()
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self._original = telem._tracer
        telem._tracer = provider.get_tracer("aidrin-test")
        self._telem = telem

    def tearDown(self):
        self._telem._tracer = self._original
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def _span_for(self, metric, **kwargs):
        run_metric(metric, self.csv, save_images=False, **kwargs)
        spans = [s for s in self.exporter.get_finished_spans() if s.name.startswith("metric.")]
        self.assertEqual(len(spans), 1, f"expected one span, got {[s.name for s in spans]}")
        return spans[0]

    def test_fast_path_metric_emits_a_span(self):
        span = self._span_for("completeness")
        self.assertEqual(span.name, "metric.completeness")

    def test_span_encloses_the_work(self):
        """A span opened after the work would report a near-zero duration."""
        span = self._span_for("completeness")
        self.assertGreater(
            span.end_time - span.start_time,
            1_000_000,  # 1ms; reading and profiling a CSV cannot be faster
            "span did not enclose the work",
        )

    def test_span_carries_the_registry_category(self):
        span = self._span_for("completeness")
        self.assertEqual(span.attributes["metric.category"], "data-quality")

    def test_file_name_is_derived_not_taken_from_the_argument(self):
        """MCP passes neither file_name nor file_type; they must be derived."""
        span = self._span_for("completeness")
        self.assertEqual(span.attributes["file.name"], os.path.basename(self.csv))
        self.assertEqual(span.attributes["file.type"], ".csv")

    def test_span_records_the_duration(self):
        span = self._span_for("completeness")
        self.assertGreater(span.attributes["metric.duration_ms"], 0)

    def test_registry_path_metric_also_emits_a_span(self):
        span = self._span_for("hipaa_compliance", columns="age")
        self.assertEqual(span.name, "metric.hipaa_compliance")


@unittest.skipUnless(HAS_OTEL, "requires the [telemetry] extra")
class TestSpanNeverLeaksExceptionText(unittest.TestCase):
    """Exception messages echo column names and cell values; only the type is safe."""

    def setUp(self):
        import aidrin.telemetry as telem

        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self._original = telem._tracer
        telem._tracer = provider.get_tracer("aidrin-test")
        self._telem = telem

    def tearDown(self):
        self._telem._tracer = self._original

    def test_failure_records_type_but_not_message(self):
        """Metric errors interpolate column names and cell values into the message."""
        from unittest.mock import patch

        secret = "value 'SSN-123-45-6789' in column 'patient_ssn'"

        with patch.dict(
            "aidrin.headless.api.METRIC_REGISTRY",
            {
                "completeness": {
                    "category": "data-quality",
                    "runner": lambda *a: (_ for _ in ()).throw(ValueError(secret)),
                    "required_args": [],
                }
            },
        ):
            with self.assertRaises(ValueError):
                run_metric("completeness", "/tmp/probe.csv", save_images=False)

        spans = self.exporter.get_finished_spans()
        self.assertTrue(spans, "no span was recorded for the failure")
        for span in spans:
            rendered = repr(span.attributes) + repr(span.events)
            self.assertNotIn("SSN-123-45-6789", rendered, "exception text reached the span")
            self.assertNotIn("patient_ssn", rendered, "exception text reached the span")

    def test_failure_still_records_the_exception_type(self):
        from unittest.mock import patch

        with patch.dict(
            "aidrin.headless.api.METRIC_REGISTRY",
            {
                "completeness": {
                    "category": "data-quality",
                    "runner": lambda *a: (_ for _ in ()).throw(ValueError("boom")),
                    "required_args": [],
                }
            },
        ):
            with self.assertRaises(ValueError):
                run_metric("completeness", "/tmp/probe.csv", save_images=False)

        span = self.exporter.get_finished_spans()[0]
        self.assertEqual(span.attributes["error.type"], "ValueError")


class TestTelemetryCannotBreakMetrics(unittest.TestCase):
    """Telemetry is never allowed to change a result or raise into the caller."""

    def setUp(self):
        self.csv = _write_csv()

    def tearDown(self):
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def test_result_is_unchanged_when_the_tracer_raises(self):
        import aidrin.telemetry as telem

        baseline = run_metric("completeness", self.csv, save_images=False)

        class _ExplodingTracer:
            def start_as_current_span(self, *a, **k):
                raise RuntimeError("tracer is on fire")

        original = telem._tracer
        telem._tracer = _ExplodingTracer()
        try:
            result = run_metric("completeness", self.csv, save_images=False)
        finally:
            telem._tracer = original

        self.assertEqual(result, baseline)



@unittest.skipUnless(HAS_OTEL, "requires the [telemetry] extra")
class TestSpansHonourTheDataDetailsFlag(unittest.TestCase):
    """Opting out of dataset details must cover spans too.

    MLflow hashes the path when details are off; a span that still carries the
    real file name exports it to the collector anyway, which makes the opt-out a
    half-measure.
    """

    def setUp(self):
        import aidrin.telemetry as telem

        self.csv = _write_csv()
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self._original = telem._tracer
        telem._tracer = provider.get_tracer("aidrin-test")
        self._telem = telem

    def tearDown(self):
        self._telem._tracer = self._original
        os.environ.pop("AIDRIN_MLFLOW_LOG_DATA_DETAILS", None)
        try:
            os.unlink(self.csv)
        except OSError:
            pass

    def test_file_name_is_recorded_by_default(self):
        run_metric("completeness", self.csv, save_images=False)
        span = [s for s in self.exporter.get_finished_spans() if s.name.startswith("metric.")][0]
        self.assertEqual(span.attributes["file.name"], os.path.basename(self.csv))

    def test_file_name_is_withheld_when_details_are_off(self):
        os.environ["AIDRIN_MLFLOW_LOG_DATA_DETAILS"] = "0"
        run_metric("completeness", self.csv, save_images=False)
        span = [s for s in self.exporter.get_finished_spans() if s.name.startswith("metric.")][0]
        self.assertNotIn(
            os.path.basename(self.csv), repr(dict(span.attributes)),
            "span exported the file name despite the opt-out",
        )
        # the file type is not identifying and stays useful
        self.assertEqual(span.attributes["file.type"], ".csv")

if __name__ == "__main__":
    unittest.main()
