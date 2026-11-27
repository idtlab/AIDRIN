"""Croissant field guide, shape pre-checks and mlcroissant-backed validation."""

import copy
import json
import os
import sys

import pytest

from aidrin.structured_data_metrics.croissant_schema import field_guide, precheck_value
from aidrin.structured_data_metrics.croissant_validation import (
    _parse_validation_report,
    validate_croissant_jsonld,
)

pytest.importorskip("mlcroissant")

_MNIST = os.path.join(os.path.dirname(__file__), "..", "fixtures", "fair_metadata", "croissant_1.1_huggingface_mnist.json")


@pytest.fixture(scope="module")
def guide():
    return field_guide()


def _mnist():
    with open(_MNIST, encoding="utf-8") as f:
        return json.load(f)


# --- field_guide -------------------------------------------------------------


def test_guide_reads_kinds_and_free_text_from_mlcroissant(guide):
    assert guide["dateModified"]["kind"] == "date" and not guide["dateModified"]["allows_free_text"]
    assert guide["url"]["kind"] == "url" and not guide["url"]["allows_free_text"]
    # license declares CreativeWork | Text | URL, so plain text is allowed too
    assert guide["license"]["kind"] == "url" and guide["license"]["allows_free_text"]
    assert guide["name"]["description"] == "The name of the dataset."


def test_guide_offers_a_template_and_sub_fields_for_simple_nodes(guide):
    publisher = guide["publisher"]
    assert publisher["addable"] is True
    assert publisher["template"] == [{"@type": "Organization"}]
    assert [s["key"] for s in publisher["sub_fields"]] == ["name", "description", "email", "url"]


def test_guide_marks_structural_fields_not_addable(guide):
    for key in ("recordSet", "distribution"):
        assert guide[key]["addable"] is False and guide[key]["template"] is None


def test_guide_format_hints_are_examples_for_dates_and_urls(guide):
    assert guide["datePublished"]["format_hint"]
    assert guide["url"]["format_hint"] == "https://example.org/dataset"
    assert guide["name"]["format_hint"] is None


# --- precheck_value ------------------------------------------------------------


@pytest.mark.parametrize(
    "key, value, message",
    [
        ("datePublished", "last spring", "ISO 8601"),
        ("url", "example.org", "full URL"),
        ("creator", {}, "expected an object"),
        ("creator", [{"@type": "Person", "name": "A"}, {}], "expected an object"),
        ("publisher", "ACME", "expected an object"),
    ],
)
def test_precheck_rejects_bad_shapes(guide, key, value, message):
    errors = precheck_value(key, value, guide)
    assert len(errors) == 1 and message in errors[0] and errors[0].startswith(f"{key}:")


@pytest.mark.parametrize(
    "key, value",
    [
        ("datePublished", "2024-01-31"),
        ("dateModified", "2024-01-31T12:00:00Z"),
        ("url", "https://example.org/data"),
        ("license", "Public"),  # free text is allowed for license
        ("creator", {"@type": "Person", "name": "A"}),
        ("description", ""),
        ("notACroissantField", {}),
    ],
)
def test_precheck_accepts_good_shapes(guide, key, value):
    assert precheck_value(key, value, guide) == []


# --- validation ----------------------------------------------------------------


def test_parse_report_splits_errors_and_warnings():
    report = (
        "Found the following 2 error(s) during the validation:\n"
        "  -  first error\n"
        "  -  second error\n"
        "\n"
        "Found the following 1 warning(s) during the validation:\n"
        "  -  a warning\n"
    )
    assert _parse_validation_report(report) == (["first error", "second error"], ["a warning"])


def test_valid_file_passes_with_warnings():
    result = validate_croissant_jsonld(_mnist())
    assert result["available"] is True and result["valid"] is True and result["errors"] == []
    assert any("datePublished" in w for w in result["warnings"])


def test_empty_nested_object_is_caught_before_the_parser():
    doc = _mnist()
    doc["creator"] = {}
    result = validate_croissant_jsonld(doc)
    assert result["valid"] is False
    assert result["errors"][0].startswith("creator:")


def test_parser_errors_are_reported():
    doc = copy.deepcopy(_mnist())
    doc["@type"] = "sc:Thing"
    result = validate_croissant_jsonld(doc)
    assert result["valid"] is False
    assert any("schema.org/Dataset" in e for e in result["errors"])


def test_missing_mlcroissant_degrades_instead_of_failing(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlcroissant", None)
    assert validate_croissant_jsonld({}) == {"available": False, "valid": None, "errors": [], "warnings": []}


def test_prefixed_keys_get_the_same_shape_checks(guide):
    assert precheck_value("sc:creator", {}, guide)[0].startswith("sc:creator: expected an object")
    assert precheck_value("sc:datePublished", "soon", guide)[0].startswith("sc:datePublished: dates")


def test_empty_prefixed_nested_object_is_caught_before_the_parser():
    doc = _mnist()
    del doc["creator"]
    doc["sc:creator"] = {}
    result = validate_croissant_jsonld(doc)
    assert result["valid"] is False
    assert result["errors"][0].startswith("sc:creator: expected an object")


@pytest.mark.parametrize(
    "version, cite_key",
    [("1.0", "citeAs"), ("1.1", "citeAs"), ("0.8", "citation"), ("unknown version", "citeAs"), (None, "citeAs")],
)
def test_guide_is_built_for_the_declared_version(version, cite_key):
    # citeAs resolves through a version-dependent function: Croissant 0.8 called it citation.
    keys = field_guide(version).keys()
    assert cite_key in keys
    assert ({"citeAs", "citation"} - {cite_key}).isdisjoint(keys)


def test_validation_still_runs_the_parser_if_the_guide_breaks(monkeypatch):
    import aidrin.structured_data_metrics.croissant_schema as schema

    def moved_internal(version=None):
        raise AttributeError("'JsonldField' object has no attribute 'input_types'")

    monkeypatch.setattr(schema, "field_guide", moved_internal)
    assert validate_croissant_jsonld(_mnist())["valid"] is True
    doc = _mnist()
    doc["@type"] = "sc:Thing"
    assert validate_croissant_jsonld(doc)["valid"] is False
