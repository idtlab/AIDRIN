import importlib
import importlib.util
import logging
import os
import runpy
import sys
import time
import uuid

import pandas as pd
from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    request,
    send_from_directory,
    session,
    url_for,
)
from aidrin.file_handling.file_parser import read_file
from web.routes.utils import ensure_json_serializable, store_result, get_result_or_default

custom_bp = Blueprint("custom", __name__)

metric_time_log = logging.getLogger("metric")

_STARTER_TEMPLATE = '''from aidrin.custom_metrics.base_dr import BaseDRAgent
from typing import Any, Dict, Union

class CustomDR(BaseDRAgent):
    def __init__(self, dataset: Any, **kwargs):
        super().__init__(dataset, **kwargs)

    def metric(self, **kwargs):
        """
        Implement your custom metric logic here.
        """

        # IMPLEMENT YOUR METRIC LOGIC BELOW
        # Example: Calculating the total number of missing cells in the entire DataFrame

        # df: pd.DataFrame = self.dataset
        # return {
        #     "total_missing_cells": df.isna().sum().to_dict()
        # }

        return {"message": "Placeholder metric. Implement your logic here."}

    def remedy(self, metric_results: dict):
        """
        Applies custom remediation logic based on the calculated metrics.
        """

        # IMPLEMENT YOUR REMEDIATION LOGIC BELOW
        # For example, filling null values with a default value

        # df_remedied: pd.DataFrame = self.dataset.copy()
        # df_remedied.fillna(0, inplace=True)
        # return df_remedied

        return self.dataset
'''


@custom_bp.route("/custom-metrics", methods=["GET", "POST"])
def custom_metrics():
    final_dict = {}
    data_file_path = session.get("uploaded_file_path")
    data_file_name = session.get("uploaded_file_name")
    data_file_type = session.get("uploaded_file_type")
    file_info = (data_file_path, data_file_name, data_file_type)

    if request.method == "POST":
        metric_time_log.info("Custom Metric Evaluation Request Started")
        start_time = time.time()

        module_name = None
        folder = None
        try:
            df = read_file(file_info)
            final_dict["Custom Metric Evaluation"] = {}

            folder = current_app.config.get("CUSTOM_METRICS_FOLDER", "custom_metrics")
            if "session_id" not in session:
                session["session_id"] = str(uuid.uuid4())
            filename = f"customDR_{session['session_id']}.py"
            custom_metric_file_path = os.path.join(folder, filename)

            if not os.path.exists(custom_metric_file_path):
                return jsonify({"error": f"{filename} not found"}), 400

            if folder not in sys.path:
                sys.path.insert(0, folder)

            module_name = f"customDR_{session['session_id']}_module"
            spec = importlib.util.spec_from_file_location(module_name, custom_metric_file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            from aidrin.custom_metrics.base_dr import BaseDRAgent

            custom_metric_class = getattr(module, "CustomDR", None)
            if not custom_metric_class or not issubclass(custom_metric_class, BaseDRAgent):
                return jsonify({"error": "CustomDR class not found or invalid"}), 400

            custom_metric_instance = custom_metric_class(dataset=df)
            metric_results = custom_metric_instance.metric()
            if not isinstance(metric_results, dict):
                return jsonify(
                    {"error": f"{custom_metric_class.__name__}.metric() must return a dictionary"}
                ), 400

            module_globals = runpy.run_path(custom_metric_file_path)

            custom_metric_class = module_globals.get("CustomDR")
            if not custom_metric_class or not issubclass(custom_metric_class, BaseDRAgent):
                return jsonify({"error": "CustomDR class not found or invalid"}), 400

            instance = custom_metric_class(dataset=df)
            metric_results = instance.metric()
            if not isinstance(metric_results, dict):
                return jsonify({"error": "metric() must return a dictionary"}), 400

            final_dict["Custom Metric Evaluation"] = metric_results

            if request.form.get("apply_remedy") == "yes":
                new_data = custom_metric_instance.remedy(metric_results)

                if not isinstance(new_data, pd.DataFrame):
                    return jsonify({"error": "remedy() must return a pandas DataFrame"}), 400

                remedy_folder = current_app.config["REMEDY_FOLDER"]
                os.makedirs(remedy_folder, exist_ok=True)

                remedy_filename = f"remedied_{session['session_id']}{data_file_type}"
                remedy_filepath = os.path.join(remedy_folder, remedy_filename)
                new_data.to_csv(remedy_filepath, index=False)

                final_dict["Custom Metric Evaluation"]["apply_remedy"] = url_for(
                    "custom.download_remedy", filename=remedy_filename
                )

            final_dict = ensure_json_serializable(final_dict)

        except Exception as e:
            metric_time_log.error(f"Error: {str(e)}")
            return jsonify({"error": str(e)}), 500

        finally:
            if module_name and module_name in sys.modules:
                del sys.modules[module_name]
            if folder and folder in sys.path:
                sys.path.remove(folder)

        metric_time_log.info(
            f"Custom Metric Evaluation Execution time: {time.time() - start_time:.2f} seconds"
        )
        return store_result("custom.custom_metrics", final_dict)

    return get_result_or_default("custom.custom_metrics", data_file_path, data_file_name)


@custom_bp.route("/download-remedy/<filename>")
def download_remedy(filename):
    remedy_folder = current_app.config["REMEDY_FOLDER"]
    return send_from_directory(remedy_folder, filename, as_attachment=True)


@custom_bp.route("/load-custom-metric", methods=["GET"])
def load_custom_metric():
    folder = current_app.config.get("CUSTOM_METRICS_FOLDER", "custom_metrics")
    os.makedirs(folder, exist_ok=True)

    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    filename = f"customDR_{session['session_id']}.py"
    file_path = os.path.join(folder, filename)

    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_STARTER_TEMPLATE)

    with open(file_path, encoding="utf-8") as f:
        code = f.read()

    response = make_response(code)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@custom_bp.route("/save-custom-metric-text", methods=["POST"])
def save_custom_metric_text():
    code = request.form.get("metric_code")
    if not code:
        return jsonify({"error": "No code provided"}), 400

    folder = current_app.config.get("CUSTOM_METRICS_FOLDER", "custom_metrics")
    os.makedirs(folder, exist_ok=True)

    filename = f"customDR_{session['session_id']}.py"
    file_path = os.path.join(folder, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(code)

    return jsonify({"message": "Custom metric saved successfully"})
