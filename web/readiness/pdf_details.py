"""Shim: PDF detail builders live in ``aidrin.report.pdf.pdf_details``."""

from aidrin.report.pdf import pdf_details as _pdf_details
from aidrin.report.pdf.pdf_details import *  # noqa: F401, F403

# Re-export underscore helpers for tests (star-import skips leading underscores).
for _name in dir(_pdf_details):
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = getattr(_pdf_details, _name)
del _name, _pdf_details
