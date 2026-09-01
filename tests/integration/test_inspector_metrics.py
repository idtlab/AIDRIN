"""Tests for metric submission from the inspector."""

import json
from pathlib import Path

import web.routes.metrics as metrics_routes


# -------------------------------------------------
# Summary statistics endpoint
# -------------------------------------------------


def test_summary_statistics_with_file(uploaded_client):
    """/summary-statistics should return JSON with dataset info."""
    response = uploaded_client.get("/summary-statistics")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["records_count"] == 5
    assert data["features_count"] == 4
    assert "age" in data["numerical_features"]
    assert "gender" in data["categorical_features"]
    assert "summary_statistics" in data
    assert "histograms" in data


def test_summary_statistics_without_file(client):
    """/summary-statistics without a file should return error."""
    response = client.get("/summary-statistics")
    data = response.get_json()
    assert data["success"] is False


# -------------------------------------------------
# Feature set endpoint
# -------------------------------------------------


def test_feature_set_with_file(uploaded_client):
    """/feature-set should return feature lists."""
    response = uploaded_client.post("/feature-set")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "age" in data["numerical_features"]
    assert "gender" in data["categorical_features"]
    assert "all_features" in data


def test_feature_set_without_file(client):
    """/feature-set without a file should return error."""
    response = client.post("/feature-set")
    data = response.get_json()
    assert data["success"] is False


# -------------------------------------------------
# Data Quality metric
# -------------------------------------------------


def test_data_quality_completeness(uploaded_client):
    """Submit completeness check — should return JSON results."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"completeness": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "Completeness" in data


def test_data_quality_outliers(uploaded_client):
    """Submit outliers check."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"outliers": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "Outliers" in data


def test_data_quality_duplicity(uploaded_client):
    """Submit duplicity check."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={"duplicity": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert "Duplicity" in data


def test_data_quality_no_selection(uploaded_client):
    """Submit with no metrics selected — should still return 200."""
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={},
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_custom_outlier_targets_with_file(uploaded_client):
    """Target discovery should return selectable column targets without overloading /feature-set."""
    response = uploaded_client.post("/custom-outlier-targets")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    targets = data["targets"]
    assert any(t["name"] == "age" and t["target_type"] == "column" for t in targets)
    assert [target["name"] for target in data["unit_targets"]] == [
        "age",
        "income",
        "education",
        "gender",
    ]
    assert all("unit_candidates" in target for target in data["unit_targets"])


def test_custom_outlier_targets_returns_generic_failure(uploaded_client, monkeypatch):
    def fail_iter_targets(_file_info):
        raise RuntimeError("/secret/internal/path")

    monkeypatch.setattr(metrics_routes, "iter_targets", fail_iter_targets)

    response = uploaded_client.post("/custom-outlier-targets")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"success": False, "message": "Custom outlier target discovery failed."}


def _uploaded_manifest_path(uploaded_client):
    with uploaded_client.session_transaction() as session:
        return Path(session["uploaded_file_path"])


def test_file_reference_options_are_additive_and_configured(uploaded_client, app):
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [app.config["UPLOAD_FOLDER"]]
    app.config["FILE_REFERENCE_WEB_SCAN_LIMIT"] = 23

    response = uploaded_client.post("/custom-outlier-targets")
    data = response.get_json()

    assert data["success"] is True
    assert any(target["name"] == "education" for target in data["targets"])
    assert data["file_reference"] == {
        "enabled": True,
        "roots": [{"id": "root-0", "label": app.config["UPLOAD_FOLDER"]}],
        "scan_limit": 23,
    }


def test_file_reference_invalid_config_does_not_break_target_discovery(uploaded_client, app):
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = ["relative/path", "/not/a/real/directory"]

    data = uploaded_client.post("/custom-outlier-targets").get_json()

    assert data["success"] is True
    assert data["targets"]
    assert data["file_reference"]["enabled"] is False


def test_data_structure_file_reference_validation_returns_metadata(uploaded_client, app):
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    artifact = upload_dir / "artifact.bin"
    artifact.write_bytes(b"aidrin")
    _uploaded_manifest_path(uploaded_client).write_text("file_path\nartifact.bin\n", encoding="utf-8")
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [str(upload_dir)]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "file_path",
            "file_reference_root_id": "root-0",
            "file_reference_base_subdirectory": "",
            "file_reference_max_results": "10",
        },
    )
    result = response.get_json()["File Reference Validation"]

    assert result["Summary"]["all_references_valid"] == 1
    assert result["File metadata"][0]["resolved_path"] == str(artifact)
    assert result["File metadata"][0]["size_bytes"] == 6


def test_understandability_variable_unit_validation_uses_request_local_mapping(uploaded_client):
    mapping = {
        "age": {"unit": "year"},
        "income": {"unit": "kilogram"},
        "education": {"status": "not_applicable"},
        "gender": {"status": "not_applicable"},
    }

    response = uploaded_client.post(
        "/variable-unit-validation?return_type=json",
        data={
            "variable_unit_validation": "yes",
            "variable_unit_declarations": json.dumps(mapping),
        },
    )
    result = response.get_json()["Variable Unit Validation"]

    assert result["all_variables_ready"] == 1
    assert result["counts"]["valid"] == 2
    assert result["counts"]["not_applicable"] == 2


def test_variable_unit_error_is_metric_scoped(uploaded_client):
    response = uploaded_client.post(
        "/variable-unit-validation?return_type=json",
        data={
            "variable_unit_validation": "yes",
            "variable_unit_declarations": "[]",
        },
    )
    data = response.get_json()

    assert "unit_declarations must be a JSON object" in data["Variable Unit Validation"]["Error"]


def test_data_structure_file_reference_validation_preserves_comma_target_names(uploaded_client, app):
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    artifact = upload_dir / "artifact.bin"
    artifact.write_bytes(b"aidrin")
    _uploaded_manifest_path(uploaded_client).write_text('"file,path"\nartifact.bin\n', encoding="utf-8")
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [str(upload_dir)]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "file,path",
            "file_reference_root_id": "root-0",
        },
    )
    result = response.get_json()["File Reference Validation"]

    assert list(result["Target summaries"]) == ["file,path"]
    assert result["Summary"]["all_references_valid"] == 1


def test_data_structure_file_reference_validation_accepts_regex_targets(uploaded_client, app):
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    artifact = upload_dir / "artifact.bin"
    artifact.write_bytes(b"aidrin")
    _uploaded_manifest_path(uploaded_client).write_text(
        "primary_path,notes\nartifact.bin,ok\n", encoding="utf-8"
    )
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [str(upload_dir)]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_target_match": "regex",
            "file_reference_targets": r"primary_[a-z]{1,4}",
            "file_reference_root_id": "root-0",
        },
    )
    result = response.get_json()["File Reference Validation"]

    assert list(result["Target summaries"]) == ["primary_path"]
    assert result["Summary"]["all_references_valid"] == 1


def test_data_quality_no_longer_dispatches_file_reference_validation(uploaded_client, app):
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [app.config["UPLOAD_FOLDER"]]

    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "education",
            "file_reference_root_id": "root-0",
        },
    )

    assert "File Reference Validation" not in response.get_json()


def test_file_reference_bad_root_id_is_metric_scoped(uploaded_client, app):
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [app.config["UPLOAD_FOLDER"]]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "constant feature count": "yes",
            "file_reference_validation": "yes",
            "file_reference_targets": "education",
            "file_reference_root_id": "root-999",
        },
    )
    data = response.get_json()

    assert "Constant Feature Count" in data
    assert "Select an allowed filesystem root" in data["File Reference Validation"]["Error"]


def test_file_reference_rejects_base_directory_traversal(uploaded_client, app):
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [app.config["UPLOAD_FOLDER"]]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "education",
            "file_reference_root_id": "root-0",
            "file_reference_base_subdirectory": "..",
        },
    )

    assert "must stay inside" in response.get_json()["File Reference Validation"]["Error"]


def test_file_reference_rejects_symlinked_base_directory(uploaded_client, app, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = Path(app.config["UPLOAD_FOLDER"]) / "linked"
    link.symlink_to(outside, target_is_directory=True)
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [app.config["UPLOAD_FOLDER"]]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "education",
            "file_reference_root_id": "root-0",
            "file_reference_base_subdirectory": "linked",
        },
    )

    assert "must stay inside" in response.get_json()["File Reference Validation"]["Error"]


def test_file_reference_enforces_root_and_web_scan_cap(uploaded_client, app, tmp_path):
    upload_dir = Path(app.config["UPLOAD_FOLDER"])
    allowed = upload_dir / "allowed.bin"
    allowed.write_bytes(b"allowed")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    _uploaded_manifest_path(uploaded_client).write_text(
        f"file_path\n{allowed}\n{outside}\n",
        encoding="utf-8",
    )
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [str(upload_dir)]
    app.config["FILE_REFERENCE_WEB_SCAN_LIMIT"] = 1

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "file_path",
            "file_reference_root_id": "root-0",
            "file_reference_max_results": "10",
        },
    )
    result = response.get_json()["File Reference Validation"]

    assert result["Summary"]["scanned_values"] == 1
    assert result["Summary"]["unscanned_values"] == 1
    assert result["Summary"]["scan_complete"] == 0


def test_file_reference_reports_absolute_path_outside_root(uploaded_client, app, tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    _uploaded_manifest_path(uploaded_client).write_text(f"file_path\n{outside}\n", encoding="utf-8")
    app.config["FILE_REFERENCE_ALLOWED_ROOTS"] = [app.config["UPLOAD_FOLDER"]]

    response = uploaded_client.post(
        "/data-structure?return_type=json",
        data={
            "file_reference_validation": "yes",
            "file_reference_targets": "file_path",
            "file_reference_root_id": "root-0",
        },
    )
    result = response.get_json()["File Reference Validation"]

    assert result["Summary"]["invalid_references"] == 1
    assert result["Invalid references"][0]["reason"] == "outside_allowed_root"


def test_data_quality_custom_outliers(uploaded_client):
    """Submit custom outlier rules through Data Quality."""
    rules = [{
        "id": "age-range",
        "name": "Age range",
        "target": "age",
        "target_type": "column",
        "criteria": {"type": "range", "min": 26, "max": 38},
    }]
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={
            "custom_outliers": "yes",
            "custom_outlier_rules": json.dumps(rules),
            "max_outliers": "2",
            "max_export_rows": "10",
            "scan_limit": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "Custom Criteria Outliers" in data
    result = data["Custom Criteria Outliers"]
    assert result["Rule summaries"]["age-range"]["outlier"] == 2
    assert len(result["Outlier preview"]["age-range"]) == 2
    assert len(result["Outlier export"]["age-range"]) == 2


def test_data_quality_custom_outlier_error_is_metric_scoped(uploaded_client):
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={
            "completeness": "yes",
            "custom_outliers": "yes",
            "custom_outlier_rules": "[]",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    data = response.get_json()
    assert "Completeness" in data
    assert "error" not in data
    assert "Custom Criteria Outliers" in data
    assert "Error" in data["Custom Criteria Outliers"]


def test_data_quality_custom_outlier_missing_target_is_actionable(uploaded_client):
    rules = [{
        "id": "missing-target",
        "target": "missing_column",
        "target_type": "column",
        "criteria": {"type": "range", "min": 0, "max": 1},
    }]
    response = uploaded_client.post(
        "/data-quality?return_type=json",
        data={
            "custom_outliers": "yes",
            "custom_outlier_rules": json.dumps(rules),
        },
        follow_redirects=True,
    )
    error = response.get_json()["Custom Criteria Outliers"]["Errors"][0]["error"]
    assert "Target not found: missing_column" in error
    assert "Select an exact column or HDF5 dataset path from the Target list." in error


# -------------------------------------------------
# Fairness metric
# -------------------------------------------------


def test_fairness_representation_rate(uploaded_client):
    """Submit representation rate check."""
    response = uploaded_client.post(
        "/fairness?return_type=json",
        data={
            "representation rate": "yes",
            "features for representation rate": "gender",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Class Imbalance metric
# -------------------------------------------------


def test_class_imbalance(uploaded_client):
    """Submit class imbalance check."""
    response = uploaded_client.post(
        "/class-imbalance?return_type=json",
        data={
            "class imbalance": "yes",
            "target features for class imbalance": "gender",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None


# -------------------------------------------------
# Error handling
# -------------------------------------------------


def test_metric_without_file(client):
    """Posting to a metric route without a file should not crash."""
    response = client.post(
        "/data-quality?return_type=json",
        data={"completeness": "yes"},
        follow_redirects=True,
    )
    # Should either redirect or return an error — not 500
    assert response.status_code in (200, 302)
