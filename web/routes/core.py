import logging
import os
import uuid

import pandas as pd
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename
from aidrin.file_handling.file_parser import SUPPORTED_FILE_TYPES, READER_MAP
from web.routes.utils import (
    clear_all_user_cache,
    ensure_json_serializable,
    get_current_user_id,
    load_dataframe,
    summary_histograms,
)


core_bp = Blueprint("core", __name__)

file_upload_time_log = logging.getLogger("file_upload")


@core_bp.route("/")
def homepage():
    return redirect(url_for("core.inspector"))


@core_bp.route("/inspector", methods=["GET", "POST"])
def inspector():
    if request.method == "POST":
        file_upload_time_log.info("File upload initiated (workspace)")
        file = request.files["file"]

        if file:
            cleared_count = clear_all_user_cache()
            file_upload_time_log.info(
                "Cache cleared for new file upload: %d entries removed", cleared_count
            )

            display_name = file.filename
            filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            file.save(file_path)

            session["uploaded_file_name"] = display_name
            session["uploaded_file_path"] = file_path
            session["uploaded_file_type"] = request.form.get("fileTypeSelector")

            # Track files this session created so /clear removes only these,
            # never files belonging to other concurrent sessions.
            owned_files = session.get("owned_files", [])
            if file_path not in owned_files:
                owned_files.append(file_path)
            session["owned_files"] = owned_files

            return redirect(url_for("core.inspector"))

    uploaded_file_name = session.get("uploaded_file_name", "")
    uploaded_file_path = session.get("uploaded_file_path", "")
    file_type = session.get("uploaded_file_type", "")

    # Validate session: clear stale data if file no longer exists or type is missing
    if uploaded_file_path and (
        not os.path.exists(uploaded_file_path) or not file_type
    ):
        file_upload_time_log.warning(
            "Stale session detected (file=%s, type=%s). Clearing.",
            uploaded_file_path,
            file_type,
        )
        session.pop("uploaded_file_path", None)
        session.pop("uploaded_file_name", None)
        session.pop("uploaded_file_type", None)
        uploaded_file_path = ""
        uploaded_file_name = ""
        file_type = ""

    file_preview = None
    current_checked_keys = None

    if uploaded_file_path and file_type in [".h5", ".json", ".npz"]:
        try:
            if file_type in READER_MAP:
                reader = READER_MAP[file_type](uploaded_file_path, file_upload_time_log)
                try:
                    file_preview = reader.parse()
                    if file_preview and isinstance(file_preview, list):
                        file_preview = [str(key) for key in file_preview if key is not None]
                except Exception as parse_error:
                    file_upload_time_log.error("Error parsing file: %s", parse_error)
                    file_preview = []

                current_checked_keys = session.get("selected_keys", [])
                if isinstance(current_checked_keys, str):
                    current_checked_keys = (
                        current_checked_keys.split(",") if current_checked_keys else []
                    )
                elif not isinstance(current_checked_keys, list):
                    current_checked_keys = []
        except Exception as e:
            file_upload_time_log.error("Error generating file preview: %s", e)
            file_preview = None
            current_checked_keys = None

    # Check if Globus Compute is available
    from web.globus import is_globus_available
    globus_available = is_globus_available()

    # Check if LLM explanations are available
    from web.llm import is_llm_available
    llm_available = is_llm_available()
    llm_configured = bool(session.get("llm_config", {}).get("api_key"))
    globus_authenticated = session.get("globus_authenticated", False)

    # Globus remote file — treat as "uploaded" for sidebar/panels visibility
    globus_file_path = session.get("globus_file_path", "")
    globus_file_name = session.get("globus_file_name", "")
    globus_file_type = session.get("globus_file_type", "")
    globus_endpoint_id = session.get("globus_endpoint_id", "")
    globus_mode = bool(globus_file_path and globus_authenticated)

    # If Globus mode, use globus file info for template (shows sidebar + panels)
    effective_file_path = uploaded_file_path or globus_file_path
    effective_file_name = uploaded_file_name or globus_file_name
    effective_file_type = file_type or globus_file_type

    try:
        return render_template(
            "inspector.html",
            uploaded_file_path=effective_file_path or "",
            uploaded_file_name=effective_file_name or "",
            file_type=effective_file_type or "",
            supported_file_types=SUPPORTED_FILE_TYPES,
            file_preview=file_preview if file_preview is not None else [],
            current_checked_keys=current_checked_keys
            if current_checked_keys is not None
            else [],
            globus_available=globus_available,
            globus_authenticated=globus_authenticated,
            globus_mode=globus_mode,
            globus_endpoint_id=globus_endpoint_id,
            llm_available=llm_available,
            llm_configured=llm_configured,
        )
    except Exception as e:
        file_upload_time_log.error("Error rendering workspace: %s", e, exc_info=True)
        return "<h1>Workspace render error</h1>", 500


_SAMPLE_DATA_TYPES = {"csv", "json", "h5", "parquet", "xlsx", "npz", "dcat"}


@core_bp.route("/sample-data/<file_type>/<path:filename>")
def sample_data(file_type, filename):
    if file_type not in _SAMPLE_DATA_TYPES:
        return jsonify({"error": "Invalid file type"}), 400
    base = current_app.config["SAMPLE_DATA_FOLDER"]
    return send_from_directory(os.path.join(base, file_type), filename, as_attachment=True)


@core_bp.route("/upload-file", methods=["GET", "POST"])
def upload_file():
    """Legacy route — redirects to the inspector."""
    return redirect(url_for("core.inspector"))


@core_bp.route("/retrieve-uploaded-file", methods=["GET"])
def retrieve_uploaded_file():
    file_upload_time_log.info("Retrieving File")
    uploaded_file_path = session.get("uploaded_file_path")
    if uploaded_file_path:
        if os.path.exists(uploaded_file_path):
            file_upload_time_log.info("File Successfully Found")
            return send_file(uploaded_file_path, as_attachment=True)
        file_upload_time_log.info("File not found in os")
        return jsonify({"error": "File not found in os"}), 404
    file_upload_time_log.info("No file path found")
    return jsonify({"error": "No file path found"}), 404


@core_bp.route("/clear", methods=["GET", "POST"])
def clear_file():
    file_upload_time_log.info("Clearing File")

    # Cancel any active Globus Compute tasks and clear cached summary
    from web.globus import is_globus_available
    if is_globus_available():
        endpoint_id = session.get("globus_endpoint_id", "")
        file_path = session.get("globus_file_path", "")
        if endpoint_id and file_path:
            cache_key = f"globus_summary:{endpoint_id}:{file_path}"
            current_app.TEMP_RESULTS_CACHE.pop(cache_key, None)
        if session.get("globus_active_tasks"):
            try:
                from web.routes.globus import _cancel_active_globus_tasks
                _cancel_active_globus_tasks()
            except Exception as e:
                file_upload_time_log.warning("Failed to cancel Globus tasks on clear: %s", e)

    # Capture this session's own files before clearing the session.
    owned_files = session.get("owned_files", [])

    session.pop("uploaded_file_path", None)
    session.pop("uploaded_file_name", None)
    session.pop("uploaded_file_type", None)
    session.pop("minimize_preview", None)
    session.clear()

    try:
        for file_path in owned_files:
            if file_path and os.path.isfile(file_path):
                os.remove(file_path)
    except Exception:
        file_upload_time_log.error("File Clear Failure: Unable to clear files", exc_info=True)
        return jsonify({"success": False, "error": "An internal error occurred"}), 500

    return redirect(url_for("core.inspector"))


@core_bp.route("/filter-file", methods=["POST"])
def filter_file():
    try:
        data = request.get_json()
        keys = data.get("keys", "")

        if not keys:
            return jsonify({"success": False, "error": "No keys provided"}), 400

        if isinstance(keys, str):
            keys_list = [key.strip() for key in keys.split(",") if key.strip()]
        elif isinstance(keys, list):
            keys_list = [str(key) for key in keys if key]
        else:
            keys_list = [str(keys)]

        session["selected_keys"] = keys_list
        session["minimize_preview"] = True

        return jsonify({"success": True, "message": "File filtered successfully"})
    except Exception as e:
        file_upload_time_log.error("Error in filter_file: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "An internal error occurred"}), 500


@core_bp.route("/my-cache", methods=["GET"])
def my_cache():
    try:
        user_id = get_current_user_id()
        cache = current_app.TEMP_RESULTS_CACHE
        user_prefix = f"user:{user_id}"

        # Collect user-specific cached metric results (keyed with user: prefix)
        user_cache_keys = [key for key in cache if key.startswith(user_prefix)]

        # Also count transient result entries (UUID keys from store_result)
        transient_keys = [key for key in cache if not key.startswith("user:")]

        total_user_entries = len(user_cache_keys)
        global_cache_size = len(cache)
        user_cache_percentage = round(
            (total_user_entries / global_cache_size * 100) if global_cache_size > 0 else 0, 2
        )
        cache_info = {
            "user_id": user_id,
            "total_user_entries": total_user_entries,
            "global_cache_size": global_cache_size,
            "user_cache_percentage": user_cache_percentage,
            "user_cache_keys": user_cache_keys,
            "transient_entries": len(transient_keys),
        }
        return render_template("my_cache.html", cache_info=cache_info)
    except Exception as e:
        return render_template("my_cache.html", cache_info=None, error=str(e))


@core_bp.route("/clear-cache", methods=["POST"])
def clear_cache():
    try:
        removed_count = clear_all_user_cache()
        return jsonify(
            {
                "success": True,
                "message": f"Cache cleared successfully! Removed {removed_count} entries.",
                "removed_count": removed_count,
            }
        )
    except Exception as e:
        file_upload_time_log.error("Error clearing cache: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "An internal error occurred"}), 500


@core_bp.route("/cached-result/<metric_name>")
def cached_result(metric_name):
    """Return cached metric results for the current user and file, if available."""
    user_id = get_current_user_id()
    file_name = (
        session.get("uploaded_file_name")
        or session.get("globus_file_name")
        or ""
    )
    if not file_name:
        return jsonify({"cached": False})

    cache_key = f"user:{user_id}:file:{file_name}:{metric_name}"
    entry = current_app.TEMP_RESULTS_CACHE.get(cache_key)
    if entry and entry.get("data"):
        resp = {"cached": True, "data": entry["data"]}
        if entry.get("_llm_explanations"):
            resp["llm_explanations"] = entry["_llm_explanations"]
        return jsonify(resp)
    return jsonify({"cached": False})


@core_bp.route("/summary-statistics", methods=["GET", "POST"])
def summary_statistics():
    if request.method == "POST":
        try:
            uploaded_file_path = session.get("uploaded_file_path")
            if uploaded_file_path and os.path.exists(uploaded_file_path):
                return redirect(url_for("core.summary_statistics"))
            return redirect(url_for("core.inspector"))
        except Exception as e:
            file_upload_time_log.error("Error in summary_statistics POST: %s", e, exc_info=True)
            return jsonify({"success": False, "message": "An internal error occurred"})

    try:
        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")

        if not file_path or not os.path.exists(file_path):
            return jsonify({"success": False, "message": "No file uploaded or file not found"}), 200
        if not file_type:
            return jsonify({"success": False, "message": "File type not set in session"}), 200

        file_info = (file_path, file_name, file_type)
        df, load_error = load_dataframe(file_info)
        if load_error:
            return jsonify({"success": False, "message": load_error}), 200

        # Restrict to numeric columns: describe() would otherwise fall back to
        # object-column stats (top/freq are strings) and the numeric formatter
        # below would fail on them. Datasets with no numerical features simply
        # get an empty numerical summary (issue #125).
        numeric_df = df.select_dtypes(include="number")
        if numeric_df.shape[1] == 0:
            summary_statistics = {}
        else:
            summary_statistics = numeric_df.describe().map(
                lambda x: round(x, 2) if x == 0 or abs(x) >= 0.001 else f"{x:.2e}"
            ).to_dict()

        histograms = summary_histograms(df)

        # Booleans are treated as categorical (they're excluded from describe()
        # and select_dtypes("number") above, so they belong with the categorical
        # summary, not the numerical one).
        numerical_columns = [
            col for col, dtype in df.dtypes.items()
            if pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)
        ]
        categorical_columns = [
            col for col, dtype in df.dtypes.items()
            if pd.api.types.is_string_dtype(dtype) or pd.api.types.is_bool_dtype(dtype)
        ]
        all_features = numerical_columns + categorical_columns

        for v in summary_statistics.values():
            for old_key in list(v.keys()):
                if old_key in ["25%", "50%", "75%"]:
                    new_key = old_key.replace("%", "th percentile")
                    v[new_key] = v.pop(old_key)

        # Per-column summary for categorical features (describe() above only
        # covers numerical columns). Reports non-null count, distinct values,
        # the most frequent value, its frequency, and that frequency as a
        # percentage of the non-null values.
        categorical_summary = {}
        for col in categorical_columns:
            counts = df[col].value_counts(dropna=True)
            count = int(df[col].notna().sum())
            freq = int(counts.iloc[0]) if not counts.empty else 0
            categorical_summary[str(col)] = {
                "count": count,
                "unique": int(df[col].nunique(dropna=True)),
                "top": str(counts.index[0]) if not counts.empty else "—",
                "freq": freq,
                "freq_pct": round(freq / count * 100, 1) if count else 0.0,
            }

        response_data = ensure_json_serializable({
            "success": True,
            "message": "File uploaded successfully",
            "records_count": len(df),
            "features_count": len(df.columns),
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
            "summary_statistics": summary_statistics,
            "categorical_summary": categorical_summary,
            "histograms": histograms,
        })
        return jsonify(response_data)
    except Exception as e:
        file_upload_time_log.error("Error computing summary statistics: %s", e, exc_info=True)
        return jsonify({"success": False, "message": "An internal error occurred"})


@core_bp.route("/feature-set", methods=["POST"])
def extract_features():
    try:
        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")

        if not file_path or not os.path.exists(file_path):
            return jsonify({"success": False, "message": "No file uploaded or file not found"}), 200
        if not file_type:
            return jsonify({"success": False, "message": "File type not set in session"}), 200

        file_info = (file_path, file_name, file_type)
        df, load_error = load_dataframe(file_info)
        if load_error:
            return jsonify({"success": False, "message": load_error}), 200

        numerical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)
        ]
        categorical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_string_dtype(dtype)
        ]
        all_features = numerical_columns + categorical_columns

        class_imbalance_features = [
            col for col in all_features if df[col].nunique() <= 30
        ]

        response_data = {
            "success": True,
            "message": "File uploaded successfully",
            "records_count": len(df),
            "features_count": len(df.columns),
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
            "class_imbalance_features": class_imbalance_features,
        }
        return jsonify(response_data)
    except Exception as e:
        file_upload_time_log.error("Error extracting features: %s", e, exc_info=True)
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"})
