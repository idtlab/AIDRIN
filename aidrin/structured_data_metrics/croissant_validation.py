"""Structural validation of Croissant JSON-LD against MLCommons' own ``mlcroissant`` library.

AIDRIN's FAIR checks in :mod:`fair_metadata` score *content* (is a license present, is a
record set documented, ...). They say nothing about whether the JSON-LD a user has hand-
edited still parses as valid Croissant -- a stray quote in an edited ``recordSet`` box, or
a value that no longer satisfies the format (e.g. ``@type`` no longer extending
``https://schema.org/Dataset``), would otherwise ship silently. This module runs the
official parser as a last check before such an edit is handed to the user.
"""

import logging
import re

_log = logging.getLogger(__name__)

_ISSUE_SECTION = re.compile(r"Found the following \d+ (error|warning)\(s\) during the validation:")
_ISSUE_BULLET = re.compile(r"^\s*-\s+(.*)$")


def _parse_validation_report(report):
    """Split mlcroissant's ``ValidationError`` message into (errors, warnings).

    The message is built by ``Issues.report()`` as one or two sections, each headed
    "Found the following N error(s)/warning(s) during the validation:" followed by
    "  -  <message>" bullets; that format is depended on here rather than re-derived,
    since the exception carries no structured data of its own.
    """
    errors, warnings = [], []
    current = errors
    for line in report.splitlines():
        section = _ISSUE_SECTION.match(line.strip())
        if section:
            current = errors if section.group(1) == "error" else warnings
            continue
        bullet = _ISSUE_BULLET.match(line)
        if bullet:
            current.append(bullet.group(1))
    return errors, warnings


def validate_croissant_jsonld(metadata):
    """Validate a Croissant document with MLCommons' own ``mlcroissant`` library.

    Parameters
    ----------
    metadata : dict
        A Croissant JSON-LD document (parsed, not a file path).

    Returns
    -------
    dict
        ``available`` is ``False`` when ``mlcroissant`` can't be imported (it is a
        required dependency, but a broken install should degrade this one check rather
        than break FAIR assessment). Otherwise ``valid`` is a bool
        and ``errors``/``warnings`` are lists of human-readable messages from the parser.
        An unexpected parser failure is reported as a fixed validation error (its details
        go to the log, not the result, so no internal error text reaches a web user)
        rather than propagating as a 500.
    """
    try:
        import mlcroissant as mlc
    except ImportError:
        return {"available": False, "valid": None, "errors": [], "warnings": []}

    from aidrin.structured_data_metrics.croissant_schema import field_guide, precheck_value
    from aidrin.structured_data_metrics.fair_metadata import _croissant_version

    try:
        guide = field_guide(_croissant_version(metadata))
    except Exception:
        # The guide reads mlcroissant internals; if a release moved one, skip the shape
        # pre-checks and let the parser itself (guarded below) judge the document.
        guide = {}
    precheck_errors = []
    for key, value in metadata.items():
        precheck_errors.extend(precheck_value(key, value, guide))
    if precheck_errors:
        # Caught before the real parser ever sees the document -- this also sidesteps
        # the RecursionError precheck_value documents (an empty nested object like
        # creator: {} crashes mlcroissant.Dataset() rather than raising a clean error).
        return {"available": True, "valid": False, "errors": precheck_errors, "warnings": []}

    try:
        dataset = mlc.Dataset(jsonld=metadata)
    except mlc.ValidationError as exc:
        errors, warnings = _parse_validation_report(str(exc))
        if not errors:
            _log.warning("mlcroissant rejected a document without itemized errors", exc_info=True)
            errors = ["mlcroissant rejected the document without listing specific errors"]
        return {"available": True, "valid": False, "errors": errors, "warnings": warnings}
    except Exception:
        _log.warning("mlcroissant failed while parsing a document", exc_info=True)
        return {
            "available": True,
            "valid": False,
            "errors": ["mlcroissant could not parse the document; check for malformed or empty nested values"],
            "warnings": [],
        }

    issues = dataset.metadata.issues
    return {"available": True, "valid": True, "errors": [], "warnings": sorted(issues.warnings)}
