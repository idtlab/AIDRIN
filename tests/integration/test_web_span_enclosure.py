"""Web metric routes must emit spans that enclose the work they measure.

Seven routes opened their span *after* the metric finished, wrapping only a
``set_attribute`` call and passing a hand-computed duration — zero-duration
markers that measure nothing.  Two routes (``/data-quality`` and
``/data-structure``) were already correct, with an enclosing parent span and one
child per metric; those are pinned here too so a refactor cannot flatten them.
"""

import pytest

pytest.importorskip("opentelemetry", reason="requires the [telemetry] extra")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

# A metric span must be at least this long; a marker span opened after the work
# is a handful of microseconds.
MIN_REAL_WORK_NS = 1_000_000  # 1ms


@pytest.fixture
def spans(monkeypatch):
    """Capture spans emitted during a request."""
    import aidrin.telemetry as telem

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    monkeypatch.setattr(telem, "_tracer", provider.get_tracer("aidrin-test"))
    return exporter


def _metric_spans(exporter):
    return [s for s in exporter.get_finished_spans() if s.name.startswith("metric.")]


def _named(exporter, name):
    matches = [s for s in _metric_spans(exporter) if s.name == name]
    assert matches, f"no {name} span; got {[s.name for s in _metric_spans(exporter)]}"
    return matches[0]


def _assert_encloses_work(span):
    duration = span.end_time - span.start_time
    assert duration >= MIN_REAL_WORK_NS, (
        f"{span.name} lasted {duration}ns — the span does not enclose the work, "
        "it was opened after the metric finished"
    )


# ---------------------------------------------------------------------------
# The seven trailing-marker routes
# ---------------------------------------------------------------------------


def test_fairness_span_encloses_work(uploaded_client, spans):
    uploaded_client.post(
        "/fairness?return_type=json",
        data={
            "statistical rate": "yes",
            "features for statistical rate": "gender",
            "target for statistical rate": "income",
        },
        follow_redirects=True,
    )
    _assert_encloses_work(_named(spans, "metric.fairness"))


def test_class_imbalance_span_encloses_work(uploaded_client, spans):
    uploaded_client.post(
        "/class-imbalance?return_type=json",
        data={
            "class imbalance": "yes",
            "target features for class imbalance": "gender",
            "distance metric for class imbalance": "CH",
        },
        follow_redirects=True,
    )
    _assert_encloses_work(_named(spans, "metric.class_imbalance"))


def test_privacy_span_encloses_work(uploaded_client, spans):
    uploaded_client.post(
        "/privacy-preservation?return_type=json",
        data={
            "k-anonymity": "yes",
            "quasi identifiers for k-anonymity": ["age", "gender"],
        },
        follow_redirects=True,
    )
    _assert_encloses_work(_named(spans, "metric.privacy_preservation"))


def test_hipaa_span_encloses_work(uploaded_client, spans):
    uploaded_client.post(
        "/hipaa-compliance?return_type=json",
        data={"hipaa compliance": "yes", "columns for hipaa compliance": "age"},
        follow_redirects=True,
    )
    _assert_encloses_work(_named(spans, "metric.hipaa_compliance"))


# ---------------------------------------------------------------------------
# The two routes that were already correct — do not regress them
# ---------------------------------------------------------------------------


def test_data_quality_keeps_its_child_spans(uploaded_client, spans):
    """An enclosing parent plus one child per selected metric."""
    uploaded_client.post(
        "/data-quality?return_type=json",
        data={"completeness": "yes", "duplicity": "yes", "outliers": "yes"},
        follow_redirects=True,
    )
    parent = _named(spans, "metric.data_quality")
    _assert_encloses_work(parent)

    children = {s.name for s in _metric_spans(spans)} - {"metric.data_quality"}
    assert {"metric.completeness", "metric.duplicity", "metric.outliers"} <= children, (
        f"child spans were flattened away; saw {children}"
    )


def test_data_structure_keeps_its_child_spans(uploaded_client, spans):
    uploaded_client.post(
        "/data-structure?return_type=json",
        data={"constant feature count": "yes", "skewness": "yes"},
        follow_redirects=True,
    )
    parent = _named(spans, "metric.data_structure")
    _assert_encloses_work(parent)

    children = {s.name for s in _metric_spans(spans)} - {"metric.data_structure"}
    assert "metric.constant_feature_count" in children, (
        f"child spans were flattened away; saw {children}"
    )
