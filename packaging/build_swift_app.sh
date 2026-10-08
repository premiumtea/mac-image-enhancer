#!/bin/zsh
# Build "Mac Image Enhancer.app": the SwiftUI window, plus (unless SKIP_ENGINE=1) the Python engine inside it.
#
#   packaging/build_swift_app.sh               # dist/Mac Image Enhancer.app, with the engine (needs pyinstaller)
#   SKIP_ENGINE=1 packaging/build_swift_app.sh # the window only (screenshots, quick checks; run with
#                                              # MAC_IMAGE_ENHANCER_ENGINE="python|enhance.py" to use a checkout's engine)
#
# Needs Xcode 26 (the Liquid Glass APIs), and the project's venv for the version, the icon and the engine.
# The app is signed ad hoc, which is what Apple Silicon needs to run a locally built app. Set SIGN_ID to sign properly.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
VERSION=$($PY -c "import enhance; print(enhance.__version__)")
NAME="Mac Image Enhancer"
APP="dist/$NAME.app"

$PY packaging/gen_swift.py --check
mkdir -p build dist
$PY packaging/make_icon.py build/MacImageEnhancer.icns
(cd app && swift build -c release --arch arm64)
BIN="$(cd app && swift build -c release --arch arm64 --show-bin-path)/MacImageEnhancer"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/MacImageEnhancer"
cp build/MacImageEnhancer.icns "$APP/Contents/Resources/"
cp LICENSE NOTICE "$APP/Contents/Resources/"
sed "s/__VERSION__/$VERSION/g" packaging/Info.plist.in > "$APP/Contents/Info.plist"

if [ -z "${SKIP_ENGINE:-}" ]; then
  $PY packaging/collect_licenses.py build/THIRD_PARTY_LICENSES.txt
  $PY -m PyInstaller --noconfirm --clean --distpath build/engine-dist --workpath build/pyinstaller packaging/engine.spec
  cp -R build/engine-dist/mac-image-enhancer-engine "$APP/Contents/Resources/engine"
  cp build/THIRD_PARTY_LICENSES.txt "$APP/Contents/Resources/"
fi

codesign --force --deep --sign "${SIGN_ID:--}" "$APP"
codesign --verify --deep --strict "$APP"
echo "built: $APP ($(du -sh "$APP" | cut -f1))"

if [ -z "${SKIP_DMG:-}" ] && [ -z "${SKIP_ENGINE:-}" ]; then
  STAGE=build/dmg-stage
  rm -rf "$STAGE" && mkdir -p "$STAGE"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  DMG="dist/MacImageEnhancer-$VERSION-arm64.dmg"
  rm -f "$DMG"
  hdiutil create -volname "$NAME $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
  echo "built: $DMG ($(du -h "$DMG" | cut -f1))"
fi
