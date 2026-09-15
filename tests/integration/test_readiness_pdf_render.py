"""Renders a readiness report PDF for real, without mocking WeasyPrint.

Every other PDF test patches ``web.readiness.pdf._weasyprint``, which keeps them
fast and portable but means WeasyPrint itself is never exercised. A WeasyPrint
upgrade can therefore go green in CI while the rendered document is broken.

These tests close that gap. They need WeasyPrint's native libraries (Pango,
cairo, glib), so they skip cleanly where those are absent and run in the
dedicated ``pdf_render`` CI job that installs them.

The assertions target what actually breaks in practice. WeasyPrint does not
raise when it cannot fetch an image or a stylesheet -- it logs and carries on
rendering without them. So a test that only checked "some PDF bytes came back"
would still pass with the header logo silently missing. Hence the checks on
extracted text, embedded images, and the WeasyPrint logger.
"""

import io
import logging

import pytest

pypdf = pytest.importorskip("pypdf", reason="pypdf is needed to inspect the rendered PDF")


def _weasyprint_renderable():
    """True when WeasyPrint can actually load, not merely import.

    The Python package imports fine without its native libraries; the failure
    only appears when the CFFI bindings are loaded. web.readiness.pdf._weasyprint
    is the same hook the application uses, so this mirrors production exactly.
    """
    try:
        from web.readiness.pdf import _weasyprint

        _weasyprint()
        return True
    except Exception:  # noqa: BLE001 - any failure means we cannot render here
        return False


needs_weasyprint = pytest.mark.skipif(
    not _weasyprint_renderable(),
    reason="WeasyPrint native libraries (Pango/cairo/glib) not available",
)

pytestmark = [pytest.mark.pdf_render, needs_weasyprint]


@pytest.fixture
def rendered_pdf(uploaded_client, caplog):
    """Render the report through the real HTTP route and capture WeasyPrint logs."""
    with caplog.at_level(logging.WARNING, logger="weasyprint"):
        response = uploaded_client.get("/readiness-report/pdf")
    assert response.status_code == 200, response.data[:400]
    assert response.mimetype == "application/pdf"
    return response.data, caplog


def test_rendered_pdf_is_a_real_document(rendered_pdf):
    """A genuine multi-object PDF, not a stub or an error page."""
    data, _ = rendered_pdf
    assert data.startswith(b"%PDF-")
    reader = pypdf.PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 1
    # A blank page is a valid PDF, so prove the HTML actually laid out.
    assert len(data) > 5000, "suspiciously small for a rendered report"


def test_rendered_pdf_contains_the_report_text(rendered_pdf):
    """Text extraction proves the template rendered rather than failing silently."""
    data, _ = rendered_pdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "AI Data Readiness Report" in text, text[:500]


def test_rendered_pdf_embeds_the_logo(rendered_pdf):
    """The header/footer logo reaches the document.

    This is the assertion that catches a regression in image fetching. The logo
    is resolved through a custom url_fetcher over a file:// URI, so a change in
    how WeasyPrint selects its fetcher drops the image without raising. Nothing
    else in the suite would notice.
    """
    data, _ = rendered_pdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    assert any(page.images for page in reader.pages), (
        "no embedded images in the rendered PDF - the logo or charts were dropped"
    )


def test_rendering_logs_no_weasyprint_warnings(rendered_pdf):
    """WeasyPrint logs missing resources instead of raising, so treat that as failure."""
    _, caplog = rendered_pdf
    problems = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("weasyprint") and record.levelno >= logging.WARNING
    ]
    assert not problems, f"WeasyPrint reported problems while rendering: {problems}"
