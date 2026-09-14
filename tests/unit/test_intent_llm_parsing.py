"""Parsing and validation of the LLM recommendation response.

These tests must run without the openai package installed, so they import
only the pure helpers from web.llm.
"""

import inspect

from web.llm import (
    MAX_EXTRAS,
    RECOMMEND_SYSTEM_PROMPT,
    _build_user_content,
    parse_recommendation,
    validate_recommendation,
)
import web.llm as llm_module


VALID = """
{"summary": "Looks fine.",
 "rationales": {"completeness": "6 of 15 columns have nulls."},
 "extras": [{"metric": "k_anonymity", "why": "You mentioned releasing this."}]}
"""


def test_parses_bare_json():
    assert parse_recommendation(VALID)["summary"] == "Looks fine."


def test_parses_fenced_json():
    assert parse_recommendation(f"```json\n{VALID}\n```")["summary"] == "Looks fine."


def test_parses_json_with_surrounding_prose():
    text = f"Here is my answer:\n{VALID}\nHope that helps."
    assert parse_recommendation(text)["summary"] == "Looks fine."


def test_malformed_json_returns_none():
    assert parse_recommendation("{not json at all") is None


def test_empty_text_returns_none():
    assert parse_recommendation("") is None


def test_non_object_json_returns_none():
    assert parse_recommendation("[1, 2, 3]") is None


def _validate(raw, baseline=(), profile=None):
    return validate_recommendation(raw, list(baseline), profile)


def test_unknown_rationale_keys_are_dropped():
    out = _validate({"rationales": {"completeness": "ok", "not_a_metric": "nope"}})
    assert out["rationales"] == {"completeness": "ok"}


def test_unknown_extra_metrics_are_dropped():
    out = _validate({"summary": "ok", "extras": [{"metric": "not_a_metric", "why": "x"}]})
    assert out["extras"] == []


def test_extras_already_in_baseline_are_dropped():
    out = _validate(
        {"summary": "ok", "extras": [{"metric": "k_anonymity", "why": "x"}]},
        baseline=["k_anonymity"],
    )
    assert out["extras"] == []


def test_extras_are_capped():
    metrics = [
        "k_anonymity", "l_diversity", "t_closeness", "entropy_risk",
        "skewness", "kurtosis", "outliers", "duplicity",
    ]
    out = _validate({"extras": [{"metric": m, "why": "x"} for m in metrics]})
    assert len(out["extras"]) == MAX_EXTRAS


def test_extras_are_filtered_by_applicability():
    """A numerical-only dataset must not get a categorical extra."""
    profile = {"rows": 10, "columns": 3, "numerical": ["a", "b", "c"], "categorical": []}
    out = _validate(
        {"summary": "ok", "extras": [{"metric": "k_anonymity", "why": "x"}]},
        profile=profile,
    )
    assert out["extras"] == []


def test_long_strings_are_truncated():
    out = _validate({"summary": "x" * 5000, "rationales": {"completeness": "y" * 5000}})
    assert len(out["summary"]) <= 400
    assert len(out["rationales"]["completeness"]) <= 400


def test_extra_without_a_why_is_dropped():
    out = _validate({"summary": "ok", "extras": [{"metric": "k_anonymity"}]})
    assert out["extras"] == []


def test_non_dict_input_returns_none():
    assert _validate(None) is None
    assert _validate([1, 2]) is None


def test_response_that_validates_to_nothing_returns_none():
    assert _validate({"summary": "", "rationales": {}, "extras": []}) is None


def test_reply_whose_extras_all_validate_away_returns_none():
    """Nothing survived validation, so the caller must fall back to the curated list."""
    assert _validate({"extras": [{"metric": "not_a_metric", "why": "x"}]}) is None


def test_malformed_extras_entries_do_not_raise():
    out = _validate({"extras": ["a string", 42, {"metric": "k_anonymity", "why": "ok"}]})
    assert [e["metric"] for e in out["extras"]] == ["k_anonymity"]


def test_rationale_with_non_string_value_is_dropped():
    out = _validate({"rationales": {"completeness": {"nested": "object"}}, "summary": "ok"})
    assert out["rationales"] == {}


def test_extras_as_int_does_not_raise():
    """Regression: extras as a scalar int should degrade gracefully."""
    out = _validate({"summary": "ok", "extras": 42})
    assert out is not None
    assert out["extras"] == []


def test_extras_as_float_does_not_raise():
    """Regression: extras as a scalar float should degrade gracefully."""
    out = _validate({"summary": "ok", "extras": 3.14})
    assert out is not None
    assert out["extras"] == []


def test_extras_as_string_does_not_raise():
    """Regression: extras as a scalar string should degrade gracefully."""
    out = _validate({"summary": "ok", "extras": "not a list"})
    assert out is not None
    assert out["extras"] == []


def test_extras_as_dict_does_not_raise():
    """Regression: extras as a dict should degrade gracefully."""
    out = _validate({"summary": "ok", "extras": {"metric": "k_anonymity"}})
    assert out is not None
    assert out["extras"] == []


def test_validate_recommendation_with_scalar_extras():
    """End-to-end test: validate_recommendation must not raise on scalar extras."""
    result = validate_recommendation({"summary": "ok", "extras": 42}, [], None)
    assert result is not None
    assert result["extras"] == []


# ---------------------------------------------------------------------------
# Regression tests for the "fabricated results" prompt bug.
#
# The LLM enhancement layer previously produced summaries like "the dataset
# already passes key quality checks such as completeness..." even though no
# checks had actually been run. Root cause was ambiguous prompt wording
# ("the checks already selected for them" / "Already selected: ...") that a
# model could read as "these checks were already performed". These tests pin
# the corrected wording so it cannot silently regress.
# ---------------------------------------------------------------------------

def test_system_prompt_states_nothing_has_been_run():
    normalised = " ".join(RECOMMEND_SYSTEM_PROMPT.lower().split())
    assert "no checks have been run" in normalised
    assert "no results" in normalised


def test_system_prompt_forbids_pass_fail_claims():
    normalised = " ".join(RECOMMEND_SYSTEM_PROMPT.lower().split())
    assert "never state or imply that the dataset passes, fails" in normalised
    assert "you have no metric results" in normalised


def test_system_prompt_is_forward_looking():
    normalised = " ".join(RECOMMEND_SYSTEM_PROMPT.lower().split())
    assert "forward-looking, never retrospective" in normalised
    assert "what to do next, not what has been found" in normalised


def test_already_selected_phrase_removed_from_module():
    """The exact phrase that caused the fabrication bug must not reappear."""
    source = inspect.getsource(llm_module)
    assert "Already selected" not in source


def test_build_user_content_labels_baseline_as_not_yet_run():
    profile = {"rows": 10, "columns": 2, "numerical": ["a"], "categorical": ["b"]}
    content = _build_user_content(
        intents=["bias_fairness"],
        notes="testing",
        profile=profile,
        baseline=["completeness", "duplicity"],
    )
    assert "completeness, duplicity" in content
    assert "Already selected" not in content
    lowered = content.lower()
    assert "not yet run" in lowered
    assert "no results exist" in lowered


def test_build_user_content_profile_section_says_structural_only():
    profile = {"rows": 5, "columns": 1, "numerical": [], "categorical": ["x"]}
    content = _build_user_content(
        intents=[], notes=None, profile=profile, baseline=[],
    )
    lowered = content.lower()
    assert "structural metadata only" in lowered
    assert "not the result of any check" in lowered
