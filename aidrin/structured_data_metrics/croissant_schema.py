"""What a Croissant field means and what shape it expects, read from mlcroissant itself.

Every node class in mlcroissant (``Metadata``, ``Person``, ``Organization``, ...)
declares its fields with a ``jsonld_field(description=..., input_types=..., ...)``
wrapper -- real text and typing written by MLCommons, not AIDRIN. This module walks
those declarations instead of hand-authoring a second copy, so the "add this missing
field" guidance in the FAIR Assessment UI tracks whatever mlcroissant ships: a wording
change or a new field in a future release shows up here with no edit on AIDRIN's side.
"""

from datetime import date
from urllib.parse import urlparse
import re

from aidrin.structured_data_metrics.fair_metadata import _local_name

# Node classes simple enough to offer a one-box "add" for (name/description/url/email,
# nothing structural). FileObject, FileSet and RecordSet describe the dataset's own
# layout -- there's no sensible one-line template for those, so fields typed with them
# fall back to the plain "Missing" badge instead of an add affordance.
_SIMPLE_NODE_NAMES = {"Person", "Organization", "CreativeWork"}

_ISO_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)


def _format_example(kind):
    """One example value for a scalar kind -- shown as the edit box's placeholder (ghost
    text, never submitted as real content) and reused verbatim in precheck_value's error
    message, so what the UI hints at and what the validator complains about never drift
    apart. "date" is always today's actual date, so it's never a stale-looking example;
    "url" uses example.org, the domain IANA reserves for exactly this purpose (RFC 2606)
    -- not a real organization's URL."""
    if kind == "date":
        return date.today().isoformat()
    if kind == "url":
        return "https://example.org/dataset"
    return None


def _scalar_kind_by_type():
    # Imported lazily (see field_guide) so this module doesn't hard-require mlcroissant
    # at import time; callers that only need precheck_value for a field already known to
    # be e.g. "date" never need this map built at all.
    from rdflib.namespace import SDO

    return {
        SDO.Date: "date",
        SDO.DateTime: "date",
        SDO.URL: "url",
        SDO.Integer: "number",
        SDO.Number: "number",
        SDO.Boolean: "boolean",
        SDO.Text: "text",
    }


def _resolve_key(field, ctx):
    """The JSON-LD key a field is read under (e.g. "dateModified"), from its declared
    schema.org/Croissant URL -- some (like citeAs) resolve through a version-dependent
    function rather than a plain URIRef, hence calling call_url(ctx)."""
    url = field.call_url(ctx)
    return str(url).rstrip("/").rsplit("/", 1)[-1]


def _classify(field, kind_by_type):
    """(kind, node_class_names, allows_free_text) for one field, from its declared
    input_types. A field can accept several shapes at once (e.g. license: CreativeWork |
    Text | URL) -- a scalar shape wins when one is available, since it's the simpler
    thing to fill in and, for license specifically, is also what the field's own
    description recommends ("the URL of a known license"). Pure node_names
    (creator/publisher: Organization | Person only, no scalar alternative) fall through
    to "node". ``allows_free_text`` records whether plain text is *also* explicitly
    declared acceptable alongside a stricter kind (license is; url and dateModified
    aren't) -- precheck_value uses it to only enforce a strict shape where the field's
    own declaration doesn't already carve out a free-text escape hatch."""
    scalar_kinds = {kind_by_type[t] for t in field.input_types if t in kind_by_type}
    allows_free_text = "text" in scalar_kinds
    for preferred in ("date", "url", "number", "boolean", "text"):
        if preferred in scalar_kinds:
            return preferred, [], allows_free_text
    node_names = [t.__name__ for t in field.input_types if isinstance(t, type)]
    if node_names:
        return "node", node_names, allows_free_text
    return "text", [], allows_free_text


def _template_for(kind, node_names, many):
    if kind == "node":
        simple = [n for n in node_names if n in _SIMPLE_NODE_NAMES]
        if not simple:
            return None
        one = {"@type": simple[0]}
    else:
        one = ""
    return [one] if many else one


def _node_classes_by_name():
    from mlcroissant._src.structure_graph.nodes.creative_work import CreativeWork
    from mlcroissant._src.structure_graph.nodes.organization import Organization
    from mlcroissant._src.structure_graph.nodes.person import Person

    return {"Person": Person, "Organization": Organization, "CreativeWork": CreativeWork}


def _sub_fields(node_names, jsonld_fields_fn, ctx):
    """The fillable fields of a node type (e.g. Organization's name/description/email/url),
    each with mlcroissant's own description -- what a "+ Add" box for a node-shaped field
    (creator, publisher, license, ...) shows the user instead of leaving them to guess
    what belongs inside ``{"@type": "Organization"}``. Fields are deduped by key across
    every type the parent field accepts (Organization and Person share the same four),
    keeping the first description seen."""
    classes = _node_classes_by_name()
    seen = {}
    for name in node_names:
        cls = classes.get(name)
        if cls is None:
            continue
        for f in jsonld_fields_fn(cls):
            try:
                key = _resolve_key(f, ctx)
            except Exception:
                continue
            if key not in seen:
                seen[key] = {"key": key, "description": f.description or ""}
    return list(seen.values())


def _context_for(version):
    """An mlcroissant ``Context`` for a declared Croissant version ("1.0", "1.1", ...).

    Some keys resolve through a version-dependent function (see ``_resolve_key``), so the
    guide is built for the version the document declares. An undeclared or unknown version
    falls back to 1.0, the oldest release mlcroissant still reads as current.
    """
    from mlcroissant._src.core.context import Context, CroissantVersion

    try:
        conforms_to = CroissantVersion(f"http://mlcommons.org/croissant/{version}")
    except ValueError:
        conforms_to = CroissantVersion.V_1_0
    return Context(conforms_to=conforms_to)


def field_guide(version=None):
    """``{json_key: {description, cardinality, kind, node_types, addable, template,
    format_hint, sub_fields}}`` for every top-level field mlcroissant's ``Metadata`` node
    declares, for Croissant ``version`` (e.g. ``"1.1"``; ``None`` means 1.0).

    ``addable`` is False for fields whose shape isn't a reasonable one-box fill-in
    (recordSet, distribution, ...); the FAIR Assessment UI should fall back to a plain
    "Missing" indicator for those rather than offering to add them here. ``format_hint``
    (date/url fields only) is an example value to show as the edit box's placeholder --
    not real content, just a ghost-text format cue. ``sub_fields`` (node-shaped fields
    only) lists the node type's own fillable fields, so "+ Add" on e.g. ``publisher``
    can tell the user what belongs inside the JSON object rather than leaving them
    looking at a bare ``{"@type": "Organization"}``. This reads mlcroissant's private
    ``_src`` modules, so it can raise ``ImportError`` (mlcroissant can't be imported) or
    another exception (an mlcroissant release moved an internal); callers should catch
    ``Exception`` and degrade rather than fail.
    """
    from mlcroissant._src.core.dataclasses import jsonld_fields
    from mlcroissant._src.structure_graph.nodes.metadata import Metadata

    ctx = _context_for(version)
    kind_by_type = _scalar_kind_by_type()
    guide = {}
    for f in jsonld_fields(Metadata):
        try:
            key = _resolve_key(f, ctx)
        except Exception:
            continue
        kind, node_names, allows_free_text = _classify(f, kind_by_type)
        many = f.cardinality == "MANY"
        template = _template_for(kind, node_names, many)
        simple_node_names = [n for n in node_names if n in _SIMPLE_NODE_NAMES]
        guide[key] = {
            "description": f.description or "",
            "cardinality": f.cardinality,
            "kind": kind,
            "node_types": node_names,
            "allows_free_text": allows_free_text,
            "addable": template is not None,
            "template": template,
            "format_hint": _format_example(kind),
            "sub_fields": _sub_fields(simple_node_names, jsonld_fields, ctx) if simple_node_names else [],
        }
    return guide


def precheck_value(key, value, guide):
    """Shape checks for one top-level value, sourced from the same field guide used for
    the UI hints -- run before handing a document to mlcroissant.Dataset() so a bad
    shape gets a specific, field-attributed message instead of (or in addition to)
    whatever the parser itself reports. This also sidesteps a real mlcroissant bug found
    while building this: an empty nested object (e.g. ``creator: {}``) raises a
    ``RecursionError`` inside the parser rather than a clean validation error; rejecting
    an empty object here means that input never reaches it.

    ``key`` is the document's own spelling; a prefixed key (``sc:creator``) is looked up
    by its local name, so Croissant files written with ``sc:`` prefixes are checked too.
    """
    entry = guide.get(key) or guide.get(_local_name(key))
    if entry is None:
        return []
    kind = entry["kind"]
    many = entry["cardinality"] == "MANY"
    # A strict shape (date/url) is only enforced when the field's own declared types
    # don't also allow plain text -- license declares CreativeWork|Text|URL, so a bare
    # string like "Public" is legitimate there, not just something mlcroissant happens
    # not to catch.
    strict = not entry["allows_free_text"]
    values = value if (many and isinstance(value, list)) else [value]
    errors = []
    for v in values:
        if kind == "date" and strict and isinstance(v, str) and v and not _ISO_DATE.match(v):
            errors.append(f"{key}: dates should follow ISO 8601 (e.g. {_format_example('date')}), got {v!r}")
        elif kind == "url" and strict and isinstance(v, str) and v:
            parsed = urlparse(v)
            if not (parsed.scheme and parsed.netloc):
                errors.append(f"{key}: expected a full URL (e.g. {_format_example('url')}), got {v!r}")
        elif kind == "node" and v not in (None, ""):
            if not isinstance(v, dict) or not any(v.values()):
                errors.append(
                    f'{key}: expected an object like {{"@type": "Organization", "name": "..."}}, got {v!r}'
                )
    return errors
