#!/bin/zsh
# Build "Mac Enhancer.app" and a .dmg:  packaging/build_app.sh
#
# Needs the project's venv (torch, spandrel, pillow, numpy, tifffile, and tkinter via
# `brew install python-tk@3.12`) plus `pip install pyinstaller`. Use PYTHON=... for another
# interpreter, and PYTHONPATH if PyInstaller lives outside it.
#
# The app is signed ad hoc, which is what Apple Silicon needs to run a locally built app.
# It is NOT signed with a Developer ID or notarized, so a downloaded copy is stopped by
# Gatekeeper until the user opens it with right-click > Open. Set SIGN_ID to sign properly.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
VERSION=$($PY -c "import enhance; print(enhance.__version__)")

mkdir -p build dist
$PY packaging/make_icon.py build/MacEnhancer.icns
$PY packaging/collect_licenses.py build/THIRD_PARTY_LICENSES.txt
$PY -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/mac_enhancer.spec

APP="dist/Mac Enhancer.app"
rm -rf "dist/Mac Enhancer"   # PyInstaller's intermediate folder: the .app is the same content
codesign --force --deep --sign "${SIGN_ID:--}" "$APP"
codesign --verify --deep --strict "$APP"

STAGE=build/dmg-stage
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/MacEnhancer-$VERSION-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "Mac Enhancer $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "built: $APP"
echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
