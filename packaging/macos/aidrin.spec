# PyInstaller spec for the macOS AIDRIN.app bundle. Build via packaging/macos/build.sh.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = Path(SPECPATH).parents[1]  # noqa: F821 - SPECPATH is injected by PyInstaller

datas = [
    (str(REPO / "web" / "templates"), "web/templates"),
    (str(REPO / "web" / "static"), "web/static"),
    (str(REPO / "aidrin" / "images"), "aidrin/images"),
    (str(REPO / "examples" / "sample_data"), "examples/sample_data"),
]
binaries = []

# Our own packages: the metric modules and route blueprints are wired together in
# ways PyInstaller's static analysis does not always follow.
hiddenimports = (
    collect_submodules("aidrin")
    + collect_submodules("web")
    + collect_submodules("worker")
)

# Third-party packages that ship data files or import submodules dynamically.
# webview/AppKit provide the native window; without them the launcher falls back to a browser.
for package in ("shap", "dython", "pgeocode", "numba", "llvmlite", "celery", "kombu", "sklearn",
                "webview", "AppKit", "WebKit", "Foundation", "objc"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Optional integrations are resolved at runtime by is_*_available() probes; leaving them
# out keeps the bundle smaller and the probes simply report "not installed".
excludes = [
    "globus_sdk", "globus_compute_sdk", "openai", "langchain", "faiss", "fitz",
    "opentelemetry", "IPython", "notebook", "pytest", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
]

a = Analysis(  # noqa: F821
    [str(REPO / "packaging" / "macos" / "aidrin_app.py")],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AIDRIN",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AIDRIN",
)

app = BUNDLE(  # noqa: F821
    coll,
    name="AIDRIN.app",
    icon=os.environ.get("AIDRIN_ICNS") or None,
    bundle_identifier="org.idtlab.aidrin",
    version=os.environ.get("AIDRIN_VERSION", "0.0.0"),
    info_plist={
        "CFBundleName": "AIDRIN",
        "CFBundleDisplayName": "AIDRIN",
        "CFBundleShortVersionString": os.environ.get("AIDRIN_VERSION", "0.0.0"),
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # The UI is a browser tab, but keep the Dock icon so the app can be quit normally.
        "LSUIElement": False,
    },
)
