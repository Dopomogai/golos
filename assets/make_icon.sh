#!/bin/bash
# Build golos.icns from the generated 1024px PNG (variant A by default).
set -euo pipefail
cd "$(dirname "$0")/.."

VARIANT="${1:-A}"

.venv/bin/python assets/make_icon.py

ICONSET=assets/golos.iconset
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for spec in "16 16" "32 32" "64 64" "128 128" "256 256" "512 512" "1024 1024"; do
    set -- $spec
    sips -z "$2" "$2" "assets/icon_${VARIANT}.png" --out "$ICONSET/icon_${1}x${1}.png" >/dev/null
done
# macOS naming for @2x variants
cp "$ICONSET/icon_32x32.png"     "$ICONSET/icon_16x16@2x.png"
cp "$ICONSET/icon_64x64.png"     "$ICONSET/icon_32x32@2x.png"
cp "$ICONSET/icon_256x256.png"   "$ICONSET/icon_128x128@2x.png"
cp "$ICONSET/icon_512x512.png"   "$ICONSET/icon_256x256@2x.png"
cp "$ICONSET/icon_1024x1024.png" "$ICONSET/icon_512x512@2x.png"

iconutil -c icns "$ICONSET" -o golos.icns
echo "wrote golos.icns (variant $VARIANT)"
