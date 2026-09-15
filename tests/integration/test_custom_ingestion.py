"""Integration tests for upload-time custom loaders (Other / custom loader)."""


GOOD_LOADER = """
import pandas as pd

def load(path, **kwargs):
    df = pd.read_csv(path)
    df["from_custom_loader"] = 1
    return df
"""

BAD_LOADER = """
def load(path, **kwargs):
    return None
"""


def test_upload_with_custom_loader_success(client, tmp_path):
    csv_path = tmp_path / "tiny.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n5,6\n7,8\n9,10\n", encoding="utf-8")
    with open(csv_path, "rb") as handle:
        response = client.post(
            "/inspector",
            data={
                "file": (handle, "tiny.csv"),
                "fileTypeSelector": ".custom",
                "loader_code": GOOD_LOADER,
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "/inspector" in response.headers["Location"]
    with client.session_transaction() as sess:
        assert sess.get("custom_loader_spec")
        assert sess.get("uploaded_file_name") == "tiny.csv"


def test_upload_with_bad_custom_loader_fails(client, tmp_path):
    csv_path = tmp_path / "tiny.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    with open(csv_path, "rb") as handle:
        response = client.post(
            "/inspector",
            data={
                "file": (handle, "tiny.csv"),
                "fileTypeSelector": ".custom",
                "loader_code": BAD_LOADER,
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert not sess.get("custom_loader_spec")
    html = response.data.decode().lower()
    assert "custom loader" in html or "error" in html or "failed" in html


def test_inspector_has_custom_loader_tab_not_dropdown(client):
    response = client.get("/inspector")
    html = response.data.decode()
    assert "Custom Loader" in html
    assert 'id="tab-custom"' in html
    assert 'id="custom-upload"' in html
    assert "Other / custom loader" not in html
    assert "Custom Ingestion" not in html
    assert "panel-custom-ingestion" not in html


def test_inspector_has_no_custom_ingestion_panel(uploaded_client):
    response = uploaded_client.get("/inspector")
    html = response.data.decode()
    assert "panel-custom-ingestion" not in html
    assert "Custom Ingestion" not in html


def test_custom_loader_storage_is_separate_from_metrics(client, app, tmp_path):
    from pathlib import Path

    test_upload_with_custom_loader_success(client, tmp_path)
    with client.session_transaction() as sess:
        loader_path = Path(sess['custom_loader_spec'].rsplit(':', 1)[0])
    assert loader_path.parent == Path(app.config['CUSTOM_LOADERS_FOLDER'])
    assert not loader_path.is_relative_to(Path(app.config['CUSTOM_METRICS_FOLDER']))
    assert loader_path.read_text() == GOOD_LOADER.strip()


def test_custom_loader_fallback_storage_is_separate(client, app, tmp_path, monkeypatch):
    from pathlib import Path

    app.config.pop('CUSTOM_LOADERS_FOLDER')
    monkeypatch.setattr('web.routes.core.tempfile.gettempdir', lambda: str(tmp_path))
    test_upload_with_custom_loader_success(client, tmp_path)
    with client.session_transaction() as sess:
        loader_path = Path(sess['custom_loader_spec'].rsplit(':', 1)[0])
    assert loader_path.parent == tmp_path / 'aidrin_custom_loaders'
    assert not loader_path.is_relative_to(Path(app.config['CUSTOM_METRICS_FOLDER']))


def test_custom_loader_directory_can_be_configured(tmp_path, monkeypatch):
    from web import create_app

    loader_dir = tmp_path / 'dedicated_loaders'
    monkeypatch.setenv('FLASK_CUSTOM_LOADERS_FOLDER', str(loader_dir))
    app = create_app()
    assert app.config['CUSTOM_LOADERS_FOLDER'] == str(loader_dir)
    assert loader_dir.is_dir()


def test_custom_loader_format_mismatch_shows_actionable_error(client):
    import io

    response = client.post(
        "/inspector",
        data={
            "file": (io.BytesIO(b"value\n1\n2\n"), "data.csv"),
            "fileTypeSelector": ".custom",
            "loader_code": "import pandas as pd\ndef load(path, **kwargs):\n    return pd.read_json(path)\n",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Check that the file format matches what this loader expects" in html
    assert "Original error: ValueError:" in html
    with client.session_transaction() as sess:
        assert not sess.get("custom_loader_spec")
