"""Exception text must stay in the server log, not in HTTP responses.

Covers the routes CodeQL flagged for py/stack-trace-exposure in web/routes/metrics.py.
"""

from unittest.mock import patch

from web.routes import metrics

SECRET = "secret-detail-/srv/aidrin/private"


def _boom(*_args, **_kwargs):
    raise ValueError(SECRET)


def _assert_hidden(response, caplog):
    assert SECRET not in response.get_data(as_text=True)
    assert SECRET in caplog.text


def test_readiness_section_hides_exception(uploaded_client, caplog):
    with patch.dict(metrics._READINESS_SECTION_BUILDERS, {"data-quality": _boom}):
        response = uploaded_client.get("/readiness-report/data-quality")
    assert response.get_json()["data"]["error"]
    _assert_hidden(response, caplog)


def test_readiness_visualizations_hide_exception(uploaded_client, caplog):
    with patch.object(metrics, "_get_or_build_readiness_visualizations", _boom):
        response = uploaded_client.get("/readiness-report/data-quality/visualizations")
    assert response.get_json()["success"] is False
    _assert_hidden(response, caplog)


def test_readiness_report_hides_exception(uploaded_client, caplog):
    with patch.object(metrics, "_get_or_build_readiness_section", _boom):
        response = uploaded_client.get("/readiness-report")
    assert response.get_json()["success"] is False
    _assert_hidden(response, caplog)


def test_readiness_pdf_hides_exception(uploaded_client, caplog):
    with patch.object(metrics, "_get_or_build_readiness_section", _boom):
        response = uploaded_client.get("/readiness-report/pdf")
    assert response.status_code == 500
    _assert_hidden(response, caplog)


def test_readiness_pdf_runtime_error_keeps_install_hint(uploaded_client, caplog):
    def _no_weasyprint(*_args, **_kwargs):
        raise RuntimeError(SECRET)

    with patch("web.readiness.pdf.build_pdf_context", _no_weasyprint):
        response = uploaded_client.get("/readiness-report/pdf")
    assert response.status_code == 500
    assert "WeasyPrint" in response.get_json()["message"]
    _assert_hidden(response, caplog)


def test_data_structure_hides_exception(uploaded_client, caplog):
    with patch.object(metrics, "kurtosis", _boom):
        response = uploaded_client.post("/data-structure?return_type=json", data={"kurtosis": "yes"})
    assert response.get_json()["error"]
    _assert_hidden(response, caplog)
