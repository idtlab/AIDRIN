"""FAIR compliance of a dataset's metadata file, scored per metadata standard.

Each standard is a *profile*: for every FAIR principle, a mapping of check label to a
check function. A check returns a short, displayable summary of what it found, or
``None`` when the metadata does not satisfy it. Dataset-level checks look at top-level
keys only, so a nested ``distribution[].title`` can never stand in for the dataset title.
"""

import base64
import io
import json
import re

import matplotlib.pyplot as plt

FAILED = "CHECK FAILED ❌"
PRINCIPLES = ("Findable", "Accessible", "Interoperable", "Reusable")
_MAX_LISTED = 5


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _present(value):
    return value not in (None, "", [], {})


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _local_name(key):
    """``dct:title`` and ``http://purl.org/dc/terms/title`` both become ``title``."""
    if key.startswith("@"):
        return key
    return re.split(r"[:/#]", key)[-1] or key


def _top_level(metadata):
    keys = {}
    for key, value in metadata.items():
        keys.setdefault(_local_name(key), value)
    return keys


def _summary(value):
    """Reduce a metadata value to one displayable scalar."""
    if isinstance(value, dict):
        for name in ("name", "fn", "title", "@id"):
            if isinstance(value.get(name), (str, int, float)):
                return value[name]
        return f"{len(value)} fields"
    if isinstance(value, list):
        items = [v for v in value if _present(v)]
        if items and all(isinstance(v, (str, int, float)) for v in items):
            shown = ", ".join(str(v) for v in items[:_MAX_LISTED])
            more = len(items) - _MAX_LISTED
            return f"{shown} (+{more} more)" if more > 0 else shown
        first = _summary(items[0]) if items else ""
        return f"{first} (+{len(items) - 1} more)" if len(items) > 1 else first
    return value


# ---------------------------------------------------------------------------
# Check builders
# ---------------------------------------------------------------------------

def _reads(*names):
    """Record which top-level keys a check reads, so the rest can go under ``Other``."""
    def mark(check):
        check.reads = names
        return check
    return mark


def key(*names):
    """Passes when any of the top-level keys is present."""
    @_reads(*names)
    def check(meta):
        for name in names:
            if _present(meta.get(name)):
                return _summary(meta[name])
        return None
    return check


def in_each(parent, child, noun):
    """Passes when at least one entry of the ``parent`` list carries ``child`` (or one of a tuple)."""
    children = child if isinstance(child, tuple) else (child,)

    @_reads(parent)
    def check(meta):
        entries = [e for e in _as_list(meta.get(parent)) if isinstance(e, dict)]
        found = sum(1 for e in entries if any(_present(e.get(c)) for c in children))
        return f"{found}/{len(entries)} {noun}" if found else None
    return check


def entry_where(parent, predicate, describe):
    """Passes when an entry of the ``parent`` list satisfies ``predicate``."""
    @_reads(parent)
    def check(meta):
        for entry in _as_list(meta.get(parent)):
            if isinstance(entry, dict) and predicate(entry):
                return describe(entry)
        return None
    return check


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

# DCAT-US 1.1 (Project Open Data). Keys a dataset carries on its distributions are
# checked there; the rest are top-level only.
DCAT_US_1_1 = {
    "Findable": {
        "identifier": key("identifier"),
        "title": key("title"),
        "description": key("description"),
        "keyword": key("keyword"),
        "theme": key("theme"),
        "landingPage": key("landingPage"),
    },
    "Accessible": {
        "accessLevel": key("accessLevel"),
        "downloadURL (distribution)": in_each("distribution", "downloadURL", "distributions"),
        "mediaType (distribution)": in_each("distribution", "mediaType", "distributions"),
        "accessURL (distribution)": in_each("distribution", "accessURL", "distributions"),
        "issued": key("issued"),
        "modified": key("modified"),
    },
    "Interoperable": {
        "conformsTo": key("conformsTo"),
        "references": key("references"),
        "language": key("language"),
        "format (distribution)": in_each("distribution", "format", "distributions"),
        "spatial": key("spatial"),
        "temporal": key("temporal"),
    },
    "Reusable": {
        "license": key("license"),
        "rights": key("rights"),
        "publisher": key("publisher"),
        "description": key("description"),
        "format (distribution)": in_each("distribution", "format", "distributions"),
        "programCode": key("programCode"),
        "bureauCode": key("bureauCode"),
        "contactPoint": key("contactPoint"),
    },
}


# DCAT-US 3.0 (GSA, JSON Schema with plain keys; dataset requires title, description,
# contactPoint and identifier). License may sit on the dataset or on its distributions.
@_reads("license", "distribution")
def _dcat_us_3_license(meta):
    return key("license")(meta) or in_each("distribution", "license", "distributions")(meta)


DCAT_US_3 = {
    "Findable": {
        "identifier": key("identifier"),
        "title": key("title"),
        "description": key("description"),
        "keyword": key("keyword"),
        "theme": key("theme"),
        "landingPage": key("landingPage"),
    },
    "Accessible": {
        "accessRights": key("accessRights"),
        "accessURL or downloadURL (distribution)": in_each("distribution", ("accessURL", "downloadURL"), "distributions"),
        "mediaType (distribution)": in_each("distribution", "mediaType", "distributions"),
        "issued": key("issued"),
        "modified": key("modified"),
    },
    "Interoperable": {
        "conformsTo": key("conformsTo"),
        "format (distribution)": in_each("distribution", "format", "distributions"),
        "spatial": key("spatial"),
        "temporal": key("temporal"),
        "qualifiedRelation": key("qualifiedRelation"),
    },
    "Reusable": {
        "license (dataset or distribution)": _dcat_us_3_license,
        "rights": key("rights"),
        "publisher": key("publisher"),
        "contactPoint": key("contactPoint"),
        "version": key("version"),
        "provenance (wasGeneratedBy or provenance)": key("wasGeneratedBy", "provenance"),
        "checksum (distribution)": in_each("distribution", "checksum", "distributions"),
    },
}
DCAT_US_3_REQUIRED = ("title", "description", "contactPoint", "identifier")

_ACCESS_RIGHTS = "info:eu-repo/semantics/"


def _is_access_rights(entry):
    return str(entry.get("rightsUri", "")).startswith(_ACCESS_RIGHTS)


@_reads("doi", "identifiers")
def _doi(meta):
    if _present(meta.get("doi")):
        return meta["doi"]
    for entry in _as_list(meta.get("identifiers")):
        if isinstance(entry, dict) and str(entry.get("identifierType", "")).upper() == "DOI":
            return entry.get("identifier")
    return None


@_reads("types")
def _resource_type_general(meta):
    types = meta.get("types")
    return types.get("resourceTypeGeneral") if isinstance(types, dict) else None


# DataCite Metadata Schema 4.x (checked against 4.7). The mapping follows F-UJI's
# DATACITE_JSON_MAPPING and Habermann (2024), doi:10.5281/zenodo.12168626, since
# DataCite publishes no FAIR mapping of its own.
DATACITE_4 = {
    "Findable": {
        "identifier (DOI)": _doi,
        "creators": key("creators"),
        "titles": key("titles"),
        "publisher": key("publisher"),
        "publicationYear": key("publicationYear"),
        "subjects": key("subjects"),
        "descriptions (Abstract)": entry_where(
            "descriptions", lambda e: e.get("descriptionType") == "Abstract", lambda e: "Abstract"
        ),
        "alternateIdentifiers": key("alternateIdentifiers"),
    },
    "Accessible": {
        "url or contentUrl": key("url", "contentUrl"),
        "access rights (rightsList)": entry_where("rightsList", _is_access_rights, lambda e: e["rightsUri"]),
    },
    "Interoperable": {
        "types.resourceTypeGeneral": _resource_type_general,
        "relatedIdentifiers with relationType": in_each("relatedIdentifiers", "relationType", "related identifiers"),
        "subjects with valueUri": in_each("subjects", "valueUri", "subjects"),
        "language": key("language"),
    },
    "Reusable": {
        "license (rightsList rightsUri)": entry_where(
            "rightsList",
            lambda e: _present(e.get("rightsUri")) and not _is_access_rights(e),
            lambda e: e.get("rights") or e["rightsUri"],
        ),
        "contributors": key("contributors"),
        "fundingReferences": key("fundingReferences"),
        "dates": key("dates"),
        "version": key("version"),
        "formats": key("formats"),
        "sizes": key("sizes"),
        "relatedItems": key("relatedItems"),
    },
}

DATACITE_MANDATORY = {
    "Identifier": _doi,
    "Creator": key("creators"),
    "Title": key("titles"),
    "Publisher": key("publisher"),
    "PublicationYear": key("publicationYear"),
    "ResourceType": _resource_type_general,
}

# Properties of the DataCite schema as they appear in DataCite JSON. Anything else in a
# REST API response (xml, viewsOverTime, citationCount, state, ...) is bookkeeping.
DATACITE_PROPERTIES = (
    "doi", "identifiers", "alternateIdentifiers", "creators", "titles", "publisher",
    "publicationYear", "types", "subjects", "contributors", "dates", "language",
    "relatedIdentifiers", "relatedItems", "sizes", "formats", "version", "rightsList",
    "descriptions", "geoLocations", "fundingReferences", "schemaVersion", "url", "contentUrl",
)

_STRING_FORM = "not assessable (string form; request the record with ?affiliation=true&publisher=true)"


def _ratio(found, total, noun):
    return f"{found}/{total} {noun}" if total else f"no {noun} listed"


def _datacite_structure(meta):
    people = [p for p in _as_list(meta.get("creators")) + _as_list(meta.get("contributors")) if isinstance(p, dict)]
    creators = [p for p in _as_list(meta.get("creators")) if isinstance(p, dict)]
    orcid = sum(
        1 for p in creators
        if any(isinstance(n, dict) and str(n.get("nameIdentifierScheme", "")).upper() == "ORCID"
               for n in _as_list(p.get("nameIdentifiers")))
    )
    affiliations = [a for p in people for a in _as_list(p.get("affiliation"))]
    if any(isinstance(a, str) for a in affiliations):
        ror = _STRING_FORM
    else:
        ror = _ratio(
            sum(1 for a in affiliations if str(a.get("affiliationIdentifierScheme", "")).upper() == "ROR"),
            len(affiliations), "affiliations",
        )
    publisher = meta.get("publisher")
    if isinstance(publisher, dict):
        publisher_id = "yes" if _present(publisher.get("publisherIdentifier")) else "no"
    else:
        publisher_id = _STRING_FORM if _present(publisher) else "no publisher"
    subjects = [s for s in _as_list(meta.get("subjects")) if isinstance(s, dict)]
    funders = [f for f in _as_list(meta.get("fundingReferences")) if isinstance(f, dict)]
    return {
        "Creators with ORCID": _ratio(orcid, len(creators), "creators"),
        "Affiliations with ROR": ror,
        "Publisher identifier": publisher_id,
        "Subjects with valueUri": _ratio(sum(1 for s in subjects if _present(s.get("valueUri"))), len(subjects), "subjects"),
        "Funders with funderIdentifier": _ratio(
            sum(1 for f in funders if _present(f.get("funderIdentifier"))), len(funders), "funders"
        ),
    }


# MLCommons Croissant 1.0 / 1.1 (JSON-LD on schema.org). Keys are matched by their local
# name, so "dct:conformsTo" and "conformsTo", or "rai:dataBiases" and "dataBiases", agree.
@_reads("recordSet")
def _croissant_field_types(meta):
    fields = [
        f for rs in _as_list(meta.get("recordSet")) if isinstance(rs, dict)
        for f in _as_list(rs.get("field")) if isinstance(f, dict)
    ]
    typed = sum(1 for f in fields if _present(f.get("dataType")))
    return f"{typed}/{len(fields)} fields" if typed else None


CROISSANT = {
    "Findable": {
        "name": key("name"),
        "description": key("description"),
        "keywords": key("keywords"),
        "url": key("url"),
        "identifier or sameAs": key("identifier", "sameAs"),
        "version": key("version"),
        "citeAs": key("citeAs", "citation"),
    },
    "Accessible": {
        "isAccessibleForFree or conditionsOfAccess": key("isAccessibleForFree", "conditionsOfAccess"),
        "contentUrl (distribution)": in_each("distribution", "contentUrl", "distributions"),
        "encodingFormat (distribution)": in_each("distribution", "encodingFormat", "distributions"),
    },
    "Interoperable": {
        "conformsTo": key("conformsTo"),
        "@context": key("@context"),
        "recordSet": key("recordSet"),
    },
    "Reusable": {
        "license": key("license"),
        "creator": key("creator"),
        "publisher": key("publisher"),
        "datePublished": key("datePublished"),
        "dateModified": key("dateModified"),
        "provenance (wasDerivedFrom or wasGeneratedBy)": key("wasDerivedFrom", "wasGeneratedBy"),
        "dataType (recordSet fields)": _croissant_field_types,
    },
}

# The properties Croissant 1.0 and 1.1 require of a dataset.
CROISSANT_REQUIRED = (
    "@context", "@type", "conformsTo", "name", "description", "license", "url", "creator", "datePublished",
)

# Croissant RAI 1.0 (croissant_rai.ttl), grouped by what each property documents.
# Reported, never scored: the values are free text AIDRIN cannot verify.
CROISSANT_RAI = {
    "Data life cycle": (
        "dataCollection", "dataCollectionType", "dataCollectionMissingData", "dataCollectionRawData",
        "dataCollectionTimeframe", "dataPreprocessingProtocol", "dataImputationProtocol",
        "dataManipulationProtocol", "dataReleaseMaintenancePlan",
    ),
    "Data labeling": (
        "dataAnnotationProtocol", "dataAnnotationPlatform", "dataAnnotationAnalysis", "annotationsPerItem",
        "annotatorDemographics", "machineAnnotationTools",
    ),
    "Safety and fairness": (
        "dataLimitations", "dataBiases", "dataSocialImpact", "dataUseCases", "personalSensitiveInformation",
    ),
}
_NOT_DECLARED = "Not declared"


def _croissant_conformance(meta):
    missing = [k for k in CROISSANT_REQUIRED if not _present(meta.get(k))]
    if "@type" not in missing and "Dataset" not in {_local_name(str(t)) for t in _as_list(meta["@type"])}:
        missing.append("@type")
    return {
        "Required properties present": f"{len(CROISSANT_REQUIRED) - len(missing)}/{len(CROISSANT_REQUIRED)}",
        "Missing": ", ".join(missing) or "none",
    }


def _croissant_structure(meta):
    files = [
        d for d in _as_list(meta.get("distribution"))
        if isinstance(d, dict) and "FileObject" in {_local_name(str(t)) for t in _as_list(d.get("@type"))}
    ]
    record_sets = [rs for rs in _as_list(meta.get("recordSet")) if isinstance(rs, dict)]
    fields = [f for rs in record_sets for f in _as_list(rs.get("field")) if isinstance(f, dict)]
    return {
        "FileObjects with a checksum (sha256 or md5)": _ratio(
            sum(1 for d in files if _present(d.get("sha256")) or _present(d.get("md5"))), len(files), "FileObjects"
        ),
        "Fields with dataType": _ratio(sum(1 for f in fields if _present(f.get("dataType"))), len(fields), "fields"),
        "RecordSets with a key": _ratio(sum(1 for rs in record_sets if _present(rs.get("key"))), len(record_sets), "RecordSets"),
    }


def _croissant_rai(meta):
    return {
        group: {prop: _summary(meta[prop]) if _present(meta.get(prop)) else _NOT_DECLARED for prop in props}
        for group, props in CROISSANT_RAI.items()
    }


# RO-Crate 1.2 (ro-crate-metadata.json, JSON-LD on schema.org). Checks run on the root
# data entity, found through the metadata descriptor's "about" as the spec prescribes.
_ROCRATE_DESCRIPTORS = ("ro-crate-metadata.json", "ro-crate-metadata.jsonld")
_ROCRATE_URI = re.compile(r"w3id\.org/ro/crate/(\d+\.\d+(?:-DRAFT)?)")
_ISO_8601 = re.compile(r"^\d{4}(-\d{2}){0,2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
_LOCAL_CRATE = "not applicable to a local crate (relative root @id)"


def _types(entity):
    return {_local_name(str(t)) for t in _as_list(entity.get("@type"))}


def _ref_id(value):
    return value.get("@id") if isinstance(value, dict) else value


class _Crate:
    """An RO-Crate's @graph, with its descriptor and root data entity resolved."""

    def __init__(self, metadata):
        self.graph = [e for e in _as_list(metadata.get("@graph")) if isinstance(e, dict)]
        by_id = {e.get("@id"): e for e in self.graph}
        self.descriptor = next((by_id[d] for d in _ROCRATE_DESCRIPTORS if d in by_id), {})
        self.root = by_id.get(_ref_id(self.descriptor.get("about")), {})
        self.local = not re.match(r"^[a-z][a-z0-9+.-]*:", str(self.root.get("@id", "./")))

    def of_type(self, name):
        return [e for e in self.graph if name in _types(e)]

    def version(self):
        for value in _as_list(self.descriptor.get("conformsTo")):
            match = _ROCRATE_URI.search(str(_ref_id(value)))
            if match:
                return match.group(1)
        return None


def _rocrate_profile(crate):
    """FAIR checks for one crate; web-only checks are left out for local crates."""
    files = crate.of_type("File")

    def files_with(prop):
        @_reads()
        def check(_meta):
            found = sum(1 for f in files if _present(f.get(prop)))
            return f"{found}/{len(files)} Files" if found else None
        return check

    def descriptor_version(_meta):
        version = crate.version()
        return f"RO-Crate {version}" if version else None

    def provenance(_meta):
        actions = [a for a in crate.of_type("CreateAction") + crate.of_type("UpdateAction") if _present(a.get("object"))]
        return f"{len(actions)} actions" if actions else None

    accessible = {"conditionsOfAccess": key("conditionsOfAccess")}
    if not crate.local:
        accessible["url or distribution"] = key("url", "distribution")
        accessible["contentUrl (Files)"] = files_with("contentUrl")
    return {
        "Findable": {
            "name": key("name"),
            "description": key("description"),
            "identifier or cite-as": key("identifier", "cite-as"),
            "keywords": key("keywords"),
        },
        "Accessible": accessible,
        "Interoperable": {
            "conformsTo (metadata descriptor)": _reads()(descriptor_version),
            "conformsTo (profiles on the root)": key("conformsTo"),
            "encodingFormat (Files)": files_with("encodingFormat"),
        },
        "Reusable": {
            "license": key("license"),
            "author": key("author"),
            "publisher": key("publisher"),
            "funder": key("funder"),
            "datePublished": key("datePublished"),
            "provenance (CreateAction or UpdateAction)": _reads()(provenance),
        },
    }


def _rocrate_conformance(crate):
    root, descriptor = crate.root, crate.descriptor
    must = {
        "metadata descriptor (CreativeWork)": "CreativeWork" in _types(descriptor),
        "root data entity found through about": bool(root),
        "root @type includes Dataset": "Dataset" in _types(root),
        "datePublished is one ISO 8601 date": isinstance(root.get("datePublished"), str)
        and bool(_ISO_8601.match(root["datePublished"])),
    }
    should = {
        "descriptor conformsTo a versioned RO-Crate": crate.version() is not None,
        "root name": _present(root.get("name")),
        "root description": _present(root.get("description")),
        "root license": _present(root.get("license")),
    }
    if str(_ref_id(root.get("identifier")) or "").startswith(("https://doi.org/", "http://doi.org/", "doi:")):
        should["cite-as for a persistent identifier"] = _present(root.get("cite-as"))
    return {
        "Required (MUST) present": f"{sum(must.values())}/{len(must)}",
        "Missing (MUST)": ", ".join(k for k, ok in must.items() if not ok) or "none",
        "Recommended (SHOULD) present": f"{sum(should.values())}/{len(should)}",
        "Missing (SHOULD)": ", ".join(k for k, ok in should.items() if not ok) or "none",
    }


def _rocrate_structure(crate):
    files = crate.of_type("File")
    people = crate.of_type("Person")
    orgs = crate.of_type("Organization")
    actions = crate.of_type("CreateAction") + crate.of_type("UpdateAction")
    return {
        "Files with encodingFormat and contentSize": _ratio(
            sum(1 for f in files if _present(f.get("encodingFormat")) and _present(f.get("contentSize"))), len(files), "Files"
        ),
        "People with an ORCID": _ratio(
            sum(1 for p in people if str(p.get("@id", "")).startswith("https://orcid.org/")), len(people), "people"
        ),
        "Organizations with a ROR": _ratio(
            sum(1 for o in orgs if str(o.get("@id", "")).startswith("https://ror.org/")), len(orgs), "organizations"
        ),
        "Actions with agent and instrument": _ratio(
            sum(1 for a in actions if _present(a.get("agent")) and _present(a.get("instrument"))), len(actions), "actions"
        ),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score(meta, profile):
    results, passed = {}, {}
    for principle in PRINCIPLES:
        checks = profile[principle]
        results[principle] = {}
        for label, check in checks.items():
            value = check(meta)
            results[principle][label] = FAILED if value is None else value
        passed[principle] = sum(1 for v in results[principle].values() if v != FAILED)
    totals = {p: len(profile[p]) for p in PRINCIPLES}
    summary = {f"{p} Checks": f"{passed[p]}/{totals[p]}" for p in PRINCIPLES}
    summary["Total Checks"] = f"{sum(passed.values())}/{sum(totals.values())}"
    return results, summary, passed, totals


def _other(meta, profile, shown_elsewhere=()):
    """Top-level keys no check looked at, summarised; subtrees stay in Original Metadata."""
    used = {name for p in PRINCIPLES for check in profile[p].values() for name in check.reads}
    skip = used | {"distribution", "recordSet"} | set(shown_elsewhere)
    return {k: _summary(v) for k, v in meta.items() if k not in skip and _present(v)}


def _chart(passed, totals):
    total_passed, total_expected = sum(passed.values()), sum(totals.values())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6, 2.5), gridspec_kw={"width_ratios": [1, 2], "wspace": 0.6})
    ax1.pie(
        [total_passed, max(0, total_expected - total_passed)],
        labels=["Pass", "Fail"],
        colors=["#4485F4", "#e5e7eb"],
        autopct="%1.1f%%",
        startangle=90,
        textprops={"fontsize": 10, "color": "#6b7280"},
    )
    ax1.axis("equal")

    labels = list(PRINCIPLES)
    percentages = [passed[p] / totals[p] * 100 if totals[p] else 0 for p in labels]
    bars = ax2.barh(labels, percentages, color=["#3b82f6", "#22c55e", "#eab308", "#f97316"], height=0.5)
    for bar, p in zip(bars, labels):
        ax2.text(
            bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, f"{passed[p]}/{totals[p]}",
            va="center", fontsize=9, color="#6b7280",
        )
    ax2.set_xlim(0, 110)
    ax2.set_xticks([])
    ax2.tick_params(axis="y", labelsize=9, colors="#6b7280")
    for spine in ax2.spines.values():
        spine.set_visible(False)
    fig.patch.set_alpha(0)
    ax1.set_facecolor("none")
    ax2.set_facecolor("none")

    fig.tight_layout(pad=0.5)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, transparent=True)
    plt.close(fig)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _assess_dcat_us_1_1(metadata):
    meta = _top_level(metadata)
    results, summary, passed, totals = _score(meta, DCAT_US_1_1)
    return {
        **results,
        "Other": _other(meta, DCAT_US_1_1),
        "FAIR Compliance Checks": summary,
        "Pie chart": _chart(passed, totals),
        "Original Metadata": metadata,
    }


def _assess_dcat_us_3(metadata):
    meta = _top_level(metadata)
    results, summary, passed, totals = _score(meta, DCAT_US_3)
    missing = [k for k in DCAT_US_3_REQUIRED if not _present(meta.get(k))]
    return {
        **results,
        "Other": _other(meta, DCAT_US_3, shown_elsewhere=["@type"]),
        "Conformance": {
            "Required properties present": f"{len(DCAT_US_3_REQUIRED) - len(missing)}/{len(DCAT_US_3_REQUIRED)}",
            "Missing": ", ".join(missing) or "none",
        },
        "FAIR Compliance Checks": summary,
        "Pie chart": _chart(passed, totals),
        "Original Metadata": metadata,
    }


def _assess_datacite(metadata):
    data = metadata.get("data")
    if isinstance(data, dict) and isinstance(data.get("attributes"), dict):
        metadata = data["attributes"]
    meta = {k: v for k, v in metadata.items() if k in DATACITE_PROPERTIES}
    results, summary, passed, totals = _score(meta, DATACITE_4)
    mandatory = {label: check(meta) for label, check in DATACITE_MANDATORY.items()}
    missing = [label for label, value in mandatory.items() if value is None]
    return {
        **results,
        "Other": _other(meta, DATACITE_4),
        "Conformance": {
            "Mandatory properties present": f"{len(mandatory) - len(missing)}/{len(mandatory)}",
            "Missing": ", ".join(missing) or "none",
        },
        "Structure": _datacite_structure(meta),
        "FAIR Compliance Checks": summary,
        "Pie chart": _chart(passed, totals),
        "Original Metadata": meta,
    }


def _assess_croissant(metadata):
    meta = _top_level(metadata)
    results, summary, passed, totals = _score(meta, CROISSANT)
    rai_properties = [p for props in CROISSANT_RAI.values() for p in props]
    return {
        **results,
        "Other": _other(meta, CROISSANT, shown_elsewhere=[*rai_properties, *CROISSANT_REQUIRED]),
        "Conformance": _croissant_conformance(meta),
        "Structure": _croissant_structure(meta),
        "RAI Documentation": _croissant_rai(meta),
        "FAIR Compliance Checks": summary,
        "Pie chart": _chart(passed, totals),
        "Original Metadata": metadata,
    }


def _assess_rocrate(metadata):
    crate = _Crate(metadata)
    if not crate.descriptor:
        raise ValueError("Not an RO-Crate: no ro-crate-metadata.json entity in @graph")
    profile = _rocrate_profile(crate)
    meta = _top_level(crate.root)
    results, summary, passed, totals = _score(meta, profile)
    result = {
        **results,
        "Other": _other(meta, profile, shown_elsewhere=["@id", "@type", "hasPart"]),
        "Conformance": _rocrate_conformance(crate),
        "Structure": _rocrate_structure(crate),
        "FAIR Compliance Checks": summary,
        "Pie chart": _chart(passed, totals),
        "Original Metadata": metadata,
    }
    if crate.local:
        result["Not applicable"] = {"url or distribution": _LOCAL_CRATE, "contentUrl (Files)": _LOCAL_CRATE}
    return result


_ASSESSORS = {
    "croissant": _assess_croissant,
    "rocrate": _assess_rocrate,
    "dcat-us-3.0": _assess_dcat_us_3,
    "dcat-us-1.1": _assess_dcat_us_1_1,
    "datacite": _assess_datacite,
}
STANDARDS = tuple(_ASSESSORS)
STANDARD_NAMES = {
    "croissant": "Croissant",
    "rocrate": "RO-Crate",
    "dcat-us-3.0": "DCAT-US 3.0",
    "dcat-us-1.1": "DCAT-US 1.1 (Project Open Data)",
    "datacite": "DataCite 4.x",
}

# The web form's values, which predate the names above.
_FORM_VALUES = {"DCAT": "dcat-us-1.1", "Datacite": "datacite"}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_CROISSANT_URI = re.compile(r"mlcommons\.org/croissant/(\d+\.\d+)")


def _croissant_version(metadata):
    """The Croissant version a file declares, or None if it is not Croissant."""
    for value in _as_list(metadata.get("conformsTo") or metadata.get("dct:conformsTo")):
        match = _CROISSANT_URI.search(str(value))  # the RAI extension's URI ends in /RAI/1.0 and does not match
        if match:
            return match.group(1)
    context = metadata.get("@context")
    if isinstance(context, dict) and "mlcommons.org/croissant" in str(context.get("cr", "")):
        return "unknown version"
    return None


def detect_standard(metadata):
    """Name the standard a metadata document follows, from what it declares or its key names.

    Runs on the raw JSON: ``sc:Dataset`` and ``dcat:Dataset`` must not be confused by
    prefix stripping. Raises ``ValueError`` when nothing matches.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a JSON object")
    if _croissant_version(metadata):
        return "croissant"
    graph_ids = {e.get("@id") for e in _as_list(metadata.get("@graph")) if isinstance(e, dict)}
    if graph_ids & set(_ROCRATE_DESCRIPTORS) or "w3id.org/ro/crate/" in json.dumps(metadata.get("@context", "")):
        return "rocrate"
    data = metadata.get("data")
    attributes = data.get("attributes") if isinstance(data, dict) else None
    datacite = attributes if isinstance(attributes, dict) else metadata
    if "titles" in datacite and "creators" in datacite:
        return "datacite"
    if isinstance(metadata.get("dataset"), list):
        raise ValueError("This is a DCAT catalog; upload a single dataset record from it.")
    conforms = " ".join(str(v) for v in _as_list(metadata.get("conformsTo")))
    if "accessLevel" in metadata or "bureauCode" in metadata or "project-open-data" in conforms:
        return "dcat-us-1.1"
    # DCAT uses "title" where schema.org uses "name"; contactPoint or distribution confirms it.
    if "title" in metadata and ("contactPoint" in metadata or "distribution" in metadata):
        return "dcat-us-3.0"
    raise ValueError(
        "Could not detect the metadata standard. Supported: Croissant 1.0/1.1, RO-Crate 1.2, "
        "DCAT-US 3.0, DCAT-US 1.1 (Project Open Data) and DataCite 4.x JSON; choose one explicitly "
        "if your file follows it."
    )


def calculate_fair_compliance(metadata, standard="auto"):
    """Score a metadata document against the FAIR principles.

    Parameters
    ----------
    metadata : dict
        The parsed metadata file.
    standard : str
        ``"auto"`` (detect it, the default), ``"croissant"`` (MLCommons Croissant 1.0/1.1),
        ``"rocrate"`` (RO-Crate 1.2; other versions are assessed with 1.2 rules),
        ``"dcat-us-3.0"`` (GSA DCAT-US 3.0 dataset record),
        ``"dcat-us-1.1"`` (Project Open Data) or ``"datacite"`` (DataCite 4.x JSON, including
        REST API responses wrapped in ``data.attributes``). The web form's ``"DCAT"`` and
        ``"Datacite"`` are accepted too.

    Returns
    -------
    dict
        One dict per FAIR principle mapping each check to what was found or
        ``"CHECK FAILED ❌"``, plus ``"FAIR Compliance Checks"`` (``"n/m"`` per principle and
        in total), ``"Standard"``, ``"Other"``, ``"Pie chart"`` (base64 PNG) and
        ``"Original Metadata"``. DataCite and Croissant results also carry ``"Conformance"``
        and ``"Structure"``; Croissant adds ``"RAI Documentation"``; a local RO-Crate adds
        ``"Not applicable"`` for the checks that only apply to web-based crates.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a JSON object")
    detected = standard == "auto"
    standard = detect_standard(metadata) if detected else _FORM_VALUES.get(standard, standard)
    if standard not in _ASSESSORS:
        raise ValueError(f"Unknown metadata type: {standard}")
    result = _ASSESSORS[standard](metadata)
    name = STANDARD_NAMES[standard]
    if standard == "croissant":
        name = f"{name} {_croissant_version(metadata) or '(no version declared)'}"
    elif standard == "rocrate":
        version = _Crate(metadata).version()
        name = f"{name} {version}" if version == "1.2" else f"{name} {version or '(no version declared)'}, assessed with 1.2 rules"
    result["Standard"] = {"Name": name, "Detected automatically": "yes" if detected else "no"}
    return result
