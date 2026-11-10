"""Integration tests for readiness report PDF export."""

from unittest.mock import MagicMock, patch


@patch("web.readiness.pdf._weasyprint")
def test_readiness_report_pdf_download(mock_weasyprint, uploaded_client):
    mock_instance = MagicMock()
    mock_instance.write_pdf.return_value = b"%PDF-1.4 test"
    mock_weasyprint.return_value = (MagicMock(return_value=mock_instance), MagicMock())

    response = uploaded_client.get("/readiness-report/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")
    content_disp = response.headers.get("Content-Disposition", "")
    assert "readiness-report-" in content_disp
    assert content_disp.endswith(".pdf")


def test_readiness_report_pdf_requires_upload(client):
    response = client.get("/readiness-report/pdf")
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False
