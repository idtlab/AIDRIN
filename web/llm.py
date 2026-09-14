"""Optional LLM integration for AI-generated metric explanations.

If the ``openai`` package is installed (``pip install aidrin[llm]``), users can
configure an OpenAI-compatible endpoint via the UI to receive AI-generated
explanations of metric results and visualizations.  When the package is **not**
installed the feature is hidden — zero overhead, zero behaviour change.
"""

import logging

logger = logging.getLogger(__name__)

_llm_available = False

try:
    import openai  # noqa: F401
    _llm_available = True
except ImportError:
    pass

SYSTEM_PROMPT = (
    "You are a data readiness expert. "
    "The user will provide a metric description and optionally a plot image. "
    "Reply with exactly 2-3 sentences: "
    "(1) summarize the key observations from the metric results, "
    "(2) state implications for AI/ML usage. "
    "Be direct and concise. Do not explain your reasoning process."
)


def is_llm_available():
    """Return True if the ``openai`` package is installed."""
    return _llm_available


def explain_metric(description, base64_image, config):
    """Call an OpenAI-compatible API with a metric description and plot image.

    Parameters
    ----------
    description : str
        Human-readable description of the metric (e.g. from the ``Description`` key).
    base64_image : str
        Base64-encoded PNG of the metric visualization.
    config : dict
        Must contain ``api_base``, ``api_key``, and ``model``.

    Returns
    -------
    str
        The LLM-generated explanation.

    Raises
    ------
    RuntimeError
        If the LLM SDK is not installed or the API call fails.
    """
    if not _llm_available:
        raise RuntimeError("openai package not installed")

    client = openai.OpenAI(
        base_url=config["api_base"],
        api_key=config["api_key"],
    )

    system_msg = SYSTEM_PROMPT

    if not description and not base64_image:
        raise RuntimeError("No description or visualization provided")

    # Build multimodal content (text + image)
    user_content = []
    if description:
        user_content.append({"type": "text", "text": description})
    if base64_image:
        image_url = base64_image if base64_image.startswith("data:") else f"data:image/png;base64,{base64_image}"
        user_content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })

    # Try with image first; if the model doesn't support vision it may
    # return an empty response or raise — fall back to text-only.
    last_response = None
    for attempt, content in enumerate([user_content, description]):
        if not content:
            continue
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": content},
                ],
                max_tokens=1024,
                temperature=config.get("temperature", 0.5),
            )
            last_response = response
            logger.debug("LLM response (attempt %d): choices=%s",
                         attempt, response.choices)

            if response.choices:
                msg = response.choices[0].message
                result = (msg.content or "").strip()
                if result:
                    if attempt > 0:
                        logger.info("LLM: vision not supported, used text-only fallback")
                    return result
                # Some APIs put the answer in a different field
                if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                    return msg.reasoning_content.strip()

        except Exception as e:
            logger.info("LLM attempt %d failed: %s", attempt, e)
            if attempt == 0 and description:
                continue
            raise

    # Build a diagnostic message
    diag = ""
    if last_response:
        try:
            diag = f" Raw response: {last_response.model_dump_json()[:500]}"
        except Exception:
            diag = f" choices={last_response.choices}"
    raise RuntimeError(f"Model returned empty content.{diag}")


# ---------------------------------------------------------------------------
# Intent-based metric recommendation
# ---------------------------------------------------------------------------

MAX_TEXT = 400
MAX_COLUMNS_IN_PROMPT = 50
MAX_COLUMN_NAME_LEN = 64

RECOMMEND_SYSTEM_PROMPT = (
    "You are a data readiness advisor. IMPORTANT: no checks have been run on this "
    "dataset. There are no results for any check, for any metric, for anything. "
    "Nothing has been evaluated, verified, quantified, passed, or failed. "
    "The user will tell you what they plan to do with a dataset, and you will be "
    "given a catalog of available checks, a short profile of the dataset's "
    "structure (not its quality), and a rule-based starting point -- a fixed "
    "mapping of goals to checks -- that also has no results and has not been run. "
    "Your job is to select the full list of checks the user should run NEXT, and "
    "to explain why each one matters for their stated goal.\n"
    "You are not limited to the rule-based starting point: you have more context "
    "than that fixed mapping does (the user's stated goals, their free-text notes, "
    "and the dataset's structure), so use it. Add checks the starting point omits "
    "if they matter here, drop checks it includes if they genuinely do not matter "
    "for this goal and this dataset, and set your own priority for each one you "
    "keep. Your selection replaces the starting point entirely -- whatever you "
    "return is what the user will see, so make it complete for their stated goals.\n"
    "Reply with a single JSON object and nothing else, in this exact shape:\n"
    '{"summary": "...", "selection": [{"metric": "<metric_key>", '
    '"priority": "critical"|"recommended", "why": "..."}]}\n'
    "Rules: use only metric keys from the catalog; select the checks that matter "
    "for the stated goals and omit those that do not; every entry in \"selection\" "
    "must carry a \"why\" of one or two sentences explaining why that check "
    "matters for THIS dataset and THIS goal -- you must explain every check you "
    "keep, not only the ones the starting point did not already suggest; if a "
    "check needs the user to nominate a column or supply rules, say so in its "
    "rationale. Do not invent metric names. Do not suggest column names.\n"
    "Strict prohibitions: never state or imply that the dataset passes, fails, "
    "is clean, is high quality, or has been evaluated, verified, or quantified "
    "in any way. You have no metric results — do not describe outcomes, scores, "
    "or findings, for this dataset or any check, run or unrun. Write only about "
    "what the user SHOULD check and WHY it matters for their stated goal: always "
    "forward-looking, never retrospective. The summary must describe what to do "
    "next, not what has been found."
)


def parse_recommendation(text):
    """Extract the JSON object from an LLM reply.

    Lenient because the endpoint may be any OpenAI-compatible API and
    ``response_format`` is not universally supported: strips code fences and
    locates the outermost object. Returns None if nothing parses.
    """
    import json

    if not text or not isinstance(text, str):
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        parsed = json.loads(cleaned[start:end + 1])
    except (ValueError, TypeError):
        return None

    return parsed if isinstance(parsed, dict) else None


def _clean_text(value):
    """Coerce to a trimmed, length-capped string, or None if not text."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:MAX_TEXT] if trimmed else None


def validate_selection(raw, profile=None):
    """Drop anything the model made up, keep the rest as-is.

    The LLM is the primary recommender: its selection is not overlaid onto a
    baseline and is not required to cover it. Metric keys must be real,
    priority is coerced to a valid value, every entry needs a non-empty
    ``why``, duplicates collapse to their first occurrence, and each pick
    still has to pass the same applicability filter the curated list uses --
    a metric the dataset provably cannot support (aidrin.intent.is_applicable)
    is dropped regardless of what the model says, since that is a data-truth
    constraint rather than an editorial one. Returns None when nothing in the
    selection survives.
    """
    from aidrin.intent import CRITICAL, RECOMMENDED, all_metric_keys, is_applicable

    if not isinstance(raw, dict):
        return None

    valid_keys = all_metric_keys()
    valid_priorities = (CRITICAL, RECOMMENDED)

    summary = _clean_text(raw.get("summary")) or ""

    raw_selection = raw.get("selection")
    if not isinstance(raw_selection, list):
        raw_selection = []

    selection = []
    seen = set()
    for entry in raw_selection:
        if not isinstance(entry, dict):
            continue
        metric = entry.get("metric")
        why = _clean_text(entry.get("why"))
        if not why or metric not in valid_keys or metric in seen:
            continue
        if not is_applicable(metric, profile):
            continue
        priority = entry.get("priority")
        if priority not in valid_priorities:
            priority = RECOMMENDED
        seen.add(metric)
        selection.append({"metric": metric, "priority": priority, "why": why})

    if not selection:
        return None

    return {"summary": summary, "selection": selection}


def _format_profile(profile):
    """Render the dataset profile for the prompt, capping column lists.

    This is structural metadata only (row/column counts, names, null counts) —
    it is not a result of any check and implies nothing about data quality.
    """
    if not profile:
        return "No dataset profile is available."

    lines = [
        "Structural metadata only — not the result of any check, and no "
        "indication of data quality:",
        f"Rows: {profile.get('rows', 'unknown')}",
        f"Columns: {profile.get('columns', 'unknown')}",
    ]
    for kind in ("numerical", "categorical"):
        names = profile.get(kind) or []
        shown = names[:MAX_COLUMNS_IN_PROMPT]
        suffix = f" (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
        shown_names = [str(n)[:MAX_COLUMN_NAME_LEN] for n in shown]
        lines.append(f"{kind.capitalize()} columns ({len(names)}): {', '.join(shown_names)}{suffix}")
    nulls = profile.get("columns_with_nulls")
    if nulls is not None:
        lines.append(f"Columns containing nulls: {nulls}")
    return "\n".join(lines)


def _build_user_content(intents, notes, profile, baseline):
    """Build the user-message content for the recommendation request.

    ``baseline`` is the curated, rule-based recommendation the user would get
    with no LLM connected -- sent purely as grounding the model may agree
    with, extend, trim, or reprioritise. It is not a floor: the model's own
    selection is what ships (see recommend_for_intent).

    Pure string assembly, kept separate from the network call so the exact
    wording sent to the model can be unit-tested without an API key.
    """
    from aidrin.intent import DESCRIPTIONS, INTENTS

    catalog = "\n".join(f"  {key}: {text}" for key, text in sorted(DESCRIPTIONS.items()))
    labels = {entry["key"]: entry["label"] for entry in INTENTS}
    goals = ", ".join(labels.get(key, key) for key in intents) or "(not specified)"

    return (
        f"Available checks:\n{catalog}\n\n"
        f"Dataset profile:\n{_format_profile(profile)}\n\n"
        f"User goals: {goals}\n"
        f"User notes: {notes or '(none)'}\n\n"
        f"Rule-based starting point (NOT yet run, no results exist for any of "
        f"these -- only a fixed mapping of goals to checks, not run and not a "
        f"requirement; you may add to it, remove from it, or reprioritise it): "
        f"{', '.join(baseline) or '(none)'}"
    )


def recommend_for_intent(intents, notes, profile, baseline, config):
    """Ask the LLM to select which checks the user should run next.

    The LLM is the primary recommender here: ``baseline`` (the curated,
    rule-based list) is sent only as grounding, never as a floor. Returns the
    validated ``{"summary", "selection"}`` dict, or None on any failure.
    Callers must treat None as "use the curated list instead" and must not
    merge a valid selection with the curated baseline -- the selection IS the
    recommendation list.
    """
    if not _llm_available:
        return None

    try:
        user_content = _build_user_content(intents, notes, profile, baseline)

        client = openai.OpenAI(base_url=config["api_base"], api_key=config["api_key"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": RECOMMEND_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=3000,
            temperature=config.get("temperature", 0.5),
        )
        if not response.choices:
            return None
        reply = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.info("LLM recommendation failed: %s", e)
        return None

    return validate_selection(parse_recommendation(reply), profile)
