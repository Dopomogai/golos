#!/bin/bash
# Build a versioned DMG: golos.app + /Applications symlink (drag-to-install).
# Requires the caller to build the intended architecture first.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${1:-0.3.1}"
DMG="dist/golos-${VERSION}.dmg"
STAGE="dist/dmg-stage"

if [ ! -d dist/golos.app ]; then
    echo "dist/golos.app is missing; build the intended architecture first." >&2
    exit 1
fi

rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R dist/golos.app "$STAGE/golos.app"
ln -s /Applications "$STAGE/Applications"

hdiutil create -volname "golos" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
du -sh "$DMG"
echo "built $DMG"
