"""Parsing and validation of the LLM recommendation response.

These tests must run without the openai package installed, so they import
only the pure helpers from web.llm.
"""

import inspect

from web.llm import (
    RECOMMEND_SYSTEM_PROMPT,
    _build_user_content,
    parse_recommendation,
    validate_selection,
)
import web.llm as llm_module


VALID = """
{"summary": "Here is what to check next.",
 "selection": [
   {"metric": "completeness", "priority": "critical", "why": "6 of 15 columns have nulls."},
   {"metric": "k_anonymity", "priority": "recommended", "why": "You mentioned releasing this."}
 ]}
"""


def test_parses_bare_json():
    assert parse_recommendation(VALID)["summary"] == "Here is what to check next."


def test_parses_fenced_json():
    assert parse_recommendation(f"```json\n{VALID}\n```")["summary"] == "Here is what to check next."


def test_parses_json_with_surrounding_prose():
    text = f"Here is my answer:\n{VALID}\nHope that helps."
    assert parse_recommendation(text)["summary"] == "Here is what to check next."


def test_malformed_json_returns_none():
    assert parse_recommendation("{not json at all") is None


def test_empty_text_returns_none():
    assert parse_recommendation("") is None


def test_non_object_json_returns_none():
    assert parse_recommendation("[1, 2, 3]") is None


def _validate(raw, profile=None):
    return validate_selection(raw, profile)


def test_valid_selection_survives_intact():
    out = _validate(
        {
            "summary": "ok",
            "selection": [
                {"metric": "completeness", "priority": "critical", "why": "ok"},
            ],
        }
    )
    assert out["selection"] == [{"metric": "completeness", "priority": "critical", "why": "ok"}]


def test_unknown_metric_keys_are_dropped():
    out = _validate(
        {
            "summary": "ok",
            "selection": [
                {"metric": "completeness", "priority": "critical", "why": "ok"},
                {"metric": "not_a_metric", "priority": "critical", "why": "nope"},
            ],
        }
    )
    assert [e["metric"] for e in out["selection"]] == ["completeness"]


def test_invalid_priority_is_coerced_to_recommended():
    out = _validate(
        {
            "summary": "ok",
            "selection": [{"metric": "completeness", "priority": "urgent!!", "why": "ok"}],
        }
    )
    assert out["selection"][0]["priority"] == "recommended"


def test_missing_priority_is_coerced_to_recommended():
    out = _validate(
        {"summary": "ok", "selection": [{"metric": "completeness", "why": "ok"}]}
    )
    assert out["selection"][0]["priority"] == "recommended"


def test_duplicate_metrics_collapse_to_first_occurrence():
    out = _validate(
        {
            "summary": "ok",
            "selection": [
                {"metric": "completeness", "priority": "critical", "why": "first"},
                {"metric": "completeness", "priority": "recommended", "why": "second"},
            ],
        }
    )
    assert len(out["selection"]) == 1
    assert out["selection"][0]["why"] == "first"
    assert out["selection"][0]["priority"] == "critical"


def test_selection_entries_are_filtered_by_applicability():
    """A metric the dataset provably cannot support is dropped regardless of
    what the model says -- a data-truth constraint, not an editorial one."""
    profile = {"rows": 10, "columns": 3, "numerical": ["a", "b", "c"], "categorical": []}
    out = _validate(
        {"summary": "ok", "selection": [{"metric": "k_anonymity", "priority": "critical", "why": "x"}]},
        profile=profile,
    )
    assert out is None


def test_long_strings_are_truncated():
    out = _validate(
        {
            "summary": "x" * 5000,
            "selection": [{"metric": "completeness", "priority": "critical", "why": "y" * 5000}],
        }
    )
    assert len(out["summary"]) <= 400
    assert len(out["selection"][0]["why"]) <= 400


def test_entry_without_a_why_is_dropped():
    out = _validate(
        {"summary": "ok", "selection": [{"metric": "completeness", "priority": "critical"}]}
    )
    assert out is None


def test_non_dict_input_returns_none():
    assert _validate(None) is None
    assert _validate([1, 2]) is None


def test_empty_selection_returns_none():
    assert _validate({"summary": "ok", "selection": []}) is None


def test_selection_that_validates_to_nothing_returns_none():
    """Nothing survived validation, so the caller must fall back to the curated list."""
    assert _validate({"selection": [{"metric": "not_a_metric", "priority": "critical", "why": "x"}]}) is None


def test_malformed_selection_entries_do_not_raise():
    out = _validate(
        {
            "selection": [
                "a string",
                42,
                {"metric": "k_anonymity", "priority": "critical", "why": "ok"},
            ]
        }
    )
    assert [e["metric"] for e in out["selection"]] == ["k_anonymity"]


def test_selection_as_int_does_not_raise():
    """Regression: selection as a scalar int should degrade gracefully."""
    assert _validate({"summary": "ok", "selection": 42}) is None


def test_selection_as_float_does_not_raise():
    """Regression: selection as a scalar float should degrade gracefully."""
    assert _validate({"summary": "ok", "selection": 3.14}) is None


def test_selection_as_string_does_not_raise():
    """Regression: selection as a scalar string should degrade gracefully."""
    assert _validate({"summary": "ok", "selection": "not a list"}) is None


def test_selection_as_dict_does_not_raise():
    """Regression: selection as a dict should degrade gracefully."""
    assert _validate({"summary": "ok", "selection": {"metric": "k_anonymity"}}) is None


def test_validate_selection_with_scalar_selection():
    """End-to-end test: validate_selection must not raise on a scalar selection."""
    assert validate_selection({"summary": "ok", "selection": 42}, None) is None


# ---------------------------------------------------------------------------
# Regression tests for the "fabricated results" prompt bug.
#
# The LLM recommendation layer previously produced summaries like "the
# dataset already passes key quality checks such as completeness..." even
# though no checks had actually been run. Root cause was ambiguous prompt
# wording ("the checks already selected for them" / "Already selected: ...")
# that a model could read as "these checks were already performed". These
# tests pin the corrected wording so it cannot silently regress.
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


def test_system_prompt_instructs_selecting_and_explaining_every_pick():
    normalised = " ".join(RECOMMEND_SYSTEM_PROMPT.lower().split())
    assert "select the checks that matter" in normalised
    assert "omit those that do not" in normalised
    assert "explain every check you" in normalised


def test_system_prompt_frames_curated_map_as_a_non_binding_starting_point():
    normalised = " ".join(RECOMMEND_SYSTEM_PROMPT.lower().split())
    assert "rule-based starting point" in normalised
    assert "not limited to the rule-based starting point" in normalised


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


def test_build_user_content_frames_baseline_as_a_non_binding_starting_point():
    content = _build_user_content(
        intents=["training"], notes=None, profile=None, baseline=["completeness"],
    )
    lowered = content.lower()
    assert "rule-based starting point" in lowered
    assert "reprioritise" in lowered


def test_build_user_content_profile_section_says_structural_only():
    profile = {"rows": 5, "columns": 1, "numerical": [], "categorical": ["x"]}
    content = _build_user_content(
        intents=[], notes=None, profile=profile, baseline=[],
    )
    lowered = content.lower()
    assert "structural metadata only" in lowered
    assert "not the result of any check" in lowered
