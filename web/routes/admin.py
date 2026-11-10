import os

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, send_from_directory

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/images/<path:filename>")
def serve_image(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, "..", "..", "aidrin", "images"), filename)


@admin_bp.route("/docs/<path:filename>")
def serve_docs(filename):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(root_dir, "..", "..", "docs"), filename)


HOSTED_DOCS = "https://aidrin.readthedocs.io/en/latest/"


def docs_url(page, anchor=""):
    """URL for a documentation page: the local Sphinx build if it was built, else the hosted docs.

    ``/docs/<path>`` serves the repository's ``docs/`` directory, so the local
    HTML only exists for a checkout where someone ran ``make html``; it is
    absent from a plain install. Falling back to readthedocs keeps these links
    working everywhere instead of serving a 404.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(root_dir, "..", "..", "docs", "build", "html", page)
    if os.path.exists(local):
        return f"/docs/build/html/{page}{anchor}"
    return f"{HOSTED_DOCS}{page}{anchor}"


@admin_bp.route("/docs")
def docs_index():
    return redirect(docs_url("index.html"))


@admin_bp.route("/publications", methods=["GET"])
def publications():
    from flask import render_template
    return render_template("publications.html")


@admin_bp.route("/logs")
def logs_page():
    if not current_app.config.get("ENABLE_LOG_VIEWER"):
        abort(403)
    return render_template("logs.html")


@admin_bp.route("/view-logs")
def view_logs():
    if not current_app.config.get("ENABLE_LOG_VIEWER"):
        abort(403)
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
    # class_imbalance.html has never existed; the metric is documented under
    # the Fairness and Bias section of the web usage page.
    return redirect(docs_url("web_usage.html", "#fairness-and-bias"))


@admin_bp.route("/privacy-metrics-docs")
def privacy_metrics_docs():
    # privacy_metrics.html has never existed; these metrics are documented
    # under the Data Governance section of the web usage page.
    return redirect(docs_url("web_usage.html", "#data-governance"))
