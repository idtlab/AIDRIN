"""Tests for the file upload flow in the inspector."""

import os


# -------------------------------------------------
# Upload flow
# -------------------------------------------------


def test_upload_csv(client, sample_csv):
    """Uploading a CSV file should set session and redirect."""
    with open(sample_csv, "rb") as f:
        response = client.post(
            "/inspector",
            data={"file": (f, "test_data.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


def test_upload_sets_session(client, sample_csv, app):
    """After upload, session should contain file info."""
    with client.session_transaction() as sess:
        assert "uploaded_file_path" not in sess

    with open(sample_csv, "rb") as f:
        client.post(
            "/inspector",
            data={"file": (f, "test_data.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    with client.session_transaction() as sess:
        assert sess.get("uploaded_file_name") == "test_data.csv"
        assert sess.get("uploaded_file_type") == ".csv"
        assert sess.get("uploaded_file_path", "").endswith("_test_data.csv")


def test_upload_creates_file_on_disk(client, sample_csv, app):
    """Uploaded file should exist on disk."""
    with open(sample_csv, "rb") as f:
        client.post(
            "/inspector",
            data={"file": (f, "test_data.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    with client.session_transaction() as sess:
        file_path = sess.get("uploaded_file_path", "")
    assert os.path.exists(file_path)


# -------------------------------------------------
# Clear flow
# -------------------------------------------------


def test_clear_redirects_to_inspector(uploaded_client):
    """/clear should redirect to /inspector."""
    response = uploaded_client.post("/clear", follow_redirects=False)
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]


def test_clear_empties_session(uploaded_client):
    """After /clear, session should be empty."""
    uploaded_client.post("/clear", follow_redirects=True)
    with uploaded_client.session_transaction() as sess:
        assert "uploaded_file_path" not in sess
        assert "uploaded_file_name" not in sess
        assert "uploaded_file_type" not in sess


def test_clear_shows_upload_panel(uploaded_client):
    """After /clear, inspector should show the upload panel again."""
    uploaded_client.post("/clear", follow_redirects=True)
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    assert "AI Data Readiness Infrastructure" in html
    assert 'id="sidebar"' not in html


# -------------------------------------------------
# Multi-user file isolation on clear
# -------------------------------------------------


def test_upload_tracks_owned_files(client, sample_csv):
    """Upload should record the saved path in session['owned_files']."""
    with open(sample_csv, "rb") as f:
        client.post(
            "/inspector",
            data={"file": (f, "test_data.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    with client.session_transaction() as sess:
        owned = sess.get("owned_files", [])
        assert sess.get("uploaded_file_path") in owned


def test_clear_only_removes_session_owned_files(uploaded_client, app):
    """/clear must delete only the current session's files, not other users'."""
    upload_folder = app.config["UPLOAD_FOLDER"]

    # A file belonging to a different user/session sitting in the shared folder
    other_user_file = os.path.join(upload_folder, "other_user_data.csv")
    with open(other_user_file, "w") as f:
        f.write("a,b\n1,2\n")

    # The current session's own uploaded file
    with uploaded_client.session_transaction() as sess:
        own_file = sess.get("uploaded_file_path", "")
    assert own_file and os.path.exists(own_file)

    try:
        response = uploaded_client.post("/clear", follow_redirects=False)
        assert response.status_code == 302

        # Our own file is removed...
        assert not os.path.exists(own_file)
        # ...but the other user's file is left untouched.
        assert os.path.exists(other_user_file)
    finally:
        if os.path.exists(other_user_file):
            os.remove(other_user_file)


# -------------------------------------------------
# Stale session handling
# -------------------------------------------------


def test_stale_session_cleared(uploaded_client, app):
    """If uploaded file is deleted from disk, session should auto-clear."""
    # Delete the file from disk
    with uploaded_client.session_transaction() as sess:
        file_path = sess.get("uploaded_file_path", "")
    if os.path.exists(file_path):
        os.remove(file_path)

    # Inspector should detect the stale session and show upload panel
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    assert 'id="sidebar"' not in html
    assert "AI Data Readiness Infrastructure" in html
