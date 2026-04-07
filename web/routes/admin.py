import os

from flask import Blueprint, jsonify, redirect, send_from_directory

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/images/<path:filename>")
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, "..", "..", "aidrin", "images"), filename)


@admin_bp.route("/docs/<path:filename>")
def serve_docs(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, "..", "..", "docs"), filename)


@admin_bp.route("/docs")
def docs_index():
    return redirect("/docs/build/html/index.html")


@admin_bp.route("/publications", methods=["GET"])
def publications():
    from flask import render_template
    return render_template("publications.html")


@admin_bp.route("/view_logs")
def view_logs():
    # data/logs/ lives at the project root (two levels above web/routes/)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_path = os.path.join(project_root, "data", "logs", "aidrin.log")

    log_rows = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            for line in f:
                parts = line.strip().split(" | ", maxsplit=3)
                if len(parts) == 4:
                    timestamp, logger, level, message = parts
                    log_rows.append(
                        {"timestamp": timestamp, "logger": logger, "level": level, "message": message}
                    )
                else:
                    log_rows.append(
                        {"timestamp": "", "logger": "", "level": "", "message": line.strip()}
                    )
        return jsonify(log_rows)
    return jsonify({"error": "Log file not found."}), 404


@admin_bp.route("/class-imbalance-docs")
def class_imbalance_docs():
    return redirect("/docs/build/html/class_imbalance.html")


@admin_bp.route("/privacy-metrics-docs")
def privacy_metrics_docs():
    return redirect("/docs/build/html/privacy_metrics.html")
