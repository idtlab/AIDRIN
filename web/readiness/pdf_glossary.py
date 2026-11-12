"""Shim: PDF glossary lives in ``aidrin.report.pdf.pdf_glossary``.

Templates/CSS for the PDF live under ``aidrin.report.pdf`` package data.
"""

from aidrin.report.pdf import pdf_glossary as _pdf_glossary
from aidrin.report.pdf.pdf_glossary import *  # noqa: F401, F403

for _name in dir(_pdf_glossary):
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = getattr(_pdf_glossary, _name)
del _name, _pdf_glossary
