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
