"""Croissant editing and provenance outside the browser (CLI, MCP, library)."""

import json
import os
from datetime import datetime, timezone

import pytest

from aidrin.headless import api
from aidrin.structured_data_metrics.croissant_enhance import (
    apply_croissant_edits,
    coerce_value,
    croissant_field_status,
)

_FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "fair_metadata")
_MNIST = os.path.join(_FIXTURES, "croissant_1.1_huggingface_mnist.json")
_DATACITE = os.path.join(_FIXTURES, "datacite_rest_full.json")
_NOW = datetime(2026, 3, 4, 5, 6, 7, 890000, tzinfo=timezone.utc)


def _mnist():
    with open(_MNIST, encoding="utf-8") as f:
        return json.load(f)


# --- apply_croissant_edits ---------------------------------------------------


def test_edits_and_provenance_match_the_web_ui_stamp():
    edited = apply_croissant_edits({"name": "x"}, {"license": "https://example.org/l"}, "Jane Doe", "ACME", now=_NOW)
    person = {"@type": "Person", "name": "Jane Doe", "affiliation": {"@type": "Organization", "name": "ACME"}}
    assert edited["license"] == "https://example.org/l"
    assert edited["dateModified"] == "2026-03-04"
    assert edited["contributor"] == [person]
    assert edited["wasGeneratedBy"] == {
        "@type": "UpdateAction",
        "agent": person,
        "startTime": "2026-03-04T05:06:07.890Z",
        "instrument": {"@type": "SoftwareApplication", "name": "AIDRIN"},
    }


def test_affiliation_is_left_out_when_not_given():
    edited = apply_croissant_edits({}, {"version": "1.0"}, "Jane", None, now=_NOW)
    assert edited["contributor"] == [{"@type": "Person", "name": "Jane"}]


def test_existing_contributors_are_kept_and_the_input_is_not_mutated():
    original = {"contributor": {"@type": "Person", "name": "Old"}}
    edited = apply_croissant_edits(original, {"version": "2"}, "New", now=_NOW)
    assert [c["name"] for c in edited["contributor"]] == ["Old", "New"]
    assert original == {"contributor": {"@type": "Person", "name": "Old"}}


def test_edit_lands_on_the_files_own_prefixed_key():
    edited = apply_croissant_edits({"sc:license": "old"}, {"license": "new"}, "Jane", now=_NOW)
    assert edited["sc:license"] == "new"
    assert "license" not in edited


@pytest.mark.parametrize("name", ["", "   ", None])
def test_contributor_name_is_required(name):
    with pytest.raises(ValueError, match="contributor name"):
        apply_croissant_edits({}, {"version": "1"}, name)


def test_at_least_one_edit_is_required():
    with pytest.raises(ValueError, match="No edits"):
        apply_croissant_edits({}, {}, "Jane")


# --- coerce_value -------------------------------------------------------------


def test_coerce_value_parses_json_and_typed_fields():
    guide = {"isAccessibleForFree": {"kind": "boolean"}, "size": {"kind": "number"}}
    assert coerce_value("publisher", '{"@type": "Organization", "name": "A"}', guide) == {"@type": "Organization", "name": "A"}
    assert coerce_value("keywords", '["a", "b"]', guide) == ["a", "b"]
    assert coerce_value("version", "1.0", guide) == "1.0"
    assert coerce_value("isAccessibleForFree", "True", guide) is True
    assert coerce_value("size", "3", guide) == 3
    assert coerce_value("size", "3.5", guide) == 3.5
    with pytest.raises(ValueError, match="does not parse"):
        coerce_value("publisher", "{not json", guide)


def test_coerce_value_keeps_text_for_fields_that_allow_it():
    guide = {"version": {"kind": "number", "allows_free_text": True}}
    assert coerce_value("version", "1.10", guide) == "1.10"
    assert coerce_value("version", "2", guide) == "2"


# --- field status and the headless API (need mlcroissant) ----------------------


def test_field_status_splits_missing_and_present():
    pytest.importorskip("mlcroissant")
    status = croissant_field_status(_mnist())
    missing = {f["key"]: f for f in status["missing"]}
    present = {f["key"] for f in status["present"]}
    assert status["available"] is True
    assert {"name", "license", "creator"} <= present
    assert "datePublished" in missing and missing["datePublished"]["format_hint"]
    assert [s["key"] for s in missing["publisher"]["sub_fields"]][:1] == ["name"]


def test_enhance_writes_a_valid_file_and_raises_the_score(tmp_path):
    pytest.importorskip("mlcroissant")
    out = tmp_path / "mnist.json"
    result = api.enhance_croissant(_MNIST, {"datePublished": "2024-01-01", "version": "1.0.0"}, "Jane", str(out), "ACME")
    assert result["written"] is True and result["validation"]["valid"] is True
    assert result["edited_fields"] == ["datePublished", "version"]
    assert result["fair_before"] != result["fair_after"]
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["datePublished"] == "2024-01-01"
    assert written["wasGeneratedBy"]["agent"]["name"] == "Jane"


def test_enhance_does_not_write_an_invalid_file(tmp_path):
    pytest.importorskip("mlcroissant")
    out = tmp_path / "bad.json"
    result = api.enhance_croissant(_MNIST, {"datePublished": "soon"}, "Jane", str(out))
    assert result["written"] is False and result["output_path"] is None
    assert any("datePublished" in e for e in result["validation"]["errors"])
    assert not out.exists()


def test_enhance_refuses_to_overwrite_the_input():
    with pytest.raises(ValueError, match="never overwritten"):
        api.enhance_croissant(_MNIST, {"version": "1"}, "Jane", _MNIST)


def test_non_croissant_files_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="not a Croissant file"):
        api.validate_croissant(_DATACITE)
    with pytest.raises(ValueError, match="not a Croissant file"):
        api.enhance_croissant(_DATACITE, {"version": "1"}, "Jane", str(tmp_path / "o.json"))


@pytest.mark.parametrize("key", ["dateModified", "sc:dateModified"])
def test_an_explicit_date_modified_is_not_overwritten_by_the_stamp(key):
    edited = apply_croissant_edits({"sc:dateModified": "2019-01-01"}, {key: "2020-05-05"}, "Jane", now=_NOW)
    assert edited["sc:dateModified"] == "2020-05-05"
    assert "dateModified" not in edited


def test_the_stamp_uses_the_files_prefixed_date_and_contributor_keys():
    original = {"sc:dateModified": "2019-01-01", "sc:contributor": [{"@type": "Person", "name": "Old"}]}
    edited = apply_croissant_edits(original, {"version": "2"}, "New", now=_NOW)
    assert edited["sc:dateModified"] == "2026-03-04"
    assert [c["name"] for c in edited["sc:contributor"]] == ["Old", "New"]
    assert "dateModified" not in edited and "contributor" not in edited


def test_field_status_degrades_if_the_guide_breaks(monkeypatch):
    import aidrin.structured_data_metrics.croissant_schema as schema

    def moved_internal(version=None):
        raise AttributeError("'JsonldField' object has no attribute 'cardinality'")

    monkeypatch.setattr(schema, "field_guide", moved_internal)
    status = croissant_field_status(_mnist())
    assert status["available"] is False and "cardinality" in status["error"]


def test_enhance_scores_without_rendering_charts(tmp_path, monkeypatch):
    pytest.importorskip("mlcroissant")
    from aidrin.structured_data_metrics import fair_metadata

    def no_charts(*args, **kwargs):
        raise AssertionError("enhance_croissant should not render the FAIR chart")

    monkeypatch.setattr(fair_metadata, "_chart", no_charts)
    result = api.enhance_croissant(_MNIST, {"version": "1.0.0"}, "Jane", str(tmp_path / "o.json"))
    assert result["written"] is True


def test_check_summary_matches_the_full_assessment():
    from aidrin.structured_data_metrics.fair_metadata import calculate_fair_compliance, croissant_check_summary

    assert croissant_check_summary(_mnist()) == calculate_fair_compliance(_mnist(), "croissant")["FAIR Compliance Checks"]
