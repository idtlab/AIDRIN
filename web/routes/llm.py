"""Flask routes for LLM-powered metric explanations.

All routes are under the ``/llm`` prefix. The blueprint is only
registered when the ``openai`` package is installed.
"""

import logging

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)
from web.llm import is_llm_available, explain_metric

logger = logging.getLogger(__name__)

llm_bp = Blueprint("llm", __name__, url_prefix="/llm")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@llm_bp.route("/status")
def status():
    """Check if LLM is available and configured."""
    config = session.get("llm_config")
    return jsonify({
        "available": is_llm_available(),
        "configured": bool(config and config.get("api_key")),
    })


@llm_bp.route("/configure", methods=["POST"])
def configure():
    """Store LLM configuration in the session.

    Expects JSON body:
    {
        "api_base": "https://api.openai.com/v1",
        "api_key": "sk-...",
        "model": "gpt-4o-mini"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    api_key = (data.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "API key is required"}), 400

    try:
        temperature = float(data.get("temperature") or 0.5)
    except (TypeError, ValueError):
        temperature = 0.5

    api_base = (data.get("api_base") or "https://api.openai.com/v1").strip()
    model = (data.get("model") or "gpt-4o-mini").strip()

    session["llm_config"] = {
        "api_base": api_base,
        "api_key": api_key,
        "model": model,
        "temperature": max(0.0, min(2.0, temperature)),
    }

    logger.info("LLM configured: model=%s, base=%s", model, api_base)
    return jsonify({"success": True})


@llm_bp.route("/disconnect", methods=["POST"])
def disconnect():
    """Clear LLM configuration from the session."""
    session.pop("llm_config", None)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


@llm_bp.route("/test", methods=["POST"])
def test_connection():
    """Test the LLM connection with a simple prompt.

    Expects JSON body with api_base, api_key, model.
    Does NOT save to session — just verifies the credentials work.
    """
    if not is_llm_available():
        return jsonify({"error": "openai package not installed"}), 400

    data = request.get_json()
    if not data or not data.get("api_key"):
        return jsonify({"error": "API key is required"}), 400

    try:
        import openai
        client = openai.OpenAI(
            base_url=(data.get("api_base") or "https://api.openai.com/v1").strip(),
            api_key=data["api_key"].strip(),
        )
        try:
            temp = float(data.get("temperature") or 0.5)
        except (TypeError, ValueError):
            temp = 0.5
        response = client.chat.completions.create(
            model=(data.get("model") or "gpt-4o-mini").strip(),
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=5,
            temperature=max(0.0, min(2.0, temp)),
        )
        reply = (response.choices[0].message.content or "").strip()
        logger.info("LLM test connection successful: %s", reply)
        return jsonify({"success": True, "reply": reply})
    except Exception as e:
        logger.warning("LLM test connection failed: %s", e)
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


@llm_bp.route("/explain", methods=["POST"])
def explain():
    """Generate an AI explanation for a metric result.

    Expects JSON body:
    {
        "metric_name": "Completeness",
        "description": "Indicates the proportion of available data...",
        "visualization": "<base64 PNG or data: URI>"
    }
    """
    config = session.get("llm_config")
    if not config or not config.get("api_key"):
        return jsonify({"error": "LLM not configured"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    description = data.get("description") or ""
    visualization = data.get("visualization") or ""
    metric_name = data.get("metric_name") or ""
    scores = data.get("scores")

    if not description and not visualization:
        return jsonify({"error": "At least description or visualization is required"}), 400

    # Build context: metric name + description + scores
    parts = []
    if metric_name:
        parts.append(f"Metric: {metric_name}.")
    if description:
        parts.append(description)
    if scores:
        import json
        scores_str = json.dumps(scores, indent=2, default=str)
        # Truncate if very large
        if len(scores_str) > 3000:
            scores_str = scores_str[:3000] + "\n... (truncated)"
        parts.append(f"Results:\n{scores_str}")
    full_description = " ".join(parts) if not scores else "\n\n".join(parts)

    try:
        explanation = explain_metric(full_description, visualization, config)
    except Exception as e:
        logger.error("LLM explain error: %s", e, exc_info=True)
        return jsonify({"error": "An internal error occurred"}), 500

    if not explanation:
        return jsonify({"error": "LLM returned an empty response"}), 500

    return jsonify({"explanation": explanation, "model": config.get("model", "")})


# ---------------------------------------------------------------------------
# Cache explanation
# ---------------------------------------------------------------------------


@llm_bp.route("/cache-explanation", methods=["POST"])
def cache_explanation():
    """Store an LLM explanation in the user-scoped metric cache entry.

    Expects JSON body:
    {
        "metric_name": "data_quality",
        "result_type": "Completeness",
        "explanation": "The dataset shows...",
        "model": "gpt-4o-mini"
    }
    """
    from web.routes.utils import get_current_user_id
    from flask import current_app

    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    metric_name = data.get("metric_name") or ""
    result_type = data.get("result_type") or ""
    explanation = data.get("explanation") or ""
    model = data.get("model") or ""

    if not metric_name or not explanation:
        return jsonify({"error": "metric_name and explanation are required"}), 400

    user_id = get_current_user_id()
    file_name = (
        session.get("uploaded_file_name")
        or session.get("globus_file_name")
        or ""
    )
    if not file_name:
        return jsonify({"error": "No file in session"}), 400

    cache_key = f"user:{user_id}:file:{file_name}:{metric_name}"
    entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if not entry:
        return jsonify({"error": "No cached entry found"}), 404

    # Store explanations keyed by result type (e.g., "Completeness", "Outliers")
    if "_llm_explanations" not in entry:
        entry["_llm_explanations"] = {}
    entry["_llm_explanations"][result_type] = {
        "explanation": explanation,
        "model": model,
    }

    return jsonify({"success": True})
