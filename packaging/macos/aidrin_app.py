"""Entry point for the bundled macOS AIDRIN.app.

Serves the Flask UI on a free localhost port and shows it in a native window.
Celery runs in eager mode, so metrics execute in-process and no Redis broker or
worker is required. Everything the app writes goes under
``~/Library/Application Support/AIDRIN`` because the bundle itself is read-only.
"""

import os
import signal
import socket
import sys
import threading
import webbrowser
from pathlib import Path

APP_NAME = "AIDRIN"
STATE_DIR = Path.home() / "Library" / "Application Support" / APP_NAME


def configure_environment():
    """Point every writable path outside the bundle and disable the Celery broker."""
    dirs = {
        "AIDRIN_DATA_DIR": STATE_DIR,
        "AIDRIN_CUSTOM_METRICS_DIR": STATE_DIR / "custom_metrics",
        "MPLCONFIGDIR": STATE_DIR / "caches" / "matplotlib",
        "NUMBA_CACHE_DIR": STATE_DIR / "caches" / "numba",
        "XDG_CACHE_HOME": STATE_DIR / "caches",
    }
    for var, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(var, str(path))

    # Flask reads these via app.config.from_prefixed_env() into config["CELERY"],
    # so tasks run inline instead of being published to a broker.
    os.environ.setdefault("FLASK_CELERY__task_always_eager", "true")
    os.environ.setdefault("FLASK_CELERY__task_eager_propagates", "false")


def redirect_output():
    """A double-clicked .app has no terminal; keep a log we can point users at."""
    log_path = STATE_DIR / "launcher.log"
    stream = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = stream
    sys.stderr = stream
    return log_path


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_window = None


def run_window(url):
    """Show the UI in a native WebKit window. Blocks until the window is closed.

    Returns False when pywebview is unavailable (a source checkout without the build
    extras), leaving the caller to fall back to the default browser.
    """
    global _window

    if os.environ.get("AIDRIN_NO_WINDOW") == "1":
        return False
    try:
        import webview
        from webview.menu import Menu, MenuAction
    except ImportError:
        return False

    # WKWebView does not implement browser downloads, so keep an escape hatch for the
    # parts of the UI that hand the user a file.
    menu = [Menu(APP_NAME, [MenuAction("Open in Browser", lambda: webbrowser.open(url))])]

    _window = webview.create_window(APP_NAME, url, width=1280, height=860, min_size=(900, 600))
    webview.start(menu=menu)
    return True


def main():
    configure_environment()
    if getattr(sys, "frozen", False):
        redirect_output()

    from werkzeug.serving import make_server

    from web import create_app

    app = create_app()

    port = int(os.environ.get("AIDRIN_PORT") or free_port())
    server = make_server("127.0.0.1", port, app, threaded=True)
    url = f"http://127.0.0.1:{port}/"

    stopped = threading.Event()

    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
        stopped.set()
        # Python cannot run signal handlers while the Cocoa event loop has the main
        # thread, so closing the window has to be driven directly rather than by signal.
        if _window is not None:
            _window.destroy()

    @app.post("/__quit")
    def quit_app():
        threading.Timer(0.2, shutdown).start()
        return {"status": "shutting down"}

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"{APP_NAME} serving at {url}", flush=True)

    if run_window(url):
        # The window was closed: that is the app's quit signal.
        shutdown()
        return

    if os.environ.get("AIDRIN_NO_BROWSER") != "1":
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    stopped.wait()


if __name__ == "__main__":
    main()
