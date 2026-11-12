"""Shim: readiness PDF helpers live in ``aidrin.report.pdf`` (shared with CLI).

Templates and print CSS are packaged under ``aidrin.report.pdf`` only; do not
add copies under ``web/templates`` or ``web/static``.
"""

from aidrin.report.pdf import pdf as _pdf
from aidrin.report.pdf.pdf import *  # noqa: F401, F403

for _name in dir(_pdf):
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = getattr(_pdf, _name)
del _name, _pdf
