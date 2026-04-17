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
