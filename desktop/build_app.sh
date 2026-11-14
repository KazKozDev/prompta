#!/bin/bash
# Builds "Prompta.app" — a thin launcher that runs desktop/app.py
# with the system python3 from the repository. The build needs no dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/release/Prompta.app"
PYTHON="${PYTHON:-$(command -v python3)}"
NODE="$(command -v node || true)"

if [ -z "$NODE" ]; then
  echo "⚠️  node is not on PATH — the pipeline will not run. Install Node.js 20+." >&2
fi

"$PYTHON" - <<'PY' || { echo "⚠️  PyQt6 is not installed. Run: python3 -m pip install PyQt6" >&2; exit 1; }
import PyQt6  # noqa: F401
PY

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# icon: PNG → iconset → icns (sips and iconutil ship with macOS)
test -f "$ROOT/desktop/icon.png" || { echo "desktop/icon.png is missing" >&2; exit 1; }
ICON_TMP="$(mktemp -d)"
trap 'rm -rf "$ICON_TMP"' EXIT
ICONSET="$ICON_TMP/icon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$ROOT/desktop/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z $double $double "$ROOT/desktop/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
if ! iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns"; then
  "$PYTHON" - "$ICONSET" "$APP/Contents/Resources/icon.icns" <<'ICNS'
import struct
import sys
from pathlib import Path

iconset, output = map(Path, sys.argv[1:])
entries = {
    b"icp4": "16x16", b"icp5": "32x32", b"ic07": "128x128",
    b"ic08": "256x256", b"ic09": "512x512", b"ic10": "512x512@2x",
    b"ic11": "16x16@2x", b"ic12": "32x32@2x",
    b"ic13": "128x128@2x", b"ic14": "256x256@2x",
}
chunks = []
for kind, size in entries.items():
    png = (iconset / f"icon_{size}.png").read_bytes()
    chunks.append(struct.pack(">4sI", kind, len(png) + 8) + png)
body = b"".join(chunks)
output.write_bytes(struct.pack(">4sI", b"icns", len(body) + 8) + body)
ICNS
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Prompta</string>
  <key>CFBundleDisplayName</key><string>Prompta</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>dev.prompta.pipeline</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSMicrophoneUsageDescription</key><string>Prompta uses the microphone for local Whisper dictation. Audio is not uploaded.</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSRequiresAquaSystemAppearance</key><true/>
  <key>CFBundleIconFile</key><string>icon</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/launch" <<LAUNCH
#!/bin/bash
# Thin launcher: it runs from the sources, so code changes take effect immediately.
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$PYTHON" "$ROOT/desktop/app.py" "\$@"
LAUNCH

chmod +x "$APP/Contents/MacOS/launch"

# Microphone helper: the launcher becomes the system Python, which has no microphone usage text, so macOS
# would silently hand dictation silence. prompta-mic carries its own Info.plist and asks for access itself.
if command -v clang >/dev/null && command -v codesign >/dev/null; then
  MIC_PLIST="$ICON_TMP/mic-Info.plist"
  cat > "$MIC_PLIST" <<MICPLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>dev.prompta.mic</string>
  <key>CFBundleName</key><string>Prompta Dictation</string>
  <key>NSMicrophoneUsageDescription</key><string>Prompta uses the microphone for local Whisper dictation. Audio is not uploaded.</string>
</dict>
</plist>
MICPLIST
  clang -O2 -Wall -o "$APP/Contents/MacOS/prompta-mic" "$ROOT/desktop/mic_helper.c" \
    -sectcreate __TEXT __info_plist "$MIC_PLIST"
  codesign --force --sign - --identifier dev.prompta.mic "$APP/Contents/MacOS/prompta-mic" 2>/dev/null
else
  echo "⚠️  clang/codesign not found — dictation may not get microphone access." >&2
fi

echo "✓ built: $APP"
echo "  run: open \"$APP\""
