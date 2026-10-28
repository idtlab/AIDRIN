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


def test_loader_failure_response_carries_no_server_paths(client, tmp_path):
    """The loader's own error reaches the page, but without server directories.

    An import-time failure is not behind ``describe_loader_error``'s
    "Original error:" truncation, so its text is what the web user sees
    (CodeQL py/stack-trace-exposure on the load_dataframe sinks).
    """
    leaky_loader = (
        'raise ImportError("cannot open /srv/aidrin/private/model.pkl")\n'
        "\n"
        "def load(path, **kwargs):\n"
        "    return None\n"
    )
    csv_path = tmp_path / "tiny.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    with open(csv_path, "rb") as handle:
        response = client.post(
            "/inspector",
            data={
                "file": (handle, "tiny.csv"),
                "fileTypeSelector": ".custom",
                "loader_code": leaky_loader,
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
    assert response.status_code == 200
    body = response.data.decode()
    assert "/srv/aidrin/private" not in body
    assert "Traceback" not in body


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
    assert "Original error" not in html  # kept in the server log only
    with client.session_transaction() as sess:
        assert not sess.get("custom_loader_spec")


RAISING_LOADER = """
def load(path, **kwargs):
    raise RuntimeError("broken loader")
"""


def _custom_upload(client, path, code, name=None):
    with open(path, "rb") as handle:
        return client.post(
            "/inspector",
            data={"file": (handle, name or path.name), "fileTypeSelector": ".custom", "loader_code": code},
            content_type="multipart/form-data",
        )


def _weird_file(tmp_path, name="data.weird"):
    path = tmp_path / name
    path.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    return path


def _loader_file(client):
    from pathlib import Path

    with client.session_transaction() as sess:
        return Path(sess["custom_loader_spec"].rsplit(":", 1)[0])


def test_web_custom_loaders_are_off_by_default(tmp_path, monkeypatch):
    from web import create_app

    monkeypatch.delenv("AIDRIN_ENABLE_WEB_CUSTOM_LOADERS", raising=False)
    assert create_app().config["ENABLE_WEB_CUSTOM_LOADERS"] is False
    monkeypatch.setenv("AIDRIN_ENABLE_WEB_CUSTOM_LOADERS", "1")
    assert create_app().config["ENABLE_WEB_CUSTOM_LOADERS"] is True


def test_disabled_custom_loaders_hide_tab_and_reject_upload(client, app, tmp_path):
    import os

    app.config["ENABLE_WEB_CUSTOM_LOADERS"] = False
    html = client.get("/inspector").get_data(as_text=True)
    assert 'id="tab-custom"' not in html
    assert 'id="custom-upload"' not in html

    response = _custom_upload(client, _weird_file(tmp_path), GOOD_LOADER)
    assert response.status_code == 403
    assert os.listdir(app.config["CUSTOM_LOADERS_FOLDER"]) == []
    assert os.listdir(app.config["UPLOAD_FOLDER"]) == []
    with client.session_transaction() as sess:
        assert not sess.get("custom_loader_spec")
        assert not sess.get("uploaded_file_path")


def test_failed_custom_upload_keeps_previous_dataset_and_loader(client, tmp_path):
    first = _weird_file(tmp_path, "first.weird")
    assert _custom_upload(client, first, GOOD_LOADER).status_code == 302
    loader_file = _loader_file(client)
    with client.session_transaction() as sess:
        before = {key: sess.get(key) for key in ("uploaded_file_path", "uploaded_file_type", "custom_loader_spec")}

    _custom_upload(client, _weird_file(tmp_path, "second.weird"), RAISING_LOADER)

    with client.session_transaction() as sess:
        assert {key: sess.get(key) for key in before} == before
        assert sess.get("upload_error")
    assert loader_file.read_text() == GOOD_LOADER.strip()
    summary = client.get("/summary-statistics").get_json()
    assert summary["success"] is True
    assert summary["records_count"] == 3


def test_each_custom_upload_gets_its_own_loader_file(client, tmp_path):
    assert _custom_upload(client, _weird_file(tmp_path, "first.weird"), GOOD_LOADER).status_code == 302
    first_loader = _loader_file(client)
    other_code = GOOD_LOADER.replace("from_custom_loader", "second_loader")
    assert _custom_upload(client, _weird_file(tmp_path, "second.weird"), other_code).status_code == 302
    second_loader = _loader_file(client)

    assert first_loader != second_loader
    assert first_loader.read_text() == GOOD_LOADER.strip()


def test_clear_removes_custom_loader_script(client, tmp_path):
    assert _custom_upload(client, _weird_file(tmp_path), GOOD_LOADER).status_code == 302
    loader_file = _loader_file(client)
    client.post("/clear")
    assert not loader_file.exists()


def test_custom_loader_errors_do_not_expose_server_paths(client, app, tmp_path, caplog):
    counter = tmp_path / "count.txt"
    flaky = (
        "import pathlib\nimport pandas as pd\n"
        f"COUNTER = pathlib.Path({str(counter)!r})\n"
        "def load(path, **kwargs):\n"
        "    calls = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(calls + 1))\n"
        "    if calls:\n"
        "        raise RuntimeError(f'read failed in file {path}')\n"
        "    return pd.read_csv(path)\n"
    )
    assert _custom_upload(client, _weird_file(tmp_path), flaky).status_code == 302
    path_echoing = "def load(path, **kwargs):\n    raise ValueError(f'not a ROOT file: {path}')\n"
    _custom_upload(client, _weird_file(tmp_path, "other.weird"), path_echoing)
    with client.session_transaction() as sess:
        upload_error = sess["upload_error"]
    feature_set = client.post("/feature-set", data={}).get_data(as_text=True)

    for body in (upload_error, feature_set):
        assert app.config["CUSTOM_LOADERS_FOLDER"] not in body
        assert app.config["UPLOAD_FOLDER"] not in body
        assert "custom_loader_" not in body
    assert upload_error.startswith("Your custom loader failed for 'other.weird'")
    assert "Your custom loader failed for 'data.weird'" in feature_set
    # The loader's own error goes to the server log, not the page.
    assert "not a ROOT file" not in upload_error
    assert "read failed" not in feature_set
    assert "not a ROOT file" in caplog.text and "read failed" in caplog.text


def test_custom_file_input_accepts_any_extension(client):
    # An accept list makes the browser picker grey out formats only a loader can read (e.g. .txt).
    html = client.get("/inspector").data.decode()
    tag = html[html.index('id="file-custom"'):]
    assert "accept=" not in tag[:tag.index(">")]
