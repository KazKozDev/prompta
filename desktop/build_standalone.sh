#!/bin/bash
# Builds a self-contained "Prompta.app": its own Python, PyQt6 and Node, so it runs on a Mac with none of
# them installed. Unlike build_app.sh (a launcher over the sources), changes need a rebuild.
#
#   ./desktop/build_standalone.sh        → release/standalone/Prompta.app and release/standalone/Prompta.dmg
#
# Needs on the build Mac: python3 with PyQt6 and PyInstaller, and node ≥ 22.18 (an official build: it
# links only system libraries, so the binary is copied as is). Apple Silicon (arm64) only.
# Signed ad hoc, not notarized: on another Mac the first launch needs System Settings → Privacy & Security
# → Open Anyway. Dictation is left out (Whisper and its model are ~500 MB); the app says so.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/release/standalone"
PYTHON="${PYTHON:-$(command -v python3)}"
NODE="$(command -v node || true)"
[ -n "$NODE" ] || { echo "node is not on PATH" >&2; exit 1; }
NODE="$("$PYTHON" -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$NODE")"  # the binary, not a shim
"$PYTHON" -c 'import PyQt6, PyInstaller' 2>/dev/null \
  || { echo "Needs PyQt6 and PyInstaller: $PYTHON -m pip install PyQt6 pyinstaller" >&2; exit 1; }
if otool -L "$NODE" | tail -n +2 | grep -vqE '^\s*/(System|usr/lib)/'; then
  echo "$NODE links libraries outside the system (a Homebrew build?); use an official build from nodejs.org" >&2
  exit 1
fi
VERSION="$("$PYTHON" -c 'import sys; sys.path.insert(0, sys.argv[1]); import ast; src = open(sys.argv[1] + "/app.py").read(); print(next(n.value.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "APP_VERSION"))' "$ROOT/desktop")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The runtime tree, laid out like the repository (the app finds it as ROOT): tracked files only, no tests,
# so nothing personal (providers.local.json) or generated rides along.
STAGE="$WORK/prompta"
mkdir -p "$STAGE"
(cd "$ROOT" && git ls-files package.json pipeline mcp catalog '*_prompt_rules' hermes_agent_prompt_guides \
   open_model_prompt_guides desktop/bridge.ts desktop/app.qss 'desktop/*.svg' 'desktop/*.png' \
   | grep -vE '\.test\.ts$|\.py$' > "$WORK/files")
rsync -a --files-from="$WORK/files" "$ROOT" "$STAGE"

# Icon
ICONSET="$WORK/icon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$ROOT/desktop/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) "$ROOT/desktop/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$WORK/icon.icns"

rm -rf "$OUT"
"$PYTHON" -m PyInstaller --noconfirm --log-level WARN --windowed --name Prompta \
  --icon "$WORK/icon.icns" --osx-bundle-identifier dev.prompta.pipeline \
  --paths "$ROOT/desktop" --add-data "$STAGE:prompta" --add-binary "$NODE:." \
  --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick --exclude-module PyQt6.QtMultimedia \
  --exclude-module PyQt6.QtPdf --exclude-module PyQt6.QtWebEngineCore --exclude-module tkinter \
  --distpath "$OUT" --workpath "$WORK/build" --specpath "$WORK" \
  "$ROOT/desktop/app.py"
APP="$OUT/Prompta.app"
rm -rf "$OUT/Prompta"  # PyInstaller's loose copy next to the .app

PLIST="$APP/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace NSRequiresAquaSystemAppearance -bool true "$PLIST"  # app.qss is light only
plutil -replace NSHighResolutionCapable -bool true "$PLIST"
# The oldest macOS every bundled binary supports (node and Qt each declare one).
MINOS="$(for binary in "$APP/Contents/Frameworks/node" "$APP/Contents/Frameworks/PyQt6/Qt6/lib/QtCore.framework/QtCore"; do
  otool -l "$binary" | awk '/LC_BUILD_VERSION/{found=1} found && /minos/{print $2; exit}'
done | sort -V | tail -1)"
plutil -replace LSMinimumSystemVersion -string "${MINOS:-12.0}" "$PLIST"

codesign --force --deep --sign - "$APP"  # ad hoc: the plist edits broke PyInstaller's seal
codesign --verify --deep --strict "$APP"

hdiutil create -quiet -volname Prompta -srcfolder "$APP" -ov -format UDZO "$OUT/Prompta.dmg"

echo "✓ built: $APP ($(du -sh "$APP" | cut -f1)), $OUT/Prompta.dmg ($(du -sh "$OUT/Prompta.dmg" | cut -f1))"
echo "  macOS ${MINOS:-12.0}+, arm64, signed ad hoc (not notarized)"
