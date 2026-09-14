"""Integration tests for the intent recommendation routes.

The curated path must work with no LLM installed or configured, so these
tests run in every CI job. LLM-specific behaviour is monkeypatched rather
than gated on the optional dependency.
"""

import time

import aidrin
import web.routes.intent as intent_routes
from aidrin.intent import all_metric_keys


def test_recommend_requires_intents_or_notes(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": [], "notes": ""})
    assert response.status_code == 400


def test_recommend_rejects_non_list_intents(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": "training"})
    assert response.status_code == 400


def test_recommend_works_without_any_llm(uploaded_client):
    """The curated half must not depend on openai being installed."""
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    assert response.status_code == 200
    data = response.get_json()
    assert data["llm_used"] is False
    assert data["intents"] == ["training"]
    metrics = [r["metric"] for r in data["recommendations"]]
    assert "completeness" in metrics
    assert all(r["source"] == "curated" for r in data["recommendations"])


def test_recommend_accepts_notes_only(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": [], "notes": "just curious"})
    assert response.status_code == 200
    assert response.get_json()["recommendations"] == []


def test_unknown_intents_are_filtered_out(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training", "bogus"]})
    assert response.get_json()["intents"] == ["training"]


def test_recommendations_are_critical_first(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training", "publishing"]})
    priorities = [r["priority"] for r in response.get_json()["recommendations"]]
    assert priorities == sorted(priorities, key=lambda p: 0 if p == "critical" else 1)


def test_every_recommendation_carries_a_panel_and_display_name(uploaded_client):
    response = uploaded_client.post("/intent/recommend", json={"intents": ["publishing"]})
    for rec in response.get_json()["recommendations"]:
        assert rec["display_name"]
        assert rec["panel"]
        assert rec["panel_label"]
        assert rec["why"]


def test_llm_enhancement_is_merged_when_available(uploaded_client, monkeypatch):
    monkeypatch.setattr(intent_routes, "_llm_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(
        intent_routes,
        "_call_llm",
        lambda *a, **kw: {
            "summary": "Tailored summary.",
            "rationales": {"completeness": "Six columns have nulls."},
            "extras": [{"metric": "t_closeness", "why": "Because you said EU."}],
        },
    )
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    data = response.get_json()

    assert data["llm_used"] is True
    assert data["model"] == "test-model"
    assert data["summary"] == "Tailored summary."

    by_key = {r["metric"]: r for r in data["recommendations"]}
    assert by_key["completeness"]["why"] == "Six columns have nulls."
    assert by_key["completeness"]["source"] == "curated"
    assert by_key["t_closeness"]["source"] == "ai"
    assert by_key["t_closeness"]["priority"] == "recommended"


def test_llm_failure_degrades_to_the_curated_list(uploaded_client, monkeypatch):
    monkeypatch.setattr(intent_routes, "_llm_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(intent_routes, "_call_llm", lambda *a, **kw: None)
    response = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    data = response.get_json()
    assert data["llm_used"] is False
    assert any(r["metric"] == "completeness" for r in data["recommendations"])


def test_result_is_cached_and_llm_not_called_twice(uploaded_client, monkeypatch):
    calls = []

    def _fake(*args, **kwargs):
        calls.append(1)
        return {"summary": "once", "rationales": {}, "extras": []}

    monkeypatch.setattr(intent_routes, "_llm_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(intent_routes, "_call_llm", _fake)

    first = uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    cached = uploaded_client.get("/cached-result/intent")

    assert cached.status_code == 200
    cached_data = cached.get_json()
    assert cached_data.get("cached") is True
    assert cached_data["data"]["recommendations"] == first.get_json()["recommendations"]
    assert len(calls) == 1


def test_notes_are_truncated_in_the_session(uploaded_client):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"], "notes": "x" * 5000})
    with uploaded_client.session_transaction() as sess:
        assert len(sess["intent"]["notes"]) == intent_routes.NOTES_MAX


def test_intent_is_stored_in_the_session(uploaded_client):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    with uploaded_client.session_transaction() as sess:
        assert sess["intent"]["intents"] == ["training"]


def test_dismiss_marks_the_modal_as_handled(uploaded_client):
    response = uploaded_client.post("/intent/dismiss", json={})
    assert response.status_code == 200
    with uploaded_client.session_transaction() as sess:
        assert sess["intent"]["dismissed"] is True


def test_recommend_without_a_dataset_still_returns_advice(client):
    """No file loaded means no profile, but the curated list is unaffected."""
    response = client.post("/intent/recommend", json={"intents": ["training"]})
    assert response.status_code == 200
    assert response.get_json()["recommendations"]


# --------------------------------------------------------------------------
# Stale-state resets
# --------------------------------------------------------------------------


def test_new_upload_clears_intent(uploaded_client, sample_csv):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    with uploaded_client.session_transaction() as sess:
        assert "intent" in sess

    with open(sample_csv, "rb") as handle:
        uploaded_client.post(
            "/inspector",
            data={"file": (handle, "second.csv"), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
        )

    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess


def test_clear_file_clears_intent(uploaded_client):
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    uploaded_client.post("/clear")
    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess


def test_filter_file_clears_intent(uploaded_client):
    """HDF5 dataset switch must not leave advice for the previous columns."""
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    # /filter-file reads data.get("keys") (core.py:254). Posting the wrong field
    # name returns 400 before the pop is reached, so the payload must be "keys".
    response = uploaded_client.post("/filter-file", json={"keys": ["a"]})
    assert response.status_code == 200, response.get_data(as_text=True)
    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess


def test_clear_dataset_selection_clears_intent(uploaded_client):
    """The HDF5 "pick different arrays" path must not keep the old advice."""
    uploaded_client.post("/intent/recommend", json={"intents": ["training"]})
    # /clear-dataset-selection guards on file_type == ".h5" (core.py:320-321).
    # The CSV fixture does not satisfy that, so set it via session_transaction.
    # The pop at line 328 happens before hdf5Reader.inventory() is called,
    # so even if that call fails, the pop will have already executed.
    with uploaded_client.session_transaction() as sess:
        sess["uploaded_file_type"] = ".h5"
    response = uploaded_client.post("/clear-dataset-selection")
    # Route will fail trying to parse CSV as HDF5, but pop executes first.
    assert response.status_code != 200
    with uploaded_client.session_transaction() as sess:
        assert "intent" not in sess


# --------------------------------------------------------------------------
# _build_profile is actually used
# --------------------------------------------------------------------------
#
# uploaded_client never calls /summary-statistics, so every test above that
# uses it exercises the profile=None branch only. These tests warm the cache
# first and assert the applicability filter genuinely changes the output.
# "exploration" recommends skewness and kurtosis, both of which require a
# numerical column (aidrin/intent.py APPLICABILITY); a categorical-only
# dataset must drop them once (and only once) a profile is available.

CATEGORICAL_ONLY_CSV = "color,size\nred,S\nblue,M\ngreen,L\nred,M\n"


def _upload_csv(client, tmp_path, content, filename="categorical_only.csv"):
    csv_path = tmp_path / filename
    csv_path.write_text(content)
    with open(csv_path, "rb") as handle:
        response = client.post(
            "/inspector",
            data={"file": (handle, filename), "fileTypeSelector": ".csv"},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    assert response.status_code == 302
    return client


def test_profile_from_warm_cache_drops_inapplicable_metrics(client, tmp_path):
    """Before /summary-statistics runs, the profile is None and the
    applicability filter fails open (skewness/kurtosis survive even though
    this dataset has no numerical columns). After warming the cache with the
    real profile, both must be dropped -- proving _build_profile's result is
    actually read, not just computed and discarded."""
    _upload_csv(client, tmp_path, CATEGORICAL_ONLY_CSV)

    before = client.post("/intent/recommend", json={"intents": ["exploration"]})
    before_metrics = [r["metric"] for r in before.get_json()["recommendations"]]
    assert "skewness" in before_metrics
    assert "kurtosis" in before_metrics

    warm = client.get("/summary-statistics")
    assert warm.status_code == 200
    assert warm.get_json()["numerical_features"] == []

    after = client.post("/intent/recommend", json={"intents": ["exploration"]})
    after_metrics = [r["metric"] for r in after.get_json()["recommendations"]]
    assert "skewness" not in after_metrics
    assert "kurtosis" not in after_metrics
    # Sanity: metrics with no numerical requirement are unaffected, so this
    # is the applicability filter at work, not an empty recommendation list.
    assert "completeness" in after_metrics


def test_hdf5_profile_lookup_is_keyed_by_selected_keys(client, app):
    """The summary-statistics cache key includes selected_keys (core.py's
    /summary-statistics and _build_profile both build it the same way), so a
    lookup made with a different selection must miss the cache entirely.
    Driving a real multi-dataset HDF5 upload through the test client is not
    practical here, so the session state _build_profile reads is set
    directly, exercising _selected_keys and the cache-key construction."""
    file_name = "multi.h5"
    user_id = "hdf5-profile-test-user"
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["uploaded_file_name"] = file_name
        sess["uploaded_file_path"] = "/fake/upload/multi.h5"
        sess["uploaded_file_type"] = ".h5"
        sess["selected_keys"] = ["dataset_a"]

    # Built by hand, mirroring generate_metric_cache_key's "summarystats"
    # branch (web/routes/utils.py), since that helper requires a request
    # context and none is active here.
    cache_key = f"user:{user_id}|file:{file_name}|summarystats:keys:dataset_a"
    app.TEMP_RESULTS_CACHE[cache_key] = {
        "data": {
            "success": True,
            "records_count": 10,
            "features_count": 1,
            "numerical_features": [],
            "categorical_features": ["dataset_a"],
        },
        "timestamp": time.time(),
        "expires_at": time.time() + 1800,
    }

    # Matching selected_keys: cache hits, categorical-only profile drops skewness.
    hit = client.post("/intent/recommend", json={"intents": ["exploration"]})
    hit_metrics = [r["metric"] for r in hit.get_json()["recommendations"]]
    assert "skewness" not in hit_metrics

    # Different selected_keys: cache key no longer matches -> miss -> profile
    # None -> the filter fails open again.
    with client.session_transaction() as sess:
        sess["selected_keys"] = ["dataset_b"]
    miss = client.post("/intent/recommend", json={"intents": ["exploration"]})
    miss_metrics = [r["metric"] for r in miss.get_json()["recommendations"]]
    assert "skewness" in miss_metrics


# --------------------------------------------------------------------------
# GET /intent/metrics
# --------------------------------------------------------------------------


def test_metrics_returns_every_recommendable_metric(client):
    """No dataset, no session, no LLM required -- this is a static catalog."""
    response = client.get("/intent/metrics")
    assert response.status_code == 200
    data = response.get_json()
    returned = {entry["metric"] for entry in data["metrics"]}
    assert returned == all_metric_keys()
    assert len(data["metrics"]) == 29


def test_metrics_entries_carry_the_documented_shape(client):
    response = client.get("/intent/metrics")
    data = response.get_json()
    for entry in data["metrics"]:
        assert set(entry) == {
            "metric", "display_name", "panel", "panel_label", "input_name", "description",
        }
        assert entry["display_name"]
        assert entry["panel"]
        assert entry["panel_label"]
        assert entry["description"]


def test_metrics_are_grouped_contiguously_by_panel(client):
    """The front end relies on same-panel entries being adjacent to render one
    heading per group without a second index: once a panel is left behind it
    must never reappear later in the list."""
    response = client.get("/intent/metrics")
    panels = [entry["panel"] for entry in response.get_json()["metrics"]]
    seen_and_closed = set()
    last_panel = None
    for panel in panels:
        if panel != last_panel:
            assert panel not in seen_and_closed, f"panel {panel!r} is not contiguous"
            seen_and_closed.add(panel)
            last_panel = panel


def test_metrics_route_requires_no_llm_or_session_state(client, monkeypatch):
    """Guards against a future change accidentally wiring in an LLM call."""
    def _boom(*args, **kwargs):
        raise AssertionError("_llm_config must not be consulted by /intent/metrics")

    monkeypatch.setattr(intent_routes, "_llm_config", _boom)
    response = client.get("/intent/metrics")
    assert response.status_code == 200


def test_metrics_route_reports_the_running_aidrin_version(client):
    """The profile builder fetches this endpoint once and stamps the value
    it returns into a saved profile as provenance (aidrin_version)."""
    response = client.get("/intent/metrics")
    assert response.get_json()["aidrin_version"] == aidrin.__version__


# --------------------------------------------------------------------------
# POST /intent/profile
# --------------------------------------------------------------------------

VALID_PROFILE = {
    "profile_version": 1,
    "name": "Lab intake QC",
    "critical": ["completeness", "row_level_completeness"],
    "recommended": ["outliers"],
}


def test_profile_returns_the_recommend_shape_with_llm_used_false(uploaded_client):
    response = uploaded_client.post("/intent/profile", json=VALID_PROFILE)
    assert response.status_code == 200
    data = response.get_json()

    assert data["intents"] == []
    assert data["notes"] == ""
    assert data["summary"] == ""
    assert data["llm_used"] is False
    assert data["model"] == ""
    assert data["profile_name"] == "Lab intake QC"
    assert data["dropped_unknown"] == []
    assert data["dropped_inapplicable"] == []
    # No aidrin_version in the request (VALID_PROFILE predates this field):
    # informational-only, so this must be silently empty, never an error.
    assert data["profile_aidrin_version_note"] == ""

    metrics = {r["metric"]: r for r in data["recommendations"]}
    assert metrics["completeness"]["priority"] == "critical"
    assert metrics["completeness"]["source"] == "profile"
    assert metrics["completeness"]["reason_intents"] == []
    assert metrics["outliers"]["priority"] == "recommended"


def test_profile_matching_aidrin_version_has_no_note(uploaded_client):
    response = uploaded_client.post(
        "/intent/profile", json={**VALID_PROFILE, "aidrin_version": aidrin.__version__}
    )
    assert response.status_code == 200
    assert response.get_json()["profile_aidrin_version_note"] == ""


def test_profile_different_aidrin_version_still_loads_with_a_note(uploaded_client):
    """aidrin_version is provenance only: a mismatch must never block the
    load (unlike profile_version, the file-format gate below), only surface
    a mild, non-blocking note."""
    response = uploaded_client.post(
        "/intent/profile", json={**VALID_PROFILE, "aidrin_version": "1999.01.0"}
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["recommendations"]
    note = data["profile_aidrin_version_note"]
    assert "1999.01.0" in note
    assert aidrin.__version__ in note


def test_profile_without_aidrin_version_still_loads_with_no_note(uploaded_client):
    """Profiles saved before this field existed must keep loading, silently."""
    assert "aidrin_version" not in VALID_PROFILE
    response = uploaded_client.post("/intent/profile", json=VALID_PROFILE)
    assert response.status_code == 200
    assert response.get_json()["profile_aidrin_version_note"] == ""


def test_profile_wrong_version_returns_400(uploaded_client):
    response = uploaded_client.post("/intent/profile", json={**VALID_PROFILE, "profile_version": 2})
    assert response.status_code == 400


def test_profile_legacy_version_key_still_loads(uploaded_client):
    """"version" is accepted as a legacy alias for "profile_version" on load
    only, for profile files saved before the rename."""
    body = {k: v for k, v in VALID_PROFILE.items() if k != "profile_version"}
    body["version"] = 1
    response = uploaded_client.post("/intent/profile", json=body)
    assert response.status_code == 200
    assert response.get_json()["recommendations"]


def test_profile_wrong_legacy_version_returns_400(uploaded_client):
    body = {k: v for k, v in VALID_PROFILE.items() if k != "profile_version"}
    body["version"] = 2
    response = uploaded_client.post("/intent/profile", json=body)
    assert response.status_code == 400


def test_profile_empty_metrics_returns_400(uploaded_client):
    response = uploaded_client.post(
        "/intent/profile",
        json={"profile_version": 1, "name": "Empty", "critical": [], "recommended": []},
    )
    assert response.status_code == 400


def test_profile_missing_metric_lists_returns_400(uploaded_client):
    response = uploaded_client.post("/intent/profile", json={"profile_version": 1, "name": "Empty"})
    assert response.status_code == 400


def test_profile_non_dict_body_returns_400(uploaded_client):
    response = uploaded_client.post("/intent/profile", json=["not", "a", "dict"])
    assert response.status_code == 400


def test_profile_name_is_truncated_to_the_max_length(uploaded_client):
    response = uploaded_client.post(
        "/intent/profile", json={**VALID_PROFILE, "name": "x" * 500}
    )
    data = response.get_json()
    assert len(data["profile_name"]) == intent_routes.MAX_PROFILE_NAME


def test_profile_blank_name_becomes_untitled_profile(uploaded_client):
    response = uploaded_client.post("/intent/profile", json={**VALID_PROFILE, "name": "   "})
    assert response.get_json()["profile_name"] == "Untitled profile"


def test_profile_absent_name_becomes_untitled_profile(uploaded_client):
    body = {k: v for k, v in VALID_PROFILE.items() if k != "name"}
    response = uploaded_client.post("/intent/profile", json=body)
    assert response.get_json()["profile_name"] == "Untitled profile"


def test_profile_unknown_metrics_are_reported_and_excluded(uploaded_client):
    response = uploaded_client.post(
        "/intent/profile",
        json={"profile_version": 1, "name": "x", "critical": ["completeness", "not_a_metric"], "recommended": []},
    )
    data = response.get_json()
    assert data["dropped_unknown"] == ["not_a_metric"]
    assert "not_a_metric" not in [r["metric"] for r in data["recommendations"]]
    assert "completeness" in [r["metric"] for r in data["recommendations"]]


def test_profile_result_is_cached_for_reload(uploaded_client):
    uploaded_client.post("/intent/profile", json=VALID_PROFILE)
    cached = uploaded_client.get("/cached-result/intent")
    assert cached.status_code == 200
    cached_data = cached.get_json()
    assert cached_data.get("cached") is True
    assert cached_data["data"]["profile_name"] == "Lab intake QC"


def test_profile_never_calls_the_llm(uploaded_client, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("_call_llm must not be called on the profile path")

    monkeypatch.setattr(intent_routes, "_call_llm", _boom)
    response = uploaded_client.post("/intent/profile", json=VALID_PROFILE)
    assert response.status_code == 200
    assert response.get_json()["llm_used"] is False
