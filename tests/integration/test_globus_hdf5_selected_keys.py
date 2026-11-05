"""Globus submit carries HDF5 selected_keys (issue #236)."""

from unittest.mock import patch

import pytest

from web.globus import is_globus_available


@pytest.fixture
def globus_session(client):
    if not is_globus_available():
        pytest.skip("Globus SDK not installed")

    with client.session_transaction() as sess:
        sess["globus_authenticated"] = True
        sess["globus_endpoint_id"] = "endpoint-uuid"
        sess["globus_file_path"] = "/data/multi.h5"
        sess["globus_file_name"] = "multi.h5"
        sess["globus_file_type"] = ".h5"
    return client


def test_globus_submit_forwards_selected_keys(globus_session):
    captured = {}

    def fake_submit(client, endpoint_id, metric_name, file_path, file_name, file_type, **params):
        captured["params"] = params
        return "task-1"

    with patch("web.routes.globus.submit_metric", side_effect=fake_submit):
        with patch("web.routes.globus._submission_negotiation", return_value=({"fingerprint": "fp"}, None)):
            with patch("web.routes.globus.get_compute_client", return_value=object()):
                response = globus_session.post(
                    "/globus/submit",
                    json={
                        "endpoint_id": "endpoint-uuid",
                        "file_path": "/data/multi.h5",
                        "file_name": "multi.h5",
                        "file_type": ".h5",
                        "metric_name": "completeness",
                        "selected_keys": ["grp/a", "grp/b"],
                        "params": {},
                    },
                )

    assert response.status_code == 200
    assert captured["params"]["selected_keys"] == ["grp/a", "grp/b"]

    with globus_session.session_transaction() as sess:
        assert sess["globus_selected_keys"] == ["grp/a", "grp/b"]


def test_globus_filter_datasets_persists_keys(globus_session):
    response = globus_session.post(
        "/globus/filter-datasets",
        json={"keys": ["dset/1"]},
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    with globus_session.session_transaction() as sess:
        assert sess["globus_selected_keys"] == ["dset/1"]


def test_rejected_submission_keeps_the_previous_selection(globus_session):
    """A 409 from the negotiation must not strip the loaded file's keys."""
    with globus_session.session_transaction() as sess:
        sess["globus_selected_keys"] = ["grp/a"]
        sess["intent"] = {"note": "keep me"}

    with patch("web.routes.globus._submission_negotiation", return_value=(None, {})):
        with patch("web.routes.globus.get_compute_client", return_value=object()):
            response = globus_session.post(
                "/globus/submit",
                json={
                    "endpoint_id": "endpoint-uuid",
                    "file_path": "/data/other.h5",
                    "file_name": "other.h5",
                    "file_type": ".h5",
                    "metric_name": "completeness",
                    "params": {},
                },
            )

    assert response.status_code == 409
    with globus_session.session_transaction() as sess:
        assert sess["globus_selected_keys"] == ["grp/a"]
        assert sess["intent"] == {"note": "keep me"}
        assert sess["globus_file_path"] == "/data/multi.h5"


def test_inventory_probe_does_not_claim_the_file_is_loaded(globus_session):
    """Reading a candidate file's dataset list must not rewrite session identity."""

    def fake_submit(client, endpoint_id, metric_name, file_path, file_name, file_type, **params):
        return "task-inv"

    with patch("web.routes.globus.submit_metric", side_effect=fake_submit):
        with patch("web.routes.globus._submission_negotiation", return_value=({"fingerprint": "fp"}, None)):
            with patch("web.routes.globus.get_compute_client", return_value=object()):
                response = globus_session.post(
                    "/globus/submit",
                    json={
                        "endpoint_id": "endpoint-uuid",
                        "file_path": "/data/candidate.h5",
                        "file_name": "candidate.h5",
                        "file_type": ".h5",
                        "metric_name": "file_inventory",
                        "params": {},
                    },
                )

    assert response.status_code == 200
    with globus_session.session_transaction() as sess:
        assert sess["globus_file_path"] == "/data/multi.h5"
        assert sess["globus_file_name"] == "multi.h5"


def test_cache_summary_keys_on_the_result_not_the_session(globus_session, app):
    """An in-flight summary must not be filed under a newer selection."""
    from web.routes.globus import _globus_summary_cache_key

    with globus_session.session_transaction() as sess:
        sess["globus_selected_keys"] = ["newer/selection"]

    response = globus_session.post(
        "/globus/cache-summary",
        json={"Summary": {}, "selected_dataset_keys": ["grp/a", "grp/b"]},
    )
    assert response.status_code == 200

    ran_with = _globus_summary_cache_key("endpoint-uuid", "/data/multi.h5", ["grp/a", "grp/b"])
    session_now = _globus_summary_cache_key("endpoint-uuid", "/data/multi.h5", ["newer/selection"])
    assert ran_with in app.TEMP_RESULTS_CACHE
    assert session_now not in app.TEMP_RESULTS_CACHE
