"""Structural guards for the intent catalog.

These tests are the reason aidrin/intent.py does not import METRIC_REGISTRY
at module scope: importing aidrin.headless.api pulls in pandas, celery,
matplotlib, sklearn and Flask (via the HDF5/JSON readers). The drift guard
lives here instead, where the heavy import is acceptable.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import jinja2

from aidrin import intent

REPO_ROOT = Path(__file__).resolve().parents[2]
PANELS_DIR = REPO_ROOT / "web" / "templates" / "_panels"
COMPONENTS_DIR = REPO_ROOT / "web" / "templates" / "_components"

# The two templates that render intent-goal checkboxes: the intent modal
# (goals, notes, and -- via its "Other" option -- the JSON profile loader),
# and the Intent & Recommendations panel's inline "Change goal" card (goals
# and notes only; building/loading a profile happens elsewhere in the panel).
INTENT_GOAL_TEMPLATES = {
    "intent_modal.html": COMPONENTS_DIR / "intent_modal.html",
    "_intent.html": PANELS_DIR / "_intent.html",
}

# Maps PANEL_BY_METRIC's panel keys to their template file, so the checkbox
# drift-guard below can find the right file to grep.
PANEL_TEMPLATE_FILE = {
    "data-quality": "_data_quality.html",
    "data-structure": "_data_structure.html",
    "correlation-analysis": "_correlation_analysis.html",
    "feature-relevance": "_feature_relevance.html",
    "class-imbalance": "_class_imbalance.html",
    "fairness": "_fairness.html",
    "privacy-preservation": "_privacy_preservation.html",
    "hipaa-compliance": "_hipaa_compliance.html",
    "variable-unit-validation": "_variable_unit_validation.html",
    "fair-assessment": "_fair_assessment.html",
}


def test_metric_keys_match_registry():
    """METRIC_KEYS must stay in step with the real registry."""
    from aidrin.headless.api import METRIC_REGISTRY

    assert intent.METRIC_KEYS == set(METRIC_REGISTRY)


def test_web_only_metrics_are_disjoint_from_registry():
    assert intent.METRIC_KEYS.isdisjoint(intent.WEB_ONLY)


def test_web_only_entries_carry_category_and_description():
    for key, meta in intent.WEB_ONLY.items():
        assert meta.get("category"), key
        assert meta.get("description"), key


def test_every_recommendable_metric_has_a_panel():
    assert set(intent.PANEL_BY_METRIC) == intent.all_metric_keys()


def test_every_recommendable_metric_has_a_display_name():
    assert set(intent.DISPLAY_NAMES) == intent.all_metric_keys()


def test_every_recommendable_metric_has_a_description():
    assert set(intent.DESCRIPTIONS) == intent.all_metric_keys()


def test_profile_keys_are_all_recommendable():
    valid = intent.all_metric_keys()
    for key, profile in intent.INTENT_PROFILES.items():
        for tier in ("critical", "recommended"):
            unknown = set(profile[tier]) - valid
            assert not unknown, f"{key}.{tier} has unknown metrics: {unknown}"


def test_no_metric_is_both_critical_and_recommended_for_one_intent():
    for key, profile in intent.INTENT_PROFILES.items():
        overlap = set(profile["critical"]) & set(profile["recommended"])
        assert not overlap, f"{key} lists {overlap} in both tiers"


def test_intents_and_profiles_cover_the_same_keys():
    assert {i["key"] for i in intent.INTENTS} == set(intent.INTENT_PROFILES)
    assert intent.INTENT_KEYS == set(intent.INTENT_PROFILES)


def test_there_are_seven_intents():
    assert len(intent.INTENTS) == 7


def test_every_intent_has_a_label_and_description():
    for entry in intent.INTENTS:
        assert entry["key"] and entry["label"] and entry["description"]


def test_every_panel_in_the_map_has_a_label():
    assert set(intent.PANEL_BY_METRIC.values()) <= set(intent.PANEL_LABELS)


def test_caveat_keys_are_recommendable():
    assert set(intent.CAVEATS) <= intent.all_metric_keys()


def test_metrics_needing_user_input_all_carry_a_caveat():
    """A critical card that leads to an unfillable panel is worse than no card."""
    needs_input = {
        "row_level_completeness",
        "temporal_completeness",
        "null_count_trend",
        "outliers_custom",
        "file_reference_validation",
        "class_imbalance",
        "feature_relevance",
        "statistical_rates",
        "k_anonymity",
        "l_diversity",
        "t_closeness",
        "entropy_risk",
        "single_attribute_risk",
        "multiple_attribute_risk",
    }
    assert needs_input <= set(intent.CAVEATS)


def test_applicability_requirements_are_known_kinds():
    assert set(intent.APPLICABILITY.values()) <= {
        "categorical",
        "numerical",
        "string",
        "two_columns",
    }


def test_applicability_keys_are_recommendable():
    assert set(intent.APPLICABILITY) <= intent.all_metric_keys()


def test_temporal_completeness_has_no_applicability_rule():
    """Spec decision: timestamp detection is unreliable, so never filter it."""
    assert "temporal_completeness" not in intent.APPLICABILITY


def test_differential_privacy_is_in_no_profile():
    """It is a remediation utility, not an assessment. Deliberately unused."""
    for profile in intent.INTENT_PROFILES.values():
        assert "differential_privacy" not in profile["critical"]
        assert "differential_privacy" not in profile["recommended"]


# --------------------------------------------------------------------------
# recommend_metrics
# --------------------------------------------------------------------------

FULL_PROFILE = {
    "rows": 100,
    "columns": 4,
    "numerical": ["age", "income"],
    "categorical": ["sex", "race"],
    "columns_with_nulls": 1,
}


def _metrics(results):
    return [r["metric"] for r in results]


def _by_key(results):
    return {r["metric"]: r for r in results}


def test_empty_intents_returns_empty_list():
    assert recommend([]) == []


def recommend(intents, profile=FULL_PROFILE):
    return intent.recommend_metrics(intents, profile)


def test_unknown_intent_is_ignored_not_raised():
    assert recommend(["not_a_real_intent"]) == []


def test_unknown_intent_alongside_known_one_keeps_the_known_one():
    assert "completeness" in _metrics(recommend(["training", "bogus"]))


def test_single_intent_returns_its_critical_and_recommended_metrics():
    results = _by_key(recommend(["exploration"]))
    assert results["completeness"]["priority"] == "critical"
    assert results["skewness"]["priority"] == "recommended"


def test_result_shape_has_exactly_the_documented_keys():
    entry = _by_key(recommend(["exploration"]))["completeness"]
    assert set(entry) == {
        "metric",
        "display_name",
        "panel",
        "panel_label",
        "priority",
        "source",
        "reason_intents",
        "why",
        "input_name",
    }
    assert entry["display_name"] == "Completeness"
    assert entry["panel"] == "data-quality"
    assert entry["panel_label"] == "Data Quality"
    assert entry["source"] == "curated"
    # completeness has no caveat, so why is the plain description
    assert entry["why"] == intent.DESCRIPTIONS["completeness"]
    assert entry["input_name"] == "completeness"


def test_a_metric_with_a_caveat_states_it_in_why():
    """Cards must say what the user has to bring, or they are dead ends."""
    entry = _by_key(recommend(["training"]))["class_imbalance"]
    assert intent.DESCRIPTIONS["class_imbalance"] in entry["why"]
    assert intent.CAVEATS["class_imbalance"] in entry["why"]


def test_within_file_limitation_is_stated_for_duplicate_detection():
    entry = _by_key(recommend(["benchmarking"]))["duplicity_by_features"]
    assert "within this file only" in entry["why"]


def test_multiple_intents_union_their_metrics():
    results = _metrics(recommend(["exploration", "publishing"]))
    assert "skewness" in results          # exploration only
    assert "fair_assessment" in results   # publishing only


def test_priority_merges_by_maximum():
    """duplicity is recommended for publishing, critical for exploration."""
    assert intent.INTENT_PROFILES["publishing"]["recommended"].count("duplicity") == 1
    assert intent.INTENT_PROFILES["exploration"]["critical"].count("duplicity") == 1
    results = _by_key(recommend(["publishing", "exploration"]))
    assert results["duplicity"]["priority"] == "critical"


def test_reason_intents_lists_every_intent_that_asked_for_the_metric():
    results = _by_key(recommend(["training", "exploration"]))
    assert results["completeness"]["reason_intents"] == ["training", "exploration"]


def test_reason_intents_follows_intents_declaration_order():
    """Order is stable regardless of how the caller ordered its selection."""
    a = _by_key(recommend(["exploration", "training"]))["completeness"]
    b = _by_key(recommend(["training", "exploration"]))["completeness"]
    assert a["reason_intents"] == b["reason_intents"] == ["training", "exploration"]


def test_criticals_are_ordered_before_recommended():
    results = recommend(["training"])
    priorities = [r["priority"] for r in results]
    assert priorities == sorted(priorities, key=lambda p: 0 if p == "critical" else 1)


def test_within_a_priority_more_agreeing_intents_sorts_first():
    results = recommend(["training", "benchmarking", "exploration"])
    criticals = [r for r in results if r["priority"] == "critical"]
    counts = [len(r["reason_intents"]) for r in criticals]
    assert counts == sorted(counts, reverse=True)


def test_ordering_is_deterministic():
    assert recommend(["training", "publishing"]) == recommend(["training", "publishing"])


def test_no_duplicate_metrics_in_output():
    results = _metrics(recommend(list(intent.INTENT_KEYS)))
    assert len(results) == len(set(results))


def test_applicability_drops_correlations_on_a_single_column_dataset():
    profile = {"rows": 10, "columns": 1, "numerical": ["age"], "categorical": []}
    assert "correlations" not in _metrics(recommend(["exploration"], profile))


def test_applicability_drops_categorical_metrics_when_no_categorical_columns():
    profile = {"rows": 10, "columns": 3, "numerical": ["a", "b", "c"], "categorical": []}
    assert "class_imbalance" not in _metrics(recommend(["training"], profile))


def test_applicability_drops_numerical_metrics_when_no_numerical_columns():
    profile = {"rows": 10, "columns": 3, "numerical": [], "categorical": ["a", "b", "c"]}
    assert "skewness" not in _metrics(recommend(["exploration"], profile))


def test_none_profile_disables_all_filtering():
    """Cache-miss and Globus paths pass None; the filter must fail open."""
    results = _metrics(intent.recommend_metrics(["exploration"], None))
    assert "correlations" in results
    assert "skewness" in results


def test_temporal_completeness_survives_a_profile_with_no_datetime_information():
    results = _metrics(recommend(["curation"]))
    assert "temporal_completeness" in results


def test_is_applicable_returns_true_for_unknown_metric():
    assert intent.is_applicable("not_a_metric", FULL_PROFILE) is True


# --------------------------------------------------------------------------
# CHECKBOX_BY_METRIC drift guard
# --------------------------------------------------------------------------
#
# CHECKBOX_BY_METRIC names the checkbox the jump-to-metric feature looks for
# with a plain CSS selector. If a panel template renames a checkbox and this
# map is not updated, the highlight silently does nothing -- so every
# non-None entry must be checked against the literal template text, not just
# asserted to exist.


def test_every_recommendable_metric_has_a_checkbox_entry():
    assert set(intent.CHECKBOX_BY_METRIC) == intent.all_metric_keys()


def test_checkbox_names_exist_in_their_panel_template():
    for metric, checkbox_name in intent.CHECKBOX_BY_METRIC.items():
        if checkbox_name is None:
            continue
        panel = intent.PANEL_BY_METRIC[metric]
        template_path = PANELS_DIR / PANEL_TEMPLATE_FILE[panel]
        source = template_path.read_text(encoding="utf-8")
        assert f'name="{checkbox_name}"' in source, (
            f"{metric}: no checkbox named {checkbox_name!r} in {template_path.name}"
        )


def test_fair_assessment_has_no_checkbox():
    """Its panel is a metadata upload form, not a metric checkbox."""
    assert intent.CHECKBOX_BY_METRIC["fair_assessment"] is None


# --------------------------------------------------------------------------
# Intent goal checkbox regression guard
# --------------------------------------------------------------------------
#
# web/static/js/main.js runs every checkbox inside a ".checkboxContainer" or
# ".checkboxContainerIndividual" element through toggleValue(), which
# overwrites checkbox.value with the literal string "yes" or "no" -- that is
# the metric-toggle contract main.js was written for. The intent goal
# checkboxes are a multi-select whose value IS the semantic payload (e.g.
# "training", "publishing"); a styling pass once wrapped them in those same
# container classes to reuse the visual look, which silently clobbered
# every intent checkbox's value to "no" and made the recommendations
# request always fail with 400. The fix is to keep the "material-checkbox"
# look without the container ancestor. These tests keep that regression
# from coming back.


class _IntentCheckboxNestingParser(HTMLParser):
    """Walks a template's raw HTML/Jinja source and records, for every
    ``<input name="intent">``, whether any enclosing tag carries a
    metric-toggle container class.

    A plain stack of "open tag -> its class set" is enough here: Jinja's
    ``{% for %}``/``{% endfor %}`` tags are plain text to HTMLParser (they
    are not ``<...>`` tags), so they are simply ignored, and the single
    loop body in the template source is still well-formed HTML.
    """

    BAD_CLASSES = {"checkboxContainer", "checkboxContainerIndividual"}

    def __init__(self):
        super().__init__()
        self.stack: list[set[str]] = []
        self.bad_intent_values: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        if tag == "input" and attr_map.get("name") == "intent":
            ancestor_classes: set[str] = set().union(*self.stack, set())
            if ancestor_classes & self.BAD_CLASSES:
                self.bad_intent_values.append(attr_map.get("value"))
        self.stack.append(classes)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


def test_intent_checkboxes_are_not_nested_in_metric_toggle_containers():
    for name, path in INTENT_GOAL_TEMPLATES.items():
        parser = _IntentCheckboxNestingParser()
        parser.feed(path.read_text(encoding="utf-8"))
        assert parser.bad_intent_values == [], (
            f"{name}: intent checkbox(es) {parser.bad_intent_values} are "
            "nested inside a .checkboxContainer/.checkboxContainerIndividual "
            "element -- main.js's toggleValue() will overwrite their value "
            "with 'yes'/'no' on page load, destroying the intent key"
        )


def test_intent_templates_render_all_seven_intent_keys_as_checkbox_values():
    """Guards the template side of the contract: whatever markup change is
    made, each real intent key from aidrin.intent.INTENTS must still come
    out as a checkbox value once the template is actually rendered (the
    source only contains the Jinja loop variable, not the literal keys).

    The intent modal also renders one extra, hard-coded "Other / load a
    custom profile" checkbox alongside the seven looped ones -- it is the
    only place a saved profile can be loaded from. It is deliberately NOT an
    intent key (see the CUSTOM_PROFILE_OPTION_VALUE checks below), so it is
    asserted separately rather than folded into expected_values. The panel's
    inline "Change goal" card renders only the seven real goals: building or
    loading a profile from there happens via the panel's "Profiles" card and
    the modal, not an eighth checkbox.
    """
    expected_values = {entry["key"] for entry in intent.INTENTS}
    assert len(expected_values) == 7
    assert intent.CUSTOM_PROFILE_OPTION_VALUE not in intent.INTENT_KEYS

    templates_with_custom_option = {"intent_modal.html"}

    for name, path in INTENT_GOAL_TEMPLATES.items():
        template = jinja2.Environment(loader=jinja2.BaseLoader()).from_string(
            path.read_text(encoding="utf-8")
        )
        rendered = template.render(
            intent_options=intent.INTENTS,
            custom_profile_option_value=intent.CUSTOM_PROFILE_OPTION_VALUE,
        )
        rendered_values = set(re.findall(r'name="intent" value="([^"]+)"', rendered))
        expected = (
            expected_values | {intent.CUSTOM_PROFILE_OPTION_VALUE}
            if name in templates_with_custom_option
            else expected_values
        )
        assert rendered_values == expected, f"{name}: {rendered_values}"


# --------------------------------------------------------------------------
# recommendations_from_profile
# --------------------------------------------------------------------------


def _from_profile(profile, dataset_profile=None):
    return intent.recommendations_from_profile(profile, dataset_profile)


def test_profile_entries_have_the_documented_shape():
    profile = {"critical": ["completeness"], "recommended": []}
    results, dropped_unknown, dropped_inapplicable = _from_profile(profile)
    assert dropped_unknown == []
    assert dropped_inapplicable == []
    assert len(results) == 1
    entry = results[0]
    assert set(entry) == {
        "metric",
        "display_name",
        "panel",
        "panel_label",
        "priority",
        "source",
        "reason_intents",
        "why",
        "input_name",
    }
    assert entry["metric"] == "completeness"
    assert entry["source"] == "profile"
    assert entry["reason_intents"] == []
    assert entry["priority"] == "critical"
    assert entry["why"] == intent._fallback_why("completeness")


def test_metric_in_both_tiers_resolves_to_critical():
    profile = {"critical": ["completeness"], "recommended": ["completeness"]}
    results, _, _ = _from_profile(profile)
    assert len(results) == 1
    assert results[0]["priority"] == "critical"


def test_duplicates_within_one_list_collapse():
    profile = {"critical": ["completeness", "completeness"], "recommended": []}
    results, _, _ = _from_profile(profile)
    assert len(results) == 1


def test_unknown_metric_keys_are_dropped_and_reported():
    profile = {"critical": ["completeness", "not_a_metric"], "recommended": []}
    results, dropped_unknown, dropped_inapplicable = _from_profile(profile)
    assert [r["metric"] for r in results] == ["completeness"]
    assert dropped_unknown == ["not_a_metric"]
    assert dropped_inapplicable == []


def test_inapplicable_metrics_are_dropped_when_a_dataset_profile_is_given():
    categorical_only = {"rows": 10, "columns": 3, "numerical": [], "categorical": ["a", "b", "c"]}
    profile = {"critical": ["skewness"], "recommended": []}
    results, dropped_unknown, dropped_inapplicable = _from_profile(profile, categorical_only)
    assert results == []
    assert dropped_unknown == []
    assert dropped_inapplicable == ["skewness"]


def test_inapplicable_filter_is_disabled_when_dataset_profile_is_none():
    profile = {"critical": ["skewness"], "recommended": []}
    results, dropped_unknown, dropped_inapplicable = _from_profile(profile, None)
    assert [r["metric"] for r in results] == ["skewness"]
    assert dropped_inapplicable == []


def test_non_dict_profile_returns_empty_triple_without_raising():
    for bad in (None, "completeness", ["completeness"], 42):
        assert _from_profile(bad) == ([], [], [])


def test_profile_missing_keys_returns_empty_triple():
    assert _from_profile({}) == ([], [], [])
    assert _from_profile({"critical": ["completeness"]}) == ([], [], [])
    assert _from_profile({"recommended": ["completeness"]}) == ([], [], [])


def test_profile_non_list_values_return_empty_triple_without_raising():
    assert _from_profile({"critical": "completeness", "recommended": []}) == ([], [], [])
    assert _from_profile({"critical": [], "recommended": "completeness"}) == ([], [], [])
    assert _from_profile({"critical": {}, "recommended": []}) == ([], [], [])


def test_profile_ordering_matches_recommend_metrics_sort():
    """Same sort rule: critical first, then reason_intents length (0 for all
    profile entries, so a stable tiebreak), then panel, then metric key."""
    profile = {
        "critical": ["duplicity", "completeness"],
        "recommended": ["skewness", "kurtosis"],
    }
    results, _, _ = _from_profile(profile, FULL_PROFILE)
    priorities = [r["priority"] for r in results]
    assert priorities == sorted(priorities, key=lambda p: 0 if p == "critical" else 1)

    critical_metrics = [r["metric"] for r in results if r["priority"] == "critical"]
    assert critical_metrics == sorted(
        critical_metrics,
        key=lambda m: (intent.PANEL_BY_METRIC[m], m),
    )
    recommended_metrics = [r["metric"] for r in results if r["priority"] == "recommended"]
    assert recommended_metrics == sorted(
        recommended_metrics,
        key=lambda m: (intent.PANEL_BY_METRIC[m], m),
    )
