"""Flask routes for intent-based metric recommendations.

Registered unconditionally. The curated recommendation needs no LLM and no
network; web.llm is imported lazily inside the handler so this module never
hard-depends on the optional openai package.

Nothing here runs a metric or reads a dataset. The dataset profile is read
from the summary-statistics cache when warm and is None otherwise.
"""

import logging
import time

from flask import Blueprint, current_app, jsonify, request, session

from aidrin._version import __version__ as AIDRIN_VERSION
from aidrin.intent import (
    CHECKBOX_BY_METRIC,
    DESCRIPTIONS,
    DISPLAY_NAMES,
    INTENT_KEYS,
    INTENTS,
    MAX_PROFILE_NAME,
    PANEL_BY_METRIC,
    PANEL_LABELS,
    PROFILE_VERSION,
    _recommendation_sort_key,
    all_metric_keys,
    recommend_metrics,
    recommendations_from_profile,
)
from web.routes.utils import (
    generate_metric_cache_key,
    get_current_user_id,
    is_metric_cache_valid,
)

logger = logging.getLogger(__name__)

intent_bp = Blueprint("intent", __name__, url_prefix="/intent")

NOTES_MAX = 500
CACHE_TTL_SECONDS = 30 * 60
MAX_PROFILE_COLUMNS = 50


def _session_file_name():
    return session.get("uploaded_file_name") or session.get("globus_file_name") or ""


def _selected_keys(file_type):
    """Reproduce the HDF5 branch of /summary-statistics exactly.

    core.py:461-465 (and utils.py:79's build_file_info) only read
    session["selected_keys"] when the current file is HDF5, storing it as a
    list or a comma string, and the cache key sorts them. Diverging here —
    e.g. picking up a stale selected_keys value left over from a previous
    HDF5 upload while a CSV/JSON file is now loaded — would miss the cache
    on every dataset and fall through to a profile of None.
    """
    if file_type != ".h5":
        return []
    selected = session.get("selected_keys") or []
    if isinstance(selected, str):
        selected = [key.strip() for key in selected.split(",") if key.strip()]
    return selected


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _columns_with_nulls(data):
    """Derive the null-column count; None when it cannot be established.

    /summary-statistics does not report this directly. summary_statistics is
    empty when a dataset has no numeric columns (core.py:507-508), so the
    figure is best-effort and the prompt omits the line when it is None.
    """
    records = _to_number(data.get("records_count"))
    if not records:
        return None

    count = 0
    seen = False
    for group in ("summary_statistics", "categorical_summary"):
        for stats in (data.get(group) or {}).values():
            if not isinstance(stats, dict):
                continue
            present = _to_number(stats.get("count"))
            if present is None:
                continue
            seen = True
            if present < records:
                count += 1
    return count if seen else None


def _build_profile():
    """Read a small profile from the warm summary-statistics cache.

    Returns None on a cache miss, in Globus mode, or when no file is loaded.
    Never reads the dataset: load_dataframe would materialise up to 1 GB
    synchronously inside this request, which is not acceptable for a feature
    that computes nothing.
    """
    file_name = _session_file_name()
    if not file_name or not session.get("uploaded_file_path"):
        return None

    file_type = session.get("uploaded_file_type")
    cache_key = generate_metric_cache_key(file_name, "summarystats", selected_keys=_selected_keys(file_type))
    entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if not entry or not is_metric_cache_valid(entry):
        return None

    data = entry.get("data") or {}
    if not data.get("success"):
        return None

    return {
        "rows": data.get("records_count"),
        "columns": data.get("features_count"),
        "numerical": list(data.get("numerical_features") or [])[:MAX_PROFILE_COLUMNS],
        "categorical": list(data.get("categorical_features") or [])[:MAX_PROFILE_COLUMNS],
        "columns_with_nulls": _columns_with_nulls(data),
    }


def _llm_config():
    """Return the session LLM config when the feature is usable, else None.

    Separated so tests can monkeypatch it without installing openai.
    """
    try:
        from web.llm import is_llm_available
    except Exception:
        return None
    if not is_llm_available():
        return None
    config = session.get("llm_config")
    if not config or not config.get("api_key"):
        return None
    return config


def _call_llm(intents, notes, profile, baseline, config):
    """Thin seam over web.llm.recommend_for_intent for monkeypatching."""
    from web.llm import recommend_for_intent

    return recommend_for_intent(intents, notes, profile, baseline, config)


def _build_ai_recommendations(selection):
    """Build recommendation cards from the LLM's own selection.

    The LLM is the primary recommender: this is the full recommendation
    list, not an overlay on the curated baseline, so a metric the curated
    map would have included but the model left out simply does not appear.
    Sorted with the same shared ordering recommend_metrics and
    recommendations_from_profile use, for a consistent critical-first layout.
    """
    recommendations = [
        {
            "metric": entry["metric"],
            "display_name": DISPLAY_NAMES[entry["metric"]],
            "panel": PANEL_BY_METRIC[entry["metric"]],
            "panel_label": PANEL_LABELS[PANEL_BY_METRIC[entry["metric"]]],
            "priority": entry["priority"],
            "source": "ai",
            "reason_intents": [],
            "why": entry["why"],
            "input_name": CHECKBOX_BY_METRIC[entry["metric"]],
        }
        for entry in selection
    ]
    recommendations.sort(key=_recommendation_sort_key)
    return recommendations


def _store(payload):
    """Cache under the same convention as store_result, so /cached-result works."""
    file_name = _session_file_name()
    if not file_name:
        return
    key = f"user:{get_current_user_id()}:file:{file_name}:intent"
    current_app.TEMP_RESULTS_CACHE[key] = {
        "data": payload,
        "timestamp": time.time(),
        "expires_at": time.time() + CACHE_TTL_SECONDS,
    }


@intent_bp.route("/recommend", methods=["POST"])
def recommend():
    """Return which metrics the user should check, given what they plan to do."""
    body = request.get_json(silent=True) or {}

    raw_intents = body.get("intents", [])
    if not isinstance(raw_intents, list):
        return jsonify({"error": "intents must be a list"}), 400

    order = [entry["key"] for entry in INTENTS]
    chosen = {key for key in raw_intents if key in INTENT_KEYS}
    intents = [key for key in order if key in chosen]

    notes = (body.get("notes") or "").strip()[:NOTES_MAX]
    if not intents and not notes:
        return jsonify({"error": "Select at least one goal or describe your plan"}), 400

    profile = _build_profile()
    baseline = recommend_metrics(intents, profile)

    # The LLM, when connected, is the primary recommender: its selection
    # replaces the curated baseline entirely rather than extending it, so a
    # metric the curated map would have included but the model left out is
    # genuinely absent from the response. `baseline` is still sent to the
    # model as grounding (see recommend_for_intent / _build_user_content).
    # Any LLM failure -- unavailable, unreachable, or a reply that validates
    # to nothing -- falls back to the curated baseline unchanged.
    result = None
    config = _llm_config()
    if config:
        result = _call_llm(intents, notes, profile, [r["metric"] for r in baseline], config)

    if result:
        recommendations = _build_ai_recommendations(result["selection"])
        summary = result.get("summary") or ""
        llm_used = True
        model = config.get("model", "")
    else:
        recommendations = baseline
        summary = ""
        llm_used = False
        model = ""

    payload = {
        "intents": intents,
        "notes": notes,
        "summary": summary,
        "llm_used": llm_used,
        "model": model,
        "recommendations": recommendations,
    }

    session["intent"] = {"intents": intents, "notes": notes, "dismissed": False}
    _store(payload)
    return jsonify(payload)


@intent_bp.route("/profile", methods=["POST"])
def load_profile():
    """Turn a user-supplied profile file into the same shape /recommend returns.

    No LLM call: a profile is an explicit user choice, so there is nothing
    for the LLM to select.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "Profile must be a JSON object"}), 400

    # profile_version is the file-FORMAT compatibility gate: it says whether
    # this JSON shape can still be read at all, and a mismatch is a hard
    # 400 -- never influenced by aidrin_version below, which only records
    # which AIDRIN *build* produced the file (informational provenance, not
    # a rejection reason: a profile saved today must keep loading after an
    # AIDRIN upgrade).
    #
    # "version" is accepted as a legacy alias for profile_version on load
    # only -- pre-rename builds saved profiles keyed "version" -- and can be
    # removed once no such files are likely to still be in the wild. Saving
    # never writes "version" again.
    profile_version = body.get("profile_version", body.get("version"))
    if profile_version is not None and profile_version != PROFILE_VERSION:
        return jsonify({"error": f"Unsupported profile version: {profile_version!r}"}), 400

    critical = body.get("critical")
    recommended = body.get("recommended")
    critical_list = critical if isinstance(critical, list) else []
    recommended_list = recommended if isinstance(recommended, list) else []
    if not critical_list and not recommended_list:
        return jsonify({"error": "Profile has no metrics"}), 400

    name = str(body.get("name") or "").strip()[:MAX_PROFILE_NAME]
    if not name:
        name = "Untitled profile"

    dataset_profile = _build_profile()
    recommendations, dropped_unknown, dropped_inapplicable = recommendations_from_profile(body, dataset_profile)

    # aidrin_version is informational only (see the comment above): note a
    # mismatch for the user, but never reject the load, and say nothing when
    # it is absent (profiles saved before this field existed).
    saved_aidrin_version = body.get("aidrin_version")
    aidrin_version_note = ""
    if (
        isinstance(saved_aidrin_version, str)
        and saved_aidrin_version
        and saved_aidrin_version != AIDRIN_VERSION
    ):
        aidrin_version_note = (
            f"This profile was saved with AIDRIN {saved_aidrin_version}; "
            f"you are running {AIDRIN_VERSION}."
        )

    payload = {
        "intents": [],
        "notes": "",
        "summary": "",
        "llm_used": False,
        "model": "",
        "recommendations": recommendations,
        "profile_name": name,
        "dropped_unknown": dropped_unknown,
        "dropped_inapplicable": dropped_inapplicable,
        "profile_aidrin_version_note": aidrin_version_note,
    }

    session["intent"] = {"intents": [], "notes": "", "dismissed": False, "profile_name": name}
    _store(payload)
    return jsonify(payload)


@intent_bp.route("/metrics", methods=["GET"])
def metrics():
    """Return every recommendable metric, for the profile-builder UI.

    /intent/recommend only ever returns the subset currently recommended, so
    the "build a profile" editor -- which lets a user tick metrics that
    are NOT recommended -- needs the full catalog separately. No LLM call
    and no dataset access: this is a static list derived from
    aidrin.intent's tables.

    Returned as a flat list (not nested per panel) but pre-sorted so every
    metric in the same panel is contiguous, in PANEL_LABELS's declared
    order and then by metric key. The front end groups by watching when
    panel_label changes rather than needing a second, nested response
    shape.

    Also returns aidrin_version: the builder fetches this endpoint once,
    before a user can reach "Download profile JSON", so it is the least
    invasive place to hand the running AIDRIN version to the front end for
    stamping into the saved profile as provenance (see load_profile()).
    """
    panel_order = {panel: index for index, panel in enumerate(PANEL_LABELS)}
    catalog = [
        {
            "metric": metric,
            "display_name": DISPLAY_NAMES[metric],
            "panel": PANEL_BY_METRIC[metric],
            "panel_label": PANEL_LABELS[PANEL_BY_METRIC[metric]],
            "input_name": CHECKBOX_BY_METRIC[metric],
            "description": DESCRIPTIONS[metric],
        }
        for metric in all_metric_keys()
    ]
    catalog.sort(key=lambda entry: (panel_order[entry["panel"]], entry["metric"]))
    return jsonify({"metrics": catalog, "aidrin_version": AIDRIN_VERSION})


@intent_bp.route("/dismiss", methods=["POST"])
def dismiss():
    """Record that the user skipped the question, so the modal stops asking."""
    session["intent"] = {"intents": [], "notes": "", "dismissed": True}
    return jsonify({"success": True})
