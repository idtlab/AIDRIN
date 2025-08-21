import os
import time
from celery import shared_task
from flask import current_app


@shared_task(name="delete_old_custom_metrics")
def delete_old_custom_metrics():
    """Delete old files in custom_metrics folder except __init__ and base_dr.py"""
    app = current_app._get_current_object()
    folder = app.config["CUSTOM_METRICS_FOLDER"]
    exclude = {"__init__.py", "base_dr.py"}
    now = time.time()

    for filename in os.listdir(folder):
        if filename in exclude:
            continue
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) and now - os.path.getmtime(file_path) > 3600:
                os.remove(file_path)
                print(f"[CLEANUP] Deleted stale file: {file_path}")
        except Exception as e:
            print(f"[CLEANUP] Failed to delete {file_path}: {e}")
