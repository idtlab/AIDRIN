import os
import time
from celery import shared_task
from flask import current_app


def prune_upload_folder(folder, max_age_seconds, now):
    """Delete files in ``folder`` older than ``max_age_seconds`` relative to ``now``.

    Covers both uploaded sources and their ``.aidrin.feather`` cache sidecars
    (every plain file in the upload folder is eligible). Subdirectories are left
    untouched. Returns the number of files removed. Pure and side-effect-scoped
    so it can be unit-tested without Flask/Celery.
    """
    removed = 0
    if not os.path.isdir(folder):
        return removed
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > max_age_seconds:
                os.remove(file_path)
                removed += 1
                print(f"[CLEANUP] Deleted stale upload: {file_path}")
        except Exception as e:
            print(f"[CLEANUP] Failed to delete {file_path}: {e}")
    return removed


@shared_task(name="delete_old_uploads")
def delete_old_uploads():
    """Periodically reap aged uploads and their Feather cache sidecars.

    The startup cleanup in ``create_app`` only runs once per process; this task
    keeps ``UPLOAD_FOLDER`` bounded on long-running servers.
    """
    app = current_app._get_current_object()
    folder = app.config.get("UPLOAD_FOLDER")
    if not folder:
        return
    prune_upload_folder(folder, max_age_seconds=3600, now=time.time())


def _is_generated_custom_metric_script(filename):
    """True for session-generated scripts (customDR_<uuid>.py), which is the
    only thing this cleanup should ever touch in CUSTOM_METRICS_FOLDER.

    That folder also holds permanent package source (__init__.py, base_dr.py,
    template.py, ...). An exclude-list of "known good" filenames is fragile —
    it silently deletes any new source file added later that nobody remembers
    to add to the list (this previously deleted template.py). Matching the
    actual generated-file naming pattern instead is a positive, self-updating
    invariant: only what the web route actually generates is ever eligible.
    """
    return filename.startswith("customDR_") and filename.endswith(".py")


def prune_custom_metrics_folder(folder, max_age_seconds, now):
    """Delete session-generated custom metric scripts older than the threshold.

    Pure and side-effect-scoped so it can be unit-tested without Flask/Celery,
    mirroring ``prune_upload_folder``. Returns the number of files removed.
    """
    removed = 0
    if not os.path.isdir(folder):
        return removed
    for filename in os.listdir(folder):
        if not _is_generated_custom_metric_script(filename):
            continue
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > max_age_seconds:
                os.remove(file_path)
                removed += 1
                print(f"[CLEANUP] Deleted stale custom metric: {file_path}")
        except Exception as e:
            print(f"[CLEANUP] Failed to delete {file_path}: {e}")
    return removed


@shared_task(name="delete_old_custom_metrics")
def delete_old_custom_metrics():
    """Delete old files in custom_metrics and remedy_data folders except __init__ and base_dr.py"""
    app = current_app._get_current_object()
    folder = app.config["CUSTOM_METRICS_FOLDER"]
    remedy_folder = app.config.get("REMEDY_FOLDER", os.path.join(folder, "remedy_data"))
    now = time.time()

    prune_custom_metrics_folder(folder, max_age_seconds=3600, now=now)

    # Cleanup remedy_data
    if os.path.exists(remedy_folder):
        for filename in os.listdir(remedy_folder):
            file_path = os.path.join(remedy_folder, filename)
            try:
                if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > 3600:
                    os.remove(file_path)
                    print(f"[CLEANUP] Deleted stale remedy file: {file_path}")
            except Exception as e:
                print(f"[CLEANUP] Failed to delete {file_path}: {e}")
