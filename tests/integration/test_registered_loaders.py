"""Reusable administrator formats in ordinary uploads."""

import io
import json
from pathlib import Path

import pandas as pd
import pytest

from aidrin.file_handling.file_parser import read_file
from aidrin.file_handling.registered_loaders import read_registered_loaders
from aidrin.structured_data_metrics.completeness import completeness


@pytest.fixture
def registry(app, tmp_path):
    script = tmp_path / "loader.py"
    script.write_text(
        "import pandas as pd\n"
        "def load(path, **kwargs):\n"
        "    return pd.read_csv(path, sep=';')\n"
    )
    entries = [{"id": "household", "name": "Household power", "extensions": [".txt"], "loader": "loader.py:load"}]
    path = tmp_path / "formats.json"
    path.write_text(json.dumps(entries))
    app.config["REGISTERED_LOADERS_FILE"] = str(path)
    return path, script, entries


def upload(client, selector="registered:household", filename="power.TXT", content=b"a;b\n1;2\n3;4\n"):
    return client.post("/inspector", data={
        "file": (io.BytesIO(content), filename), "fileTypeSelector": selector,
    }, follow_redirects=True)


def test_registered_format_reuse_across_sessions(app, client, registry):
    path, script, _ = registry
    html = client.get("/inspector").get_data(as_text=True)
    assert 'value="registered:household" data-accept=".txt"' in html
    assert "Household power (.txt)" in html
    assert str(script) not in html
    for user in (client, app.test_client()):
        assert upload(user).status_code == 200
        with user.session_transaction() as sess:
            assert sess["uploaded_file_type"] == ".parquet"
            assert sess["uploaded_file_name"] == "power.TXT"
            assert "custom_loader_spec" not in sess
            saved_path = sess["uploaded_file_path"]
        # Workers can read using file_info alone, without Flask session context.
        pd.testing.assert_frame_equal(read_file((saved_path, "power.TXT", ".parquet")), pd.DataFrame({"a": [1, 3], "b": [2, 4]}))
        user.post("/clear")
        assert "Household power (.txt)" in user.get("/inspector").get_data(as_text=True)
    # Metrics continue to work after removal of the script/registration.
    upload(client)
    script.unlink()
    path.write_text("[]")
    response = client.get("/summary-statistics").get_json()
    assert response["success"] is True
    assert response["records_count"] == 2
    assert response["numerical_features"] == ["a", "b"]
    with client.session_transaction() as sess:
        file_info = (sess["uploaded_file_path"], sess["uploaded_file_name"], sess["uploaded_file_type"])
    result = completeness.run(file_info, include_visualization=False)
    assert result["Overall Completeness"] == 1.0
    assert result["Completeness scores"] == {"a": 1.0, "b": 1.0}


@pytest.mark.parametrize("selector,filename,content", [
    ("registered:missing", "data.txt", b"a;b\n1;2"),
    ("registered:household", "data.csv", b"a;b\n1;2"),
    ("registered:household", "data.txt", b""),
])
def test_failed_registered_upload_cleans_files(app, client, registry, selector, filename, content):
    response = upload(client, selector, filename, content)
    assert "Could not load the registered format" in response.get_data(as_text=True)
    assert not list(Path(app.config["UPLOAD_FOLDER"]).iterdir())
    with client.session_transaction() as sess:
        assert "uploaded_file_path" not in sess


def test_conversion_failure_preserves_previous_upload(app, client, registry, monkeypatch):
    upload(client)
    with client.session_transaction() as sess:
        previous_path = sess["uploaded_file_path"]

    def fail(frame, path, **kwargs):
        Path(path).write_bytes(b"partial")
        raise ValueError("cannot serialize")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    assert "Could not load the registered format" in upload(client).get_data(as_text=True)
    with client.session_transaction() as sess:
        assert sess["uploaded_file_path"] == previous_path
    assert list(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == [Path(previous_path)]


def test_registry_updates_removal_and_duplicate_extensions(client, registry):
    path, script, entries = registry
    # Two interpretations of a generic extension remain distinct by id and name.
    entries.append(dict(entries[0], id="other", name="Other text"))
    path.write_text(json.dumps(entries))
    assert "Other text (.txt)" in client.get("/inspector").get_data(as_text=True)
    entries[0]["name"] = "Updated power"
    path.write_text(json.dumps(entries[:1]))
    html = client.get("/inspector").get_data(as_text=True)
    assert "Updated power (.txt)" in html
    assert "Other text (.txt)" not in html
    # Listing/validation does not execute scripts.
    script.write_text("raise RuntimeError('must not execute')")
    assert read_registered_loaders(path)["household"]["name"] == "Updated power"


@pytest.mark.parametrize("entries", [
    {}, [None], [{"id": "../bad"}],
    [{"id": "valid", "name": "Name", "extensions": ".txt", "loader": "m:load"}],
    [{"id": "valid", "name": "Name", "extensions": ["txt"], "loader": "m:load"}],
    [{"id": "valid", "name": "Name", "extensions": [".txt"], "loader": "invalid"}],
])
def test_invalid_registry_rejected(tmp_path, entries):
    path = tmp_path / "formats.json"
    path.write_text(json.dumps(entries))
    with pytest.raises(ValueError):
        read_registered_loaders(path)


def test_duplicate_ids_rejected(registry):
    path, _, entries = registry
    path.write_text(json.dumps(entries * 2))
    with pytest.raises(ValueError, match="Duplicate"):
        read_registered_loaders(path)


def test_registry_persists_on_app_restart(registry, monkeypatch):
    from web import create_app

    path, _, _ = registry
    monkeypatch.setenv("AIDRIN_REGISTERED_LOADERS_FILE", str(path))
    restarted = create_app()
    assert "Household power (.txt)" in restarted.test_client().get("/inspector").get_data(as_text=True)


def test_browser_code_cannot_replace_registered_loader(client, registry):
    response = client.post("/inspector", data={
        "file": (io.BytesIO(b"a;b\n1;2"), "data.txt"),
        "fileTypeSelector": "registered:household",
        "loader_code": "raise RuntimeError('browser code executed')",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert client.get("/summary-statistics").get_json()["success"] is True
