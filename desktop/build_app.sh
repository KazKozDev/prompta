#!/bin/bash
# Собирает "Prompta.app" — тонкий лончер, который запускает desktop/app.py
# системным python3 из репозитория. Никаких зависимостей для сборки не нужно.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/release/Prompta.app"
PYTHON="${PYTHON:-$(command -v python3)}"
NODE="$(command -v node || true)"

if [ -z "$NODE" ]; then
  echo "⚠️  node не найден в PATH — пайплайн не запустится. Установи Node.js 20+." >&2
fi

"$PYTHON" - <<'PY' || { echo "⚠️  PyQt6 не установлен. Выполни: python3 -m pip install PyQt6" >&2; exit 1; }
import PyQt6  # noqa: F401
PY

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# иконка: PNG → iconset → icns (sips и iconutil есть в macOS)
test -f "$ROOT/desktop/icon.png" || { echo "Нет desktop/icon.png" >&2; exit 1; }
ICON_TMP="$(mktemp -d)"
trap 'rm -rf "$ICON_TMP"' EXIT
ICONSET="$ICON_TMP/icon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
  sips -z $size $size "$ROOT/desktop/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z $double $double "$ROOT/desktop/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns"

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
# Тонкий лончер: работает из исходников, поэтому правки в коде подхватываются сразу.
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$PYTHON" "$ROOT/desktop/app.py" "\$@"
LAUNCH

chmod +x "$APP/Contents/MacOS/launch"

echo "✓ собрано: $APP"
echo "  запуск: open \"$APP\""
