"""Edit a Croissant document and stamp who changed it, outside the browser.

The FAIR Assessment UI lets a user edit top-level Croissant values, add missing fields
and download the result stamped with provenance (see ``_fairApplyProvenance`` in
``web/static/js/inspector.js``). This module is the same flow in Python, so the CLI,
the MCP server and the skill produce the same document the web UI would: edits land
on the file's own keys, and the provenance uses the same schema.org vocabulary.

The contributor's name and affiliation are always supplied by the person making the
edit. Nothing here invents or defaults them.
"""

import copy
import json
from datetime import datetime, timezone

from aidrin.structured_data_metrics.fair_metadata import _local_name


def _existing_key(metadata, key):
    """The key ``key`` is stored under in ``metadata`` (``sc:license`` for ``license``), else ``key``."""
    if key in metadata:
        return key
    local = _local_name(key)
    for existing in metadata:
        if _local_name(existing) == local:
            return existing
    return key


def croissant_field_status(metadata):
    """Which Croissant fields ``metadata`` has, which it lacks, and what each one expects.

    Returns ``{"available": False}`` (with an ``error`` message) when the field guide
    can't be built: ``mlcroissant`` can't be imported, or an mlcroissant release moved an
    internal the guide reads. Otherwise ``missing`` and ``present`` list one entry per top-level field
    mlcroissant's ``Metadata`` node declares, with its key, description, kind,
    cardinality, whether it has a one-value template (``addable``), the template, an
    example value (``format_hint``) and, for Person/Organization-shaped fields, the
    fields that belong inside the object (``sub_fields``).
    """
    from aidrin.structured_data_metrics.fair_metadata import _croissant_version

    try:
        from aidrin.structured_data_metrics.croissant_schema import field_guide

        guide = field_guide(_croissant_version(metadata))
    except Exception as exc:
        return {"available": False, "error": f"Croissant field guide unavailable: {exc}", "missing": [], "present": []}

    have = {_local_name(k) for k in metadata}
    missing, present = [], []
    for key, entry in guide.items():
        row = {"key": key, **entry}
        (present if key in have else missing).append(row)
    return {"available": True, "missing": missing, "present": present}


def coerce_value(key, text, guide):
    """Turn a command-line value for ``key`` into the JSON value to store.

    A value starting with ``{``, ``[`` or ``"`` is parsed as JSON (an object, a list,
    or a quoted string). Otherwise a strictly ``number`` or ``boolean`` field converts
    the text the way the web UI does; a field that also accepts text (``version``)
    and anything else stays a plain string.
    """
    stripped = text.strip()
    if stripped[:1] in ("{", "[", '"'):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key}: value looks like JSON but does not parse ({exc.msg})") from exc
    entry = guide.get(_local_name(key)) or {}
    if entry.get("allows_free_text"):
        # e.g. version is Number|Text: converting "1.10" to 1.1 would change the version.
        return text
    kind = entry.get("kind")
    if kind == "number":
        try:
            number = float(stripped)
        except ValueError:
            return text
        return int(number) if number.is_integer() and "." not in stripped else number
    if kind == "boolean":
        return stripped.lower() == "true"
    return text


def apply_croissant_edits(metadata, edits, contributor_name, contributor_affiliation=None, now=None):
    """Return a copy of ``metadata`` with ``edits`` applied and the provenance stamped.

    ``edits`` maps a top-level key to its new value. A key the file already holds under
    a prefix (``sc:license``) is written back under that prefix. The stamp matches the
    web UI: ``dateModified`` is today unless ``edits`` sets it (an explicit date wins),
    the contributor is appended to ``contributor``, and ``wasGeneratedBy`` records an
    ``UpdateAction`` by that person using AIDRIN.

    Raises ``ValueError`` when there are no edits or the contributor name is blank.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Croissant metadata must be a JSON object")
    if not edits:
        raise ValueError("No edits given: pass at least one field to change or add")
    name = (contributor_name or "").strip()
    if not name:
        raise ValueError("A contributor name is required to record who made the edit")
    affiliation = (contributor_affiliation or "").strip()

    edited = copy.deepcopy(metadata)
    for key, value in edits.items():
        edited[_existing_key(edited, key)] = copy.deepcopy(value)

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    person = {"@type": "Person", "name": name}
    if affiliation:
        person["affiliation"] = {"@type": "Organization", "name": affiliation}

    if not any(_local_name(key) == "dateModified" for key in edits):
        edited[_existing_key(edited, "dateModified")] = now.date().isoformat()
    contributor_key = _existing_key(edited, "contributor")
    existing = edited.get(contributor_key)
    contributors = [] if existing is None else (existing if isinstance(existing, list) else [existing])
    edited[contributor_key] = [*contributors, person]
    edited["wasGeneratedBy"] = {
        "@type": "UpdateAction",
        "agent": person,
        "startTime": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "instrument": {"@type": "SoftwareApplication", "name": "AIDRIN"},
    }
    return edited
