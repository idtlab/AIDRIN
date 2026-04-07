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
    session,
    url_for,
)
from aidrin.file_handling.file_parser import SUPPORTED_FILE_TYPES, READER_MAP, read_file
from web.routes.utils import (
    clear_all_user_cache,
    get_current_user_id,
    summary_histograms,
)

core_bp = Blueprint("core", __name__)

file_upload_time_log = logging.getLogger("file_upload")


@core_bp.route("/")
def homepage():
    return render_template("homepage.html")


@core_bp.route("/upload-file", methods=["GET", "POST"])
def upload_file():
    if request.method == "POST":
        file_upload_time_log.info("File upload initiated")
        file = request.files["file"]

        if file:
            cleared_count = clear_all_user_cache()
            print(f"Cache cleared for new file upload: {cleared_count} entries removed")

            display_name = file.filename
            filename = f"{uuid.uuid4().hex}_{file.filename}"
            file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            print(f"Saving file to {file_path}")
            file.save(file_path)

            session["uploaded_file_name"] = display_name
            session["uploaded_file_path"] = file_path
            session["uploaded_file_type"] = request.form.get("fileTypeSelector")

            return redirect(url_for("core.upload_file"))

    uploaded_file_name = session.get("uploaded_file_name", "")
    uploaded_file_path = session.get("uploaded_file_path", "")
    file_type = session.get("uploaded_file_type", "")

    file_upload_time_log.info("File Uploaded. Type: %s", file_type)

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
                    print(f"Error parsing file: {parse_error}")
                    file_preview = []

                current_checked_keys = session.get("selected_keys", [])
                if isinstance(current_checked_keys, str):
                    current_checked_keys = (
                        current_checked_keys.split(",") if current_checked_keys else []
                    )
                elif not isinstance(current_checked_keys, list):
                    current_checked_keys = []
        except Exception as e:
            print(f"Error generating file preview: {e}")
            file_preview = None
            current_checked_keys = None

    return render_template(
        "upload_file.html",
        uploaded_file_path=uploaded_file_path or "",
        uploaded_file_name=uploaded_file_name or "",
        file_type=file_type or "",
        supported_file_types=SUPPORTED_FILE_TYPES,
        file_preview=file_preview,
        current_checked_keys=current_checked_keys,
    )


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
    session.pop("uploaded_file_path", None)
    session.pop("uploaded_file_name", None)
    session.pop("uploaded_file_type", None)
    session.pop("minimize_preview", None)
    session.clear()

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    try:
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    except Exception as e:
        file_upload_time_log.info("File Clear Failure: Unable to clear folder")
        return jsonify({"success": False, "error": str(e)}), 500

    return redirect(url_for("core.upload_file"))


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
        print(f"Error in filter_file: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@core_bp.route("/my-cache", methods=["GET"])
def my_cache():
    try:
        user_id = get_current_user_id()
        cache = current_app.TEMP_RESULTS_CACHE
        user_cache_keys = [key for key in cache if key.startswith(f"user:{user_id}")]
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
        return jsonify({"success": False, "message": f"Error clearing cache: {str(e)}"}), 500


@core_bp.route("/summary-statistics", methods=["GET", "POST"])
def summary_statistics():
    if request.method == "POST":
        try:
            uploaded_file_path = session.get("uploaded_file_path")
            if uploaded_file_path and os.path.exists(uploaded_file_path):
                return redirect(url_for("core.summary_statistics"))
            return render_template("upload_file.html")
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    try:
        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")
        file_info = (file_path, file_name, file_type)
        df = read_file(file_info)

        summary_statistics = df.describe().applymap(
            lambda x: f"{x:.2e}" if abs(x) < 0.001 else round(x, 2)
        ).to_dict()

        histograms = summary_histograms(df)

        numerical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)
        ]
        categorical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_object_dtype(dtype)
        ]
        all_features = numerical_columns + categorical_columns

        for v in summary_statistics.values():
            for old_key in list(v.keys()):
                if old_key in ["25%", "50%", "75%"]:
                    new_key = old_key.replace("%", "th percentile")
                    v[new_key] = v.pop(old_key)

        response_data = {
            "success": True,
            "message": "File uploaded successfully",
            "records_count": len(df),
            "features_count": len(df.columns),
            "categorical_features": list(categorical_columns),
            "numerical_features": list(numerical_columns),
            "all_features": all_features,
            "summary_statistics": summary_statistics,
            "histograms": histograms,
        }
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@core_bp.route("/feature-set", methods=["POST"])
def extract_features():
    try:
        file_path = session.get("uploaded_file_path")
        file_name = session.get("uploaded_file_name")
        file_type = session.get("uploaded_file_type")
        file_info = (file_path, file_name, file_type)
        df = read_file(file_info)

        numerical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_numeric_dtype(dtype)
        ]
        categorical_columns = [
            col for col, dtype in df.dtypes.items() if pd.api.types.is_object_dtype(dtype)
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
        return jsonify({"success": False, "message": str(e)})
