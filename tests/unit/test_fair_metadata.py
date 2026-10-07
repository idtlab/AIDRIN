"""FAIR metadata assessment: DCAT-US 1.1 and DataCite 4.x profiles."""

import json
from pathlib import Path

import pytest

from aidrin.structured_data_metrics.fair_metadata import (
    FAILED,
    PRINCIPLES,
    calculate_fair_compliance,
)

ROOT = Path(__file__).resolve().parents[2]
DCAT_SAMPLES = ROOT / "examples" / "sample_data" / "dcat"
FIXTURES = ROOT / "tests" / "fixtures" / "fair_metadata"


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _scalar_values_only(result):
    return all(
        not isinstance(value, (dict, list))
        for principle in PRINCIPLES
        for value in result[principle].values()
    )


# ---------------------------------------------------------------------------
# DCAT-US 1.1
# ---------------------------------------------------------------------------

# Before this module, the matcher flattened nested keys and matched by suffix:
# BUTTER-E scored 18/26 and EGS_Collab 17/26, missing ``publisher`` and
# ``contactPoint`` (both objects) and taking ``title`` from a distribution.
@pytest.mark.parametrize(
    "sample, expected",
    [
        ("BUTTER-E.json", {"Findable": "5/6", "Accessible": "6/6", "Interoperable": "2/6", "Reusable": "7/8", "Total": "20/26"}),
        (
            "EGS_Collab_Experiment.json",
            {"Findable": "5/6", "Accessible": "5/6", "Interoperable": "2/6", "Reusable": "7/8", "Total": "19/26"},
        ),
    ],
)
def test_dcat_sample_scores(sample, expected):
    checks = calculate_fair_compliance(_load(DCAT_SAMPLES / sample), "DCAT")["FAIR Compliance Checks"]
    assert {p: checks[f"{p} Checks"] for p in PRINCIPLES} | {"Total": checks["Total Checks"]} == expected


def test_dcat_object_values_count_as_present():
    metadata = _load(DCAT_SAMPLES / "BUTTER-E.json")
    reusable = calculate_fair_compliance(metadata, "DCAT")["Reusable"]
    assert reusable["publisher"] == metadata["publisher"]["name"]
    assert reusable["contactPoint"] == metadata["contactPoint"]["fn"]


def test_dcat_dataset_fields_come_from_top_level_only():
    metadata = _load(DCAT_SAMPLES / "BUTTER-E.json")
    findable = calculate_fair_compliance(metadata, "DCAT")["Findable"]
    assert findable["title"] == metadata["title"]

    del metadata["title"]
    del metadata["description"]
    result = calculate_fair_compliance(metadata, "DCAT")
    # Every distribution still has a title and a description; neither may stand in.
    assert result["Findable"]["title"] == FAILED
    assert result["Findable"]["description"] == FAILED
    assert result["Reusable"]["description"] == FAILED


def test_dcat_distribution_checks_report_coverage():
    metadata = _load(DCAT_SAMPLES / "EGS_Collab_Experiment.json")
    result = calculate_fair_compliance(metadata, "DCAT")
    n = len(metadata["distribution"])
    assert result["Accessible"]["accessURL (distribution)"] == f"{n}/{n} distributions"
    assert result["Accessible"]["downloadURL (distribution)"] == FAILED


def test_dcat_prefixed_keys_match():
    result = calculate_fair_compliance({"dct:title": "T", "http://www.w3.org/ns/dcat#keyword": ["a", "b"]}, "DCAT")
    assert result["Findable"]["title"] == "T"
    assert result["Findable"]["keyword"] == "a, b"


def test_dcat_empty_values_fail():
    result = calculate_fair_compliance({"title": "", "keyword": [], "publisher": {}, "license": None}, "DCAT")
    assert result["FAIR Compliance Checks"]["Total Checks"] == "0/26"


def test_dcat_output_shape():
    metadata = _load(DCAT_SAMPLES / "BUTTER-E.json")
    result = calculate_fair_compliance(metadata, "DCAT")
    assert set(result) == {*PRINCIPLES, "Other", "FAIR Compliance Checks", "Pie chart", "Original Metadata"}
    assert result["Original Metadata"] == metadata
    assert "distribution" not in result["Other"]
    assert result["Other"]["DOI"] == metadata["DOI"]
    assert _scalar_values_only(result)


# ---------------------------------------------------------------------------
# DataCite 4.x
# ---------------------------------------------------------------------------

DATACITE_FIXTURES = ["datacite_rest_default.json", "datacite_rest_full.json", "datacite_schema_export.json"]


@pytest.mark.parametrize("fixture", DATACITE_FIXTURES)
def test_datacite_findable_core_fields_pass_in_every_shape(fixture):
    result = calculate_fair_compliance(_load(FIXTURES / fixture), "Datacite")
    assert all(value != FAILED for value in result["Findable"].values()), result["Findable"]
    assert result["Findable"]["identifier (DOI)"] == "10.5281/zenodo.12168626"
    assert result["Conformance"]["Mandatory properties present"] == "6/6"
    assert _scalar_values_only(result)


def test_datacite_url_check_fails_only_without_registration_fields():
    rest = calculate_fair_compliance(_load(FIXTURES / "datacite_rest_default.json"), "Datacite")
    export = calculate_fair_compliance(_load(FIXTURES / "datacite_schema_export.json"), "Datacite")
    assert rest["Accessible"]["url or contentUrl"] == "https://zenodo.org/doi/10.5281/zenodo.12168626"
    assert export["Accessible"]["url or contentUrl"] == FAILED


def test_datacite_string_forms_are_not_assessable_rather_than_zero():
    default = calculate_fair_compliance(_load(FIXTURES / "datacite_rest_default.json"), "Datacite")["Structure"]
    full = calculate_fair_compliance(_load(FIXTURES / "datacite_rest_full.json"), "Datacite")["Structure"]
    assert default["Affiliations with ROR"].startswith("not assessable")
    assert default["Publisher identifier"].startswith("not assessable")
    assert full["Affiliations with ROR"] == "1/1 affiliations"
    assert full["Publisher identifier"] == "no"
    assert full["Creators with ORCID"] == "1/1 creators"


def test_datacite_rest_bookkeeping_is_dropped():
    raw = _load(FIXTURES / "datacite_rest_default.json")
    assert raw["data"]["attributes"]["xml"]
    result = calculate_fair_compliance(raw, "Datacite")
    for noise in ("xml", "viewsOverTime", "citationCount", "state"):
        assert noise not in result["Original Metadata"]
        assert noise not in result["Other"]


def test_datacite_identifiers_need_doi_type():
    metadata = {"identifiers": [{"identifier": "hdl:123", "identifierType": "Handle"}]}
    result = calculate_fair_compliance(metadata, "Datacite")
    assert result["Findable"]["identifier (DOI)"] == FAILED
    assert result["Conformance"]["Missing"].startswith("Identifier")


def test_datacite_contributors_score_under_reusable():
    result = calculate_fair_compliance({"contributors": [{"name": "A"}]}, "Datacite")
    assert result["Reusable"]["contributors"] == "A"
    assert "contributors" not in result["Accessible"]


def test_datacite_access_rights_and_license_are_separate_checks():
    rights = [
        {"rights": "Open Access", "rightsUri": "info:eu-repo/semantics/openAccess"},
        {"rights": "CC BY 4.0", "rightsUri": "https://creativecommons.org/licenses/by/4.0/"},
    ]
    result = calculate_fair_compliance({"rightsList": rights}, "Datacite")
    assert result["Accessible"]["access rights (rightsList)"] == "info:eu-repo/semantics/openAccess"
    assert result["Reusable"]["license (rightsList rightsUri)"] == "CC BY 4.0"

    only_access = calculate_fair_compliance({"rightsList": rights[:1]}, "Datacite")
    assert only_access["Reusable"]["license (rightsList rightsUri)"] == FAILED


def test_datacite_totals_follow_the_profile():
    checks = calculate_fair_compliance({}, "Datacite")["FAIR Compliance Checks"]
    assert checks == {
        "Findable Checks": "0/8",
        "Accessible Checks": "0/2",
        "Interoperable Checks": "0/4",
        "Reusable Checks": "0/8",
        "Total Checks": "0/22",
    }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def test_unknown_standard_raises():
    with pytest.raises(ValueError, match="Unknown metadata type"):
        calculate_fair_compliance({}, "ISO19115")


def test_non_object_metadata_raises():
    with pytest.raises(ValueError, match="JSON object"):
        calculate_fair_compliance([{"title": "x"}], "DCAT")
