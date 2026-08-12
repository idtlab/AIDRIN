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
