#!/bin/bash
# Build a versioned DMG with a polished Finder drag-to-install window.
# Packages whichever app bundle the caller built (architecture-neutral).
#
# Usage: ./make_dmg.sh [version]
#   Default version: 0.3.1 → dist/golos-0.3.1.dmg
# Optional env (tests / custom layouts):
#   GOLOS_APP       path to .app (default: dist/golos.app)
#   GOLOS_DMG       output DMG path (default: dist/golos-${VERSION}.dmg)
#   GOLOS_DMG_WORK  scratch directory (default: dist/dmg-build)
#   GOLOS_VENV      venv with PyObjC for SVG rasterize (default: .venv)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VERSION="${1:-0.3.1}"
APP_SRC="${GOLOS_APP:-$ROOT/dist/golos.app}"
DMG="${GOLOS_DMG:-$ROOT/dist/golos-${VERSION}.dmg}"
WORK="${GOLOS_DMG_WORK:-$ROOT/dist/dmg-build}"
VOL_NAME="golos"
BG_SVG="$ROOT/assets/dmg-background.svg"
ICNS="$ROOT/golos.icns"
GOLOS_VENV="${GOLOS_VENV:-$ROOT/.venv}"

# Finder window layout (must match assets/dmg-background.svg pads)
WIN_X=200
WIN_Y=120
WIN_W=680
WIN_H=430
ICON_SIZE=128
APP_ICON_X=160
APP_ICON_Y=185
APPS_ICON_X=520
APPS_ICON_Y=185
# Finder treats background bitmap pixels as window points even on Retina.
# Rasterize at the logical window size or it displays only the top-left
# quarter on high-density screens.
BG_W=680
BG_H=430

RW_DMG=""
DEV_NAME=""
MOUNT_POINT=""
BG_PNG=""

die() {
    echo "make_dmg.sh: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"
}

# Detach with retries; never leave a volume mounted on failure paths.
detach_volume() {
    local target="${1:-}"
    [ -n "$target" ] || return 0
    local n=0
    while [ "$n" -lt 12 ]; do
        if hdiutil detach "$target" -quiet 2>/dev/null; then
            DEV_NAME=""
            MOUNT_POINT=""
            return 0
        fi
        sleep 1
        n=$((n + 1))
    done
    hdiutil detach "$target" -force -quiet 2>/dev/null || true
    DEV_NAME=""
    MOUNT_POINT=""
}

cleanup() {
    local ec=$?
    # Prefer device node; fall back to mount point.
    if [ -n "${DEV_NAME:-}" ]; then
        detach_volume "$DEV_NAME"
    elif [ -n "${MOUNT_POINT:-}" ]; then
        detach_volume "$MOUNT_POINT"
    fi
    if [ -n "${RW_DMG:-}" ] && [ -f "$RW_DMG" ]; then
        rm -f "$RW_DMG"
    fi
    if [ -n "${BG_PNG:-}" ] && [ -f "$BG_PNG" ]; then
        rm -f "$BG_PNG"
    fi
    if [ -d "$WORK" ]; then
        # Only remove known scratch files, then the work dir if empty-ish.
        rm -f "$WORK/background.png" "$WORK/golos-${VERSION}.rw.dmg" 2>/dev/null || true
        rmdir "$WORK" 2>/dev/null || true
    fi
    return "$ec"
}
trap cleanup EXIT

require_cmd hdiutil
require_cmd osascript
require_cmd ditto
require_cmd awk
require_cmd du

[ -d "$APP_SRC" ] || die "$APP_SRC is missing; build the intended architecture first."
[ -f "$APP_SRC/Contents/Info.plist" ] || die "$APP_SRC does not look like a macOS .app bundle."
[ -f "$BG_SVG" ] || die "background source missing: $BG_SVG"
[ -f "$ICNS" ] || die "volume icon missing: $ICNS"

mkdir -p "$(dirname "$DMG")"
mkdir -p "$WORK"

RW_DMG="$WORK/golos-${VERSION}.rw.dmg"
BG_PNG="$WORK/background.png"

# Remove only the exact outputs we will recreate.
rm -f "$DMG" "$RW_DMG" "$BG_PNG"

# ---------------------------------------------------------------------------
# Rasterize SVG → PNG (2×). Prefer venv PyObjC, then Swift, then qlmanage+sips.
# ---------------------------------------------------------------------------
rasterize_background() {
    local svg="$1" png="$2" w="$3" h="$4"

    if [ -x "$GOLOS_VENV/bin/python" ]; then
        if "$GOLOS_VENV/bin/python" - "$svg" "$png" "$w" "$h" <<'PY'
import sys

svg, png, w, h = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
try:
    from AppKit import (
        NSImage, NSBitmapImageRep, NSBitmapImageFileTypePNG,
        NSGraphicsContext, NSColor, NSZeroRect, NSCompositingOperationCopy,
        NSBezierPath,
    )
    from Foundation import NSURL, NSMakeRect
except ImportError:
    sys.exit(2)

img = NSImage.alloc().initWithContentsOfURL_(NSURL.fileURLWithPath_(svg))
if img is None:
    sys.exit(3)
rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, w, h, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
)
ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.setCurrentContext_(ctx)
NSColor.colorWithCalibratedRed_green_blue_alpha_(0.031, 0.043, 0.071, 1.0).set()
NSBezierPath.fillRect_(NSMakeRect(0, 0, w, h))
img.drawInRect_fromRect_operation_fraction_(
    NSMakeRect(0, 0, w, h), NSZeroRect, NSCompositingOperationCopy, 1.0
)
NSGraphicsContext.restoreGraphicsState()
data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
if data is None:
    sys.exit(4)
data.writeToFile_atomically_(png, True)
print(f"rasterized via AppKit → {png} ({w}x{h})")
PY
        then
            return 0
        fi
    fi

    if command -v swift >/dev/null 2>&1; then
        if swift - "$svg" "$png" "$w" "$h" <<'SWIFT'
import AppKit
import Foundation

let args = CommandLine.arguments
// swift - passes script args after -- ; when using `swift -`, argv[1+] are our args
// With `swift - file args`, arguments are: [binary, svg, png, w, h] depending on invocation.
// Using `swift - "$svg" ...` → arguments[1]=svg when reading from stdin via `-`.
guard args.count >= 5 else {
    // args[0] is process name; when run as `swift - a b c d`, extras start at 1
    fputs("swift rasterizer: bad argc \(args.count)\n", stderr)
    exit(1)
}
// Locate paths: last four meaningful — but CommandLine includes swift runner noise.
// Safer: take the last 4 arguments.
let tail = Array(args.suffix(4))
let inPath = tail[0], outPath = tail[1]
guard let tw = Int(tail[2]), let th = Int(tail[3]) else { fputs("bad size\n", stderr); exit(1) }
let inURL = URL(fileURLWithPath: inPath)
let outURL = URL(fileURLWithPath: outPath)
guard let img = NSImage(contentsOf: inURL) else { fputs("failed to load SVG\n", stderr); exit(2) }
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: tw, pixelsHigh: th,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
) else { fputs("bitmap fail\n", stderr); exit(3) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSColor(calibratedRed: 0.031, green: 0.043, blue: 0.071, alpha: 1).setFill()
NSBezierPath.fill(NSRect(x: 0, y: 0, width: CGFloat(tw), height: CGFloat(th)))
img.draw(
    in: NSRect(x: 0, y: 0, width: CGFloat(tw), height: CGFloat(th)),
    from: .zero, operation: .copy, fraction: 1.0
)
NSGraphicsContext.restoreGraphicsState()
guard let data = rep.representation(using: .png, properties: [:]) else {
    fputs("png encode fail\n", stderr); exit(4)
}
try data.write(to: outURL)
print("rasterized via Swift → \(outPath) (\(tw)x\(th))")
SWIFT
        then
            return 0
        fi
    fi

    if command -v qlmanage >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
        local ql_dir="$WORK/ql-out"
        mkdir -p "$ql_dir"
        if qlmanage -t -s "$w" -o "$ql_dir" "$svg" >/dev/null 2>&1; then
            local produced
            produced="$(find "$ql_dir" -maxdepth 1 -name '*.png' -print -quit)"
            if [ -n "$produced" ] && [ -f "$produced" ]; then
                sips -z "$h" "$w" "$produced" --out "$png" >/dev/null
                rm -f "$produced"
                rmdir "$ql_dir" 2>/dev/null || true
                echo "rasterized via qlmanage+sips → $png (${w}x${h})"
                return 0
            fi
        fi
        rmdir "$ql_dir" 2>/dev/null || true
    fi

    die "could not rasterize $svg (need .venv AppKit, swift, or qlmanage+sips)"
}

rasterize_background "$BG_SVG" "$BG_PNG" "$BG_W" "$BG_H"
[ -f "$BG_PNG" ] || die "background PNG was not written"

# ---------------------------------------------------------------------------
# Writable intermediate DMG sized from the app bundle + headroom.
# ---------------------------------------------------------------------------
APP_MB="$(du -sm "$APP_SRC" | awk '{print $1}')"
# Headroom: background, .DS_Store, HFS metadata, free-space margin.
SIZE_MB=$((APP_MB + 50))
if [ "$SIZE_MB" -lt 60 ]; then
    SIZE_MB=60
fi

echo "creating writable DMG (${SIZE_MB} MB) for $APP_SRC …"
# Blank read/write UDIF (no -format/-srcfolder): sized empty volume we populate.
hdiutil create \
    -ov \
    -volname "$VOL_NAME" \
    -fs HFS+ \
    -fsargs "-c c=64,a=16,e=16" \
    -size "${SIZE_MB}m" \
    -type UDIF \
    "$RW_DMG" >/dev/null

ATTACH_OUT="$(hdiutil attach -readwrite -noverify -noautoopen "$RW_DMG")"
# Last /dev line that mentions /Volumes is the mounted HFS partition.
DEV_NAME="$(echo "$ATTACH_OUT" | awk '/\/Volumes\// {print $1; exit}')"
# Preserve spaces in mount names (for example /Volumes/golos 1). The first
# two whitespace-delimited fields are the device and filesystem type; the
# remainder of the matching line is the mount path.
MOUNT_POINT="$(echo "$ATTACH_OUT" | sed -nE '/\/Volumes\// {
    s|^/dev/[^[:space:]]+[[:space:]]+[^[:space:]]+[[:space:]]+||
    p
    q
}')"
[ -n "$DEV_NAME" ] && [ -n "$MOUNT_POINT" ] || die "failed to parse hdiutil attach output"
[ -d "$MOUNT_POINT" ] || die "mount point missing: $MOUNT_POINT"
# If /Volumes/golos already existed, hdiutil may mount as "golos 1", etc.
VOL_MOUNTED="$(basename "$MOUNT_POINT")"
echo "mounted $DEV_NAME → $MOUNT_POINT (volume name: $VOL_MOUNTED)"

# Populate volume
ditto "$APP_SRC" "$MOUNT_POINT/golos.app"
ln -s /Applications "$MOUNT_POINT/Applications"
mkdir -p "$MOUNT_POINT/.background"
cp "$BG_PNG" "$MOUNT_POINT/.background/background.png"

# ---------------------------------------------------------------------------
# Configure Finder window via AppleScript (deterministic icon view layout).
# ---------------------------------------------------------------------------
echo "configuring Finder window …"
osascript <<EOF || die "Finder AppleScript layout failed (is Finder available?)"
tell application "Finder"
    tell disk "$VOL_MOUNTED"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set sidebar width of container window to 0
        set the bounds of container window to {$WIN_X, $WIN_Y, $((WIN_X + WIN_W)), $((WIN_Y + WIN_H))}
        set opts to the icon view options of container window
        set arrangement of opts to not arranged
        set icon size of opts to $ICON_SIZE
        set text size of opts to 12
        set background picture of opts to file ".background:background.png"
        set position of item "golos.app" of container window to {$APP_ICON_X, $APP_ICON_Y}
        set position of item "Applications" of container window to {$APPS_ICON_X, $APPS_ICON_Y}
        update without registering applications
        delay 1
        close
        open
        delay 1
        close
    end tell
end tell
EOF

# Set the volume icon after Finder writes its layout. On current macOS,
# applying the Finder background can remove an icon file installed earlier.
cp "$ICNS" "$MOUNT_POINT/.VolumeIcon.icns"
if command -v SetFile >/dev/null 2>&1; then
    SetFile -c icnC "$MOUNT_POINT/.VolumeIcon.icns" 2>/dev/null || true
    SetFile -a C "$MOUNT_POINT" 2>/dev/null || true
else
    echo "note: SetFile not found; volume uses the default disk icon" >&2
fi

# Ensure .DS_Store is flushed before conversion.
sync
sleep 1

echo "detaching …"
detach_volume "$DEV_NAME"
# Confirm unmounted
if [ -d "$MOUNT_POINT" ]; then
    detach_volume "$MOUNT_POINT"
fi

echo "converting to compressed UDZO …"
# hdiutil convert refuses to overwrite; we already removed $DMG
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG" >/dev/null
rm -f "$RW_DMG"
RW_DMG=""

du -sh "$DMG"
echo "built $DMG"
