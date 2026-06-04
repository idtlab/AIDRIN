"""Tests for core routes: file operations, filter, retrieve."""

import os


# -------------------------------------------------
# Retrieve uploaded file
# -------------------------------------------------


def test_retrieve_file_without_upload(client):
    """Should return 404 when no file is uploaded."""
    response = client.get("/retrieve-uploaded-file")
    assert response.status_code == 404
    data = response.get_json()
    assert "error" in data


def test_retrieve_file_after_upload(uploaded_client):
    """Should return the uploaded file."""
    response = uploaded_client.get("/retrieve-uploaded-file")
    assert response.status_code == 200


# -------------------------------------------------
# Filter file (for hierarchical data)
# -------------------------------------------------


def test_filter_file_no_keys(client):
    """/filter-file without keys should return error."""
    response = client.post(
        "/filter-file",
        json={"keys": ""},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False


def test_filter_file_with_keys(uploaded_client):
    """/filter-file with keys should set session."""
    response = uploaded_client.post(
        "/filter-file",
        json={"keys": "age,income"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


def test_filter_file_with_list_keys(uploaded_client):
    """/filter-file accepts keys as a list."""
    response = uploaded_client.post(
        "/filter-file",
        json={"keys": ["age", "income"]},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


# -------------------------------------------------
# Summary statistics edge cases
# -------------------------------------------------


def test_summary_statistics_post_without_file(client):
    """POST to /summary-statistics without file should redirect."""
    response = client.post("/summary-statistics", follow_redirects=False)
    assert response.status_code == 302


def test_summary_statistics_get_without_file(client):
    """GET /summary-statistics without file should return error."""
    response = client.get("/summary-statistics")
    data = response.get_json()
    assert data["success"] is False


def _force_unreadable(client):
    """Mark the uploaded file as Parquet though its bytes are CSV, so read_file
    fails and returns an error string (reproduces the parquet-engine scenario)."""
    with client.session_transaction() as sess:
        sess["uploaded_file_type"] = ".parquet"


def test_summary_statistics_surfaces_read_error_gracefully(uploaded_client):
    """When the file cannot be read, the route returns the real error message,
    not a masked AttributeError from calling DataFrame methods on a string."""
    _force_unreadable(uploaded_client)
    response = uploaded_client.get("/summary-statistics")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is False
    assert data["message"]  # a meaningful message is present
    assert "AttributeError" not in data["message"]
    assert "object has no attribute" not in data["message"]


def test_extract_features_surfaces_read_error_gracefully(uploaded_client):
    """/feature-set should likewise surface a clean read error, not AttributeError."""
    _force_unreadable(uploaded_client)
    response = uploaded_client.post("/feature-set")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is False
    assert data["message"]
    assert "AttributeError" not in data["message"]
    assert "object has no attribute" not in data["message"]


def test_load_dataframe_returns_df_for_valid_csv(sample_csv):
    """The shared helper returns a DataFrame and no error for a readable file."""
    import pandas as pd

    from web.routes.utils import load_dataframe

    df, err = load_dataframe((str(sample_csv), "test_data.csv", ".csv"))
    assert err is None
    assert isinstance(df, pd.DataFrame)


def test_load_dataframe_returns_message_on_read_error():
    """The shared helper converts a read failure into (None, message)."""
    from web.routes.utils import load_dataframe

    df, err = load_dataframe(("/nonexistent/file.csv", "file.csv", ".csv"))
    assert df is None
    assert err


# -------------------------------------------------
# Clear
# -------------------------------------------------


def test_clear_without_session(client):
    """/clear with empty session should still redirect."""
    response = client.post("/clear", follow_redirects=False)
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


# -------------------------------------------------
# Stale session: file type missing
# -------------------------------------------------


def test_stale_session_missing_type(client, sample_csv, app):
    """If file_type is missing from session, inspector should clear it."""
    # Upload a file
    with open(sample_csv, "rb") as f:
        client.post(
            "/inspector",
            data={"file": (f, "test.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    # Manually remove file_type from session
    with client.session_transaction() as sess:
        sess.pop("uploaded_file_type", None)

    # Inspector should detect stale session
    response = client.get("/inspector")
    html = response.data.decode()
    assert 'id="sidebar"' not in html
