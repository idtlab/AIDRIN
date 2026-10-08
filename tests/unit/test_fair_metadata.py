"""FAIR metadata assessment: DCAT-US 1.1 and DataCite 4.x profiles."""

import json
from pathlib import Path

import pytest

from aidrin.structured_data_metrics.fair_metadata import (
    FAILED,
    PRINCIPLES,
    calculate_fair_compliance,
    detect_standard,
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
    assert set(result) == {*PRINCIPLES, "Other", "FAIR Compliance Checks", "Pie chart", "Original Metadata", "Standard"}
    assert result["Standard"] == {"Name": "DCAT-US 1.1 (Project Open Data)", "Detected automatically": "no"}
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
# Standard names and the public API
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, form_value", [("dcat-us-1.1", "DCAT"), ("datacite", "Datacite")])
def test_standard_names_and_web_form_values_agree(name, form_value):
    metadata = _load(DCAT_SAMPLES / "BUTTER-E.json")
    by_name = calculate_fair_compliance(metadata, name)
    by_form = calculate_fair_compliance(metadata, form_value)
    assert by_name["FAIR Compliance Checks"] == by_form["FAIR Compliance Checks"]


def test_public_api_reads_a_path_or_a_dict():
    import aidrin

    path = DCAT_SAMPLES / "BUTTER-E.json"
    from_path = aidrin.calculate_fair_compliance(str(path), "dcat-us-1.1")
    from_dict = aidrin.calculate_fair_compliance(_load(path), "dcat-us-1.1")
    assert from_path["FAIR Compliance Checks"] == from_dict["FAIR Compliance Checks"]
    assert "calculate_fair_compliance" in aidrin.__all__


def test_headless_api_drops_only_the_chart_by_default():
    from aidrin.headless import api

    path = str(DCAT_SAMPLES / "BUTTER-E.json")
    assert "Pie chart" not in api.calculate_fair_compliance(path, "dcat-us-1.1")
    assert api.calculate_fair_compliance(path, "dcat-us-1.1", strip_visualizations=False)["Pie chart"]


# ---------------------------------------------------------------------------
# Croissant
# ---------------------------------------------------------------------------

# Real files: Hugging Face's 1.1 export, OpenML's 1.0 export, and the MLCommons
# DICES example, which fills in eight Responsible AI properties.
CROISSANT_HF = FIXTURES / "croissant_1.1_huggingface_mnist.json"
CROISSANT_OPENML = FIXTURES / "croissant_1.0_openml_iris.json"
CROISSANT_RAI = FIXTURES / "croissant_1.0_mlcommons_dices_rai.json"


@pytest.mark.parametrize(
    "fixture, version, total, required",
    [(CROISSANT_HF, "1.1", "13/20", "8/9"), (CROISSANT_OPENML, "1.0", "17/20", "9/9"), (CROISSANT_RAI, "1.0", "12/20", "8/9")],
)
def test_croissant_real_files(fixture, version, total, required):
    result = calculate_fair_compliance(_load(fixture), "croissant")
    assert result["Standard"]["Name"] == f"Croissant {version}"
    assert result["FAIR Compliance Checks"]["Total Checks"] == total
    assert result["Conformance"]["Required properties present"] == required
    assert _scalar_values_only(result)


def test_croissant_conformance_names_missing_required_properties():
    # Hugging Face's export omits datePublished, which Croissant requires.
    result = calculate_fair_compliance(_load(CROISSANT_HF), "croissant")
    assert result["Conformance"]["Missing"] == "datePublished"


def test_croissant_structure_accepts_md5_or_sha256_checksums():
    # OpenML publishes md5; Hugging Face publishes sha256. Both count.
    for fixture in (CROISSANT_HF, CROISSANT_OPENML):
        structure = calculate_fair_compliance(_load(fixture), "croissant")["Structure"]
        assert structure["FileObjects with a checksum (sha256 or md5)"] == "1/1 FileObjects"


def test_croissant_rai_is_reported_not_scored():
    result = calculate_fair_compliance(_load(CROISSANT_RAI), "croissant")
    rai = result["RAI Documentation"]
    assert set(rai) == {"Data life cycle", "Data labeling", "Safety and fairness"}
    assert sum(len(group) for group in rai.values()) == 20  # every property in croissant_rai.ttl
    assert rai["Safety and fairness"]["dataBiases"] != "Not declared"
    assert rai["Safety and fairness"]["dataLimitations"] == "Not declared"
    # Never scored: no RAI property is a FAIR check, and none is repeated under Other.
    rai_properties = {prop for group in rai.values() for prop in group}
    assert not rai_properties & {label for p in PRINCIPLES for label in result[p]}
    assert not rai_properties & set(result["Other"])


def test_croissant_rai_matches_with_or_without_prefix():
    plain = calculate_fair_compliance({"conformsTo": "http://mlcommons.org/croissant/1.1", "dataBiases": "x"}, "croissant")
    prefixed = calculate_fair_compliance({"conformsTo": "http://mlcommons.org/croissant/1.1", "rai:dataBiases": "x"}, "croissant")
    assert plain["RAI Documentation"] == prefixed["RAI Documentation"]


def test_croissant_nested_description_does_not_satisfy_the_dataset_check():
    metadata = _load(CROISSANT_OPENML)
    del metadata["description"]  # every recordSet and field still has one
    result = calculate_fair_compliance(metadata, "croissant")
    assert result["Findable"]["description"] == FAILED
    assert "description" in result["Conformance"]["Missing"]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "metadata, expected",
    [
        (_load(CROISSANT_HF), "croissant"),
        (_load(CROISSANT_OPENML), "croissant"),
        ({"conformsTo": ["http://mlcommons.org/croissant/RAI/1.0", "http://mlcommons.org/croissant/1.1"]}, "croissant"),
        ({"@context": {"cr": "http://mlcommons.org/croissant/"}, "@type": "sc:Dataset"}, "croissant"),
        (_load(DCAT_SAMPLES / "BUTTER-E.json"), "dcat-us-1.1"),
        (_load(DCAT_SAMPLES / "EGS_Collab_Experiment.json"), "dcat-us-1.1"),
        (_load(FIXTURES / "datacite_rest_default.json"), "datacite"),
        (_load(FIXTURES / "datacite_schema_export.json"), "datacite"),
    ],
)
def test_detect_standard(metadata, expected):
    assert detect_standard(metadata) == expected


def test_croissant_version_ignores_the_rai_uri():
    metadata = {"conformsTo": ["http://mlcommons.org/croissant/RAI/1.0", "http://mlcommons.org/croissant/1.1"]}
    assert calculate_fair_compliance(metadata)["Standard"]["Name"] == "Croissant 1.1"


def test_detection_fails_clearly_on_unknown_metadata():
    with pytest.raises(ValueError, match="Could not detect"):
        detect_standard({"@type": "dcat:Dataset", "title": "x"})


def test_auto_is_the_default_and_is_reported():
    result = calculate_fair_compliance(_load(DCAT_SAMPLES / "BUTTER-E.json"))
    assert result["Standard"] == {"Name": "DCAT-US 1.1 (Project Open Data)", "Detected automatically": "yes"}
    assert result["FAIR Compliance Checks"]["Total Checks"] == "20/26"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def test_unknown_standard_raises():
    with pytest.raises(ValueError, match="Unknown metadata type"):
        calculate_fair_compliance({}, "ISO19115")


def test_non_object_metadata_raises():
    with pytest.raises(ValueError, match="JSON object"):
        calculate_fair_compliance([{"title": "x"}], "DCAT")
