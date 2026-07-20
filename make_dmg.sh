#!/bin/bash
# Build dist/golos-0.2.0.dmg: golos.app + /Applications symlink (drag-to-install).
# Runs build_app.sh first when dist/golos.app is missing.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${1:-0.2.0}"
DMG="dist/golos-${VERSION}.dmg"
STAGE="dist/dmg-stage"

[ -d dist/golos.app ] || ./build_app.sh

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R dist/golos.app "$STAGE/golos.app"
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "golos" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
du -sh "$DMG"
echo "built $DMG"
