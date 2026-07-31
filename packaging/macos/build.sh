#!/usr/bin/env bash
# Build AIDRIN.app (and a .dmg) for macOS.
#
#   ./packaging/macos/build.sh
#
# Produces build/macos/dist/AIDRIN.app and build/macos/AIDRIN-<version>.dmg.
# The result is unsigned: see packaging/macos/README.md for the Gatekeeper caveat.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$REPO_ROOT/build/macos"
VENV="${AIDRIN_BUILD_VENV:-$BUILD_DIR/venv}"
PYTHON_VERSION="${AIDRIN_BUILD_PYTHON:-3.12}"

cd "$REPO_ROOT"
mkdir -p "$BUILD_DIR"

AIDRIN_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' aidrin/_version.py)"
export AIDRIN_VERSION

# 1. Build environment ------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> Creating build venv ($PYTHON_VERSION) at $VENV"
  uv venv --python "$PYTHON_VERSION" "$VENV"
  # pywebview (and the pyobjc it pulls in) provides the native window, Dock icon and
  # Quit menu; it is a build-time concern only, so it stays out of the project deps.
  VIRTUAL_ENV="$VENV" uv pip install -e "$REPO_ROOT" "pyinstaller>=6.10" "pywebview>=5.0"
fi

# 2. Icon -------------------------------------------------------------------
ICONSET="$BUILD_DIR/AIDRIN.iconset"
ICNS="$BUILD_DIR/AIDRIN.icns"
# packaging/macos/icon.png is the app icon. Without it, fall back to the in-app logo.
ICON_SRC="packaging/macos/icon.png"
[ -f "$ICON_SRC" ] || ICON_SRC="aidrin/images/logoNoBackground.png"
if [ ! -f "$ICNS" ] || [ "$ICON_SRC" -nt "$ICNS" ]; then
  echo "==> Generating icon from $ICON_SRC"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  # Square the source on its own canvas so macOS does not stretch a non-square image.
  SQUARE="$BUILD_DIR/icon-square.png"
  DIM=$(sips -g pixelHeight -g pixelWidth "$ICON_SRC" | awk '/pixel/ {print $2}' | sort -rn | head -1)
  sips -s format png --padToHeightWidth "$DIM" "$DIM" "$ICON_SRC" --out "$SQUARE" >/dev/null
  for size in 16 32 64 128 256 512; do
    sips -z $size $size "$SQUARE" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$SQUARE" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$ICNS"
fi
export AIDRIN_ICNS="$ICNS"

# 3. Bundle -----------------------------------------------------------------
echo "==> Running PyInstaller (this takes a few minutes)"
"$VENV/bin/pyinstaller" packaging/macos/aidrin.spec \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/work"

APP="$BUILD_DIR/dist/AIDRIN.app"
# Ad-hoc signature: without it macOS kills the freshly-modified bundle on Apple Silicon.
echo "==> Ad-hoc signing"
codesign --force --deep --sign - "$APP"

# 4. Disk image -------------------------------------------------------------
DMG="$BUILD_DIR/AIDRIN-$AIDRIN_VERSION.dmg"
echo "==> Building $DMG"
STAGE="$BUILD_DIR/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "AIDRIN $AIDRIN_VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo
echo "App: $APP"
echo "DMG: $DMG ($(du -sh "$DMG" | cut -f1))"
