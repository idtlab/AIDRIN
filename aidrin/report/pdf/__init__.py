"""Readiness-report PDF context and WeasyPrint rendering (shared by web + CLI)."""

from aidrin.report.pdf.pdf import (
    FootnoteRegistry,
    build_pdf_context,
    pdf_filename,
    readiness_pdf_logo_uri,
    render_readiness_report_pdf,
)

__all__ = [
    "FootnoteRegistry",
    "build_pdf_context",
    "pdf_filename",
    "readiness_pdf_logo_uri",
    "render_readiness_report_pdf",
]
