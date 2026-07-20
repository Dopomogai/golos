#!/usr/bin/env python3
"""golos icon: Vishuddha-chakra interpretation — a 16-petal lotus ring of
waveform bars around a central disc, on a dark rounded square.

Renders three 1024x1024 variants to assets/icon_A.png / icon_B.png /
icon_C.png. assets/make_icon.sh builds golos.icns from variant A.

Run with the venv python (needs PyObjC): .venv/bin/python assets/make_icon.py
"""

import math
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
SIZE = 1024
PETALS = 16

# composition geometry (fraction of canvas)
CENTER = SIZE / 2
DISC_R = SIZE * 0.145          # central moon disc
RING_R = SIZE * 0.295          # inner petal edge radius
PETAL_W = SIZE * 0.055         # capsule width
PETAL_LONG = SIZE * 0.16       # alternating petal lengths (waveform sunburst)
PETAL_SHORT = SIZE * 0.105


def lerp(c1, c2, t):
    """Linear blend of two RGB triples; t in [0, 1]."""
    return tuple(a + (b - a) * t for a, b in zip(c1, c2))


def petal_color(variant: str, angle_deg: float, x_norm: float):
    """x_norm in [-1, 1] (petal center, normalized). angle for gradients."""
    t = (x_norm + 1) / 2  # 0 at left, 1 at right
    if variant == "A":   # chakra blue: turquoise -> sky blue
        return lerp((0.16, 0.82, 0.78), (0.36, 0.62, 0.98), t)
    if variant == "B":   # brand fire: recording-wings red -> orange
        return lerp((1.0, 0.25, 0.20), (1.0, 0.60, 0.10), t)
    # C: duotone: blue on the left half -> orange on the right half
    return lerp((0.25, 0.55, 0.95), (1.0, 0.55, 0.12), t)


BACKGROUNDS = {
    "A": (0.05, 0.07, 0.14),   # deep navy-black
    "B": (0.07, 0.06, 0.06),   # near-black warm
    "C": (0.12, 0.12, 0.13),   # charcoal
}
DISC_COLORS = {
    "A": (0.88, 0.93, 1.0),    # pale moon disc
    "B": (1.0, 0.85, 0.70),    # warm center
    "C": (0.97, 0.97, 0.97),   # white
}


def render(variant: str, out_path: Path):
    from AppKit import (
        NSImage, NSColor, NSBezierPath, NSGraphicsContext, NSAffineTransform,
        NSBitmapImageRep, NSBitmapImageFileTypePNG,
    )
    from Foundation import NSMakeRect

    image = NSImage.alloc().initWithSize_((SIZE, SIZE))
    image.lockFocus()

    bg = BACKGROUNDS[variant]
    NSColor.colorWithCalibratedRed_green_blue_alpha_(*bg, 1.0).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(0, 0, SIZE, SIZE), SIZE * 0.225, SIZE * 0.225).fill()

    # 16 petals radially; alternating long/short reads like a waveform ring
    for k in range(PETALS):
        angle = k * (360.0 / PETALS)
        length = PETAL_LONG if k % 2 == 0 else PETAL_SHORT
        x_norm = math.cos(math.radians(angle))
        color = petal_color(variant, angle, x_norm)

        transform = NSAffineTransform.transform()
        transform.translateXBy_yBy_(CENTER, CENTER)
        transform.rotateByDegrees_(angle)
        transform.concat()
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*color, 1.0).set()
        # capsule: inner edge at RING_R, extending outward
        rect = NSMakeRect(RING_R, -PETAL_W / 2, length, PETAL_W)
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, PETAL_W / 2, PETAL_W / 2).fill()
        transform.invert()
        transform.concat()

    # central disc (moon) + faint ring
    dr, dg, db = DISC_COLORS[variant]
    NSColor.colorWithCalibratedRed_green_blue_alpha_(dr, dg, db, 1.0).set()
    NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(CENTER - DISC_R, CENTER - DISC_R, DISC_R * 2, DISC_R * 2)
    ).fill()
    NSColor.colorWithCalibratedRed_green_blue_alpha_(dr, dg, db, 0.25).set()
    ring = NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(CENTER - DISC_R * 1.35, CENTER - DISC_R * 1.35,
                   DISC_R * 2.7, DISC_R * 2.7))
    ring.setLineWidth_(SIZE * 0.012)
    ring.stroke()

    image.unlockFocus()

    rep = NSBitmapImageRep.alloc().initWithData_(image.TIFFRepresentation())
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    data.writeToFile_atomically_(str(out_path), True)
    print(f"wrote {out_path}")


def render_glyph(petals: int, out_path: Path):
    """Menu-bar TEMPLATE glyph: chakra mark as solid black on transparent
    (macOS template images are alpha-driven). 36x36 px (@2x of 18x18 pt)."""
    from AppKit import (
        NSImage, NSColor, NSBezierPath, NSAffineTransform,
        NSBitmapImageRep, NSBitmapImageFileTypePNG,
    )
    from Foundation import NSMakeRect

    G = 36.0
    center = G / 2
    ring_r = G * 0.28
    petal_w = G * 0.13 if petals <= 12 else G * 0.09
    long_l = G * 0.24
    short_l = G * 0.17

    image = NSImage.alloc().initWithSize_((G, G))
    image.lockFocus()
    NSColor.blackColor().set()
    for k in range(petals):
        angle = k * (360.0 / petals)
        length = long_l if k % 2 == 0 else short_l
        transform = NSAffineTransform.transform()
        transform.translateXBy_yBy_(center, center)
        transform.rotateByDegrees_(angle)
        transform.concat()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(ring_r, -petal_w / 2, length, petal_w),
            petal_w / 2, petal_w / 2).fill()
        transform.invert()
        transform.concat()
    NSBezierPath.bezierPathWithOvalInRect_(
        NSMakeRect(center - G * 0.14, center - G * 0.14, G * 0.28, G * 0.28)
    ).fill()
    image.unlockFocus()

    rep = NSBitmapImageRep.alloc().initWithData_(image.TIFFRepresentation())
    data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    data.writeToFile_atomically_(str(out_path), True)
    print(f"wrote {out_path} ({petals} petals)")


def main():
    for variant in ("A", "B", "C"):
        render(variant, OUT_DIR / f"icon_{variant}.png")


if __name__ == "__main__":
    import sys
    if "--glyph" in sys.argv:
        render_glyph(12, OUT_DIR / "glyph_12.png")
        render_glyph(16, OUT_DIR / "glyph_16.png")
    else:
        main()
