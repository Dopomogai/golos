"""Always-on-top floating status bubble (borderless NSPanel) + recording wings.

Styles ([bubble] style in config.toml):
- "notch": a small pill inside the menu-bar row, centered under the camera
  notch, shown while processing / after insert. While recording, "wings":
  a fluid live waveform emanating from both edges of the notch, drawn over
  the menu bar. On stop, the wings collapse inward toward the notch (~0.2s
  sweep) before the processing pill appears. The wings panel ignores mouse
  events — clicks fall through to the menus underneath.
- "corner": draggable pill at the bottom-right with a live waveform while
  recording (no wings, no notch needed).

Visibility: idle means HIDDEN — no bubble at all. The bubble starts hidden at
launch and only appears in non-idle states.

States: idle (hidden), recording (red wings/waveform), locked (same),
processing (blue pill, breathing dot, animated ellipsis + elapsed seconds),
success (green "✓ inserted" pill, ~1.2s, then hidden).
Non-activating; appears on all spaces including fullscreen.

All UI methods must be called on the main thread.

PyObjC notes: ObjC subclasses use objc.super (not Python super), and are
defined exactly once per process (ObjC class names are global) — per-instance
state lives on the view instances, not in closures.
"""

import logging
import time
from collections import deque

log = logging.getLogger(__name__)

# corner style geometry
W, H = 132.0, 36.0
# notch pill geometry (inside the 32pt menu-bar row)
PILL_W, PILL_H, MENU_ROW_H = 150.0, 24.0, 32.0
# wings geometry
WING_W, WING_H = 184.0, 48.0
WING_BARS = 26               # bars per side (2pt margin + 26 x 7pt = 184)
SUCCESS_BARS = 24            # success mode: nearly the full strip width
WING_BAR_W, WING_BAR_STEP = 4.0, 7.0
WING_BAR_MAX_H = 34.0


def edge_falloff(i: int) -> float:
    """Alpha factor per bar index (0 at the notch edge, WING_BARS-1 outermost):
    full for the inner ~70% of bars, then linear down toward the strip edge so
    bars visually dissolve instead of clipping."""
    return min(1.0, (WING_BARS - i) / 7.0)


SUCCESS_SECONDS = 1.2


def success_decay(progress: float) -> float:
    """Recede curve for the success strip: 1.0 at show time, eases to 0 as the
    strip hides (~1.2s), so the wave visibly ebbs away."""
    p = min(1.0, max(0.0, progress))
    return (1.0 - p) ** 1.2


def success_envelope(i: int) -> float:
    """Hill envelope across the success bars: tallest at the notch, tapering
    to ~0 at BOTH outer ends. i in [0, SUCCESS_BARS-1], 0 = notch edge."""
    import math
    t = i / (SUCCESS_BARS - 1)
    return math.cos(t * math.pi / 2) ** 0.9


def shimmer_amplitude(t: float, breath: float) -> float:
    """Processing wave energy: decays with distance from the notch (t 0..1),
    multiplied by the slow breathing factor."""
    return (1.0 - 0.6 * t) * breath


def circle_rect_values(i: int, side: int, notch_w: float, mid_y: float):
    """Geometry of one silence dot (identical for every bar: same y, w, h)."""
    if side == 0:
        x = WING_W - 2 - i * WING_BAR_STEP - WING_BAR_W
    else:
        x = WING_W + notch_w + 2 + i * WING_BAR_STEP
    return (x, mid_y - WING_BAR_W / 2, WING_BAR_W, WING_BAR_W)
COLLAPSE_SECONDS = 0.2
LEVEL_COUNT = 52             # rolling RMS buffer (feeds both wings)
LEVEL_MIN_INTERVAL = 1/30    # redraw throttle (~30 fps)
LEVEL_EMA = 0.5              # smoothing: new = 0.5*old + 0.5*incoming

# state -> (label, dot RGB, pulsing?)
STATES = {
    "idle": ("idle", (0.45, 0.45, 0.45), False),
    "recording": ("recording", (0.90, 0.20, 0.20), True),
    "processing": ("processing", (0.20, 0.45, 0.95), False),
    "locked": ("locked rec", (0.90, 0.20, 0.20), True),
    "success": ("✓ inserted", (0.20, 0.80, 0.35), False),
}
RECORDING_STATES = ("recording", "locked")

_classes = None


def _bubble_classes():
    """Define the ObjC view/panel classes once per process."""
    global _classes
    if _classes is not None:
        return _classes

    import objc
    from AppKit import (
        NSPanel, NSView, NSColor, NSFont, NSBezierPath, NSFontAttributeName,
        NSForegroundColorAttributeName, NSTimer,
    )
    from Quartz import CALayer, CABasicAnimation, CGColorCreateGenericRGB, CGSizeMake
    from Foundation import NSMakeRect, NSMakePoint, NSDictionary, NSString

    class BubblePanel(NSPanel):
        # Non-activating: clicking/dragging must not steal focus.
        def canBecomeKeyWindow(self):
            return False

        def canBecomeMainWindow(self):
            return False

    class BubbleView(NSView):
        """The pill: dark rounded background, colored dot, label; optional
        live waveform while recording (corner style / no-aux fallback).
        Runs the processing ellipsis/elapsed timer itself."""

        def initWithFrame_(self, frame):
            self = objc.super(BubbleView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._state = "idle"
            self._is_notch = False
            self._levels = None          # shared deque, set by Bubble
            self._label_override = None
            self._notice_rgb = None
            self._on_click = None
            self._processing_timer = None
            self._processing_start = 0.0
            self._tick_count = 0
            self.setWantsLayer_(True)
            h = frame.size.height
            self._dot_layer = CALayer.layer()
            self._dot_layer.setFrame_(NSMakeRect(12, (h - 8) / 2, 8, 8))
            self._dot_layer.setCornerRadius_(4)
            self.layer().addSublayer_(self._dot_layer)
            self._apply_dot()
            return self

        def drawRect_(self, rect):
            h = self.bounds().size.height
            NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.88).set()
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                self.bounds(), h / 2, h / 2)
            path.fill()
            if self._state in RECORDING_STATES and not self._is_notch:
                self._draw_waveform()
            else:
                self._draw_label()

        def _draw_label(self):
            h = self.bounds().size.height
            label = self._label_override or STATES[self._state][0]
            attrs = NSDictionary.dictionaryWithObjects_forKeys_(
                [NSFont.systemFontOfSize_(11 if self._is_notch else 13),
                 NSColor.whiteColor()],
                [NSFontAttributeName, NSForegroundColorAttributeName],
            )
            s = NSString.stringWithString_(label)
            size = s.sizeWithAttributes_(attrs)
            s.drawAtPoint_withAttributes_(
                NSMakePoint(26 if self._is_notch else 32, (h - size.height) / 2),
                attrs)

        def _draw_waveform(self):
            # Symmetric vertical bars from the shared rolling RMS buffer.
            h = self.bounds().size.height
            r, g, b = STATES[self._state][1]
            NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 0.95).set()
            vals = list(self._levels) if self._levels is not None else []
            bars = 24
            area_x, area_w = 26.0, self.bounds().size.width - 26.0 - 8.0
            bar_w = 4.0
            step = min(bar_w + 2.0, area_w / bars)
            x0 = area_x + (area_w - step * bars) / 2
            mid_y = h / 2  # corner pill: center on the pill itself
            for i in range(bars):
                idx = len(vals) - bars + i
                v = vals[idx] if 0 <= idx < len(vals) else 0.0
                mag = min(1.0, v * 7.0)          # RMS ~0.01-0.2 -> bar fraction
                bar_h = max(2.0, mag * (h - 4))
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSMakeRect(x0 + i * step, mid_y - bar_h / 2, bar_w, bar_h),
                    bar_w / 2, bar_w / 2,
                ).fill()

        # -- processing label animation -------------------------------------

        def setState_(self, state):
            self._state = state
            self._label_override = None
            self._notice_rgb = None
            self._on_click = None
            if self._processing_timer is not None:
                self._processing_timer.invalidate()
                self._processing_timer = None
            if state == "processing":
                self._processing_start = time.monotonic()
                self._tick_count = 0
                self._processing_timer = NSTimer \
                    .scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                        0.4, self, "processingTick:", None, True)
            self._apply_dot()
            self.setNeedsDisplay_(True)

        def mouseUp_(self, event):
            if self._on_click is not None:
                self._on_click()

        def displayNotice_kind_(self, text, kind):
            self._state = "notice"
            self._label_override = text
            self._notice_rgb = {"success": (0.25, 0.85, 0.4),
                                "info": (0.30, 0.55, 0.95),
                                "warn": (0.95, 0.35, 0.25)}.get(kind, (0.5, 0.5, 0.5))
            if self._processing_timer is not None:
                self._processing_timer.invalidate()
                self._processing_timer = None
            self._apply_dot()
            self.setNeedsDisplay_(True)

        def processingTick_(self, timer):
            self._tick_count += 1
            elapsed = time.monotonic() - self._processing_start
            dots = ("", ".", "..", "…")[self._tick_count % 4]
            label = "processing" + dots
            if elapsed >= 3.0:
                label += f" {int(elapsed)}s"
            self._label_override = label
            self.setNeedsDisplay_(True)

        def _apply_dot(self):
            if self._state == "notice" and self._notice_rgb is not None:
                rgb = self._notice_rgb
                pulse = False
            else:
                _, rgb, pulse = STATES[self._state]
            self._dot_layer.setBackgroundColor_(CGColorCreateGenericRGB(*rgb, 1.0))
            self._dot_layer.removeAnimationForKey_("pulse")
            self._dot_layer.removeAnimationForKey_("breathe")
            if self._state == "processing":
                # continuous slow "breathe" while waiting on the API
                anim = CABasicAnimation.animationWithKeyPath_("opacity")
                anim.setFromValue_(1.0)
                anim.setToValue_(0.4)
                anim.setDuration_(1.2)
                anim.setAutoreverses_(True)
                anim.setRepeatCount_(1e9)
                self._dot_layer.addAnimation_forKey_(anim, "breathe")
            elif pulse:
                anim = CABasicAnimation.animationWithKeyPath_("opacity")
                anim.setFromValue_(1.0)
                anim.setToValue_(0.25)
                anim.setDuration_(0.7)
                anim.setAutoreverses_(True)
                anim.setRepeatCount_(1e9)
                self._dot_layer.addAnimation_forKey_(anim, "pulse")
            # subtle red glow while the pill itself shows recording
            if not self._is_notch and self._state in RECORDING_STATES:
                self.layer().setShadowColor_(CGColorCreateGenericRGB(*rgb, 1.0))
                self.layer().setShadowOpacity_(0.8)
                self.layer().setShadowRadius_(12.0)
                self.layer().setShadowOffset_(CGSizeMake(0, 0))
            else:
                self.layer().setShadowOpacity_(0.0)

    class WingsView(NSView):
        """Mirrored fluid waveform wings emanating from both notch edges.

        Most recent (EMA-smoothed) RMS sample at the notch edge, older samples
        outward — sound ripples away from the notch. Per-bar color gradients
        red -> orange with alpha fading to ~0.25. On stop, bars shrink from
        the outside in (~0.2s sweep) via startCollapse.

        The strip is a single state-driven surface (setMode_):
        - "recording": red live waveform;
        - "processing": blue traveling shimmer + "processing… Ns" gap label;
        - "success": green strip + "✓ inserted" gap label."""

        def initWithFrame_(self, frame):
            self = objc.super(WingsView, self).initWithFrame_(frame)
            if self is None:
                return None
            self._levels = None          # shared deque, set by Bubble
            self._mode = "recording"
            self._collapse = 0.0         # 0..1 sweep progress
            self._collapse_timer = None
            self._on_collapse_done = None
            self._shimmer_timer = None
            self._shimmer_phase = 0.0
            self._mode_start = 0.0
            self._notice_text = ""
            self._notice_kind = "info"
            self._sensitivity = 1.0    # display gain multiplier for the waveform
            self.setWantsLayer_(True)
            self.layer().setShadowOpacity_(0.6)
            self.layer().setShadowRadius_(6.0)
            self.layer().setShadowOffset_(CGSizeMake(0, 0))
            self._apply_glow()
            return self

        # -- modes -------------------------------------------------------------

        def setMode_(self, mode):
            self._mode = mode
            self._mode_start = time.monotonic()
            self._shimmer_phase = 0.0
            if self._shimmer_timer is not None:
                self._shimmer_timer.invalidate()
                self._shimmer_timer = None
            if mode in ("processing", "success"):
                # 30fps redraw clock: drives the shimmer travel AND the
                # success recede (progress computed from _mode_start).
                self._shimmer_timer = NSTimer \
                    .scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                        1 / 30, self, "shimmerTick:", None, True)
            self._apply_glow()
            self.setNeedsDisplay_(True)

        def displayNotice_kind_(self, text, kind):
            self._notice_text = text
            self._notice_kind = kind
            self.setMode_("notice")

        def stopAnimation(self):
            """Stop the redraw clock (called when the strip hides for idle)."""
            if self._shimmer_timer is not None:
                self._shimmer_timer.invalidate()
                self._shimmer_timer = None

        def shimmerTick_(self, timer):
            self._shimmer_phase += (1 / 30) * 14.0  # ~14 bars/s travel speed
            self.setNeedsDisplay_(True)

        def _apply_glow(self):
            rgb = {"recording": (1.0, 0.3, 0.2),
                   "processing": (0.25, 0.5, 1.0),
                   "success": (0.2, 0.85, 0.4),
                   "notice": (0.5, 0.5, 0.5)}.get(self._mode, (1, 1, 1))
            self.layer().setShadowColor_(CGColorCreateGenericRGB(*rgb, 1.0))

        # -- drawing -------------------------------------------------------------

        def drawRect_(self, rect):
            if self._mode == "processing":
                self._draw_shimmer()
            elif self._mode == "success":
                self._draw_success_strip()
            elif self._mode == "notice":
                self._draw_notice()
            else:
                self._draw_recording(rect)

        def _bar_x(self, side, i, notch_w):
            if side == 0:
                return WING_W - 2 - i * WING_BAR_STEP - WING_BAR_W
            return WING_W + notch_w + 2 + i * WING_BAR_STEP

        def _draw_gap_label(self, text, color):
            w = self.bounds().size.width
            h = self.bounds().size.height
            notch_w = w - 2 * WING_W
            attrs = NSDictionary.dictionaryWithObjects_forKeys_(
                [NSFont.systemFontOfSize_(11), color],
                [NSFontAttributeName, NSForegroundColorAttributeName])
            s = NSString.stringWithString_(text)
            size = s.sizeWithAttributes_(attrs)
            x = WING_W + (notch_w - size.width) / 2
            # vertically center on the menu row, not the taller strip
            mid_y = h - MENU_ROW_H / 2
            s.drawAtPoint_withAttributes_(
                NSMakePoint(x, mid_y - size.height / 2), attrs)

        def _draw_recording(self, rect):
            if self._levels is None:
                return
            vals = list(self._levels)
            w = self.bounds().size.width
            h = self.bounds().size.height
            notch_w = w - 2 * WING_W
            mid_y = h - MENU_ROW_H / 2  # center on the menu row, not the taller strip
            for side in (0, 1):  # 0 = left of notch, 1 = right
                for i in range(WING_BARS):
                    idx = len(vals) - 1 - i
                    v = vals[idx] if idx >= 0 else 0.0
                    mag = min(1.0, v * 15.0 * self._sensitivity)
                    t = i / (WING_BARS - 1)   # 0 at notch edge -> 1 outward
                    mag_scaled = mag * 30.0
                    if mag_scaled <= 2.0 and self._collapse == 0.0:
                        # silence: perfectly even dotted line — identical
                        # circles, same alpha, no micro-variation
                        NSColor.colorWithCalibratedRed_green_blue_alpha_(
                            1.0, 0.25 + t * 0.35, 0.2 - t * 0.1,
                            0.35 * edge_falloff(i)).set()
                        cx, cy, cw, ch = circle_rect_values(i, side, notch_w, mid_y)
                        NSBezierPath.bezierPathWithOvalInRect_(
                            NSMakeRect(cx, cy, cw, ch)).fill()
                        continue
                    bar_h = 4.0 + (mag_scaled - 2.0)  # starts at 4pt: no pop
                    if self._collapse > 0.0:
                        # outside-in sweep: outermost bar (i = BARS-1) first
                        scale = 1.0 - (self._collapse * WING_BARS - (WING_BARS - 1 - i))
                        bar_h *= max(0.0, min(1.0, scale))
                    if bar_h < 0.5:
                        continue
                    alpha = (1.0 - t * 0.75) * edge_falloff(i)
                    color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        1.0, 0.25 + t * 0.35, 0.2 - t * 0.1, alpha)
                    color.set()
                    x = self._bar_x(side, i, notch_w)
                    if bar_h <= WING_BAR_W:
                        NSBezierPath.bezierPathWithOvalInRect_(
                            NSMakeRect(x, mid_y - bar_h / 2, WING_BAR_W, bar_h)
                        ).fill()
                    else:
                        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                            NSMakeRect(x, mid_y - bar_h / 2, WING_BAR_W, bar_h),
                            WING_BAR_W / 2, WING_BAR_W / 2,
                        ).fill()

        def _draw_shimmer(self):
            # Blue wave ping-ponging across the strip; crests lose amplitude
            # with distance from the notch, and the whole strip breathes
            # (0.7-1.0 over 2.4s) so long waits stay alive.
            import math
            w = self.bounds().size.width
            h = self.bounds().size.height
            notch_w = w - 2 * WING_W
            mid_y = h - MENU_ROW_H / 2  # center on the menu row, not the taller strip
            span = float(WING_BARS - 1)
            pos = self._shimmer_phase % (2 * span)
            center = pos if pos <= span else 2 * span - pos  # ping-pong
            elapsed = time.monotonic() - self._mode_start
            breath = 0.85 + 0.15 * math.sin(elapsed * 2 * math.pi / 2.4)
            for side in (0, 1):
                for i in range(WING_BARS):
                    dist = i - center
                    bright = math.exp(-(dist * dist) / 18.0)
                    t = i / (WING_BARS - 1)
                    alpha = (0.15 + 0.75 * bright) * edge_falloff(i)
                    bar_h = (8.0 + 18.0 * bright) * shimmer_amplitude(t, breath)
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.25, 0.5, 1.0, alpha).set()
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        NSMakeRect(self._bar_x(side, i, notch_w),
                                   mid_y - bar_h / 2, WING_BAR_W, bar_h),
                        WING_BAR_W / 2, WING_BAR_W / 2).fill()
            dots = ("", ".", "..", "…")[int(elapsed / 0.4) % 4]
            label = "processing" + dots
            if elapsed >= 3.0:
                label += f" {int(elapsed)}s"
            self._draw_gap_label(label, NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.75, 0.85, 1.0, 1.0))

        def _draw_success_strip(self):
            # Green hill that recedes: tallest at the notch, tapering to short
            # at both outer ends (envelope), and the whole arc ebbs to ~0 over
            # the ~1.2s display (label stays for the full duration).
            w = self.bounds().size.width
            h = self.bounds().size.height
            notch_w = w - 2 * WING_W
            mid_y = h - MENU_ROW_H / 2  # center on the menu row, not the taller strip
            progress = (time.monotonic() - self._mode_start) / SUCCESS_SECONDS
            decay = success_decay(progress)
            for side in (0, 1):
                for i in range(SUCCESS_BARS):
                    t = i / (SUCCESS_BARS - 1)
                    bar_h = 24.0 * decay * success_envelope(i)
                    if bar_h < 0.5:
                        continue
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.2, 0.85, 0.4, (0.75 - t * 0.5) * edge_falloff(i)).set()
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        NSMakeRect(self._bar_x(side, i, notch_w),
                                   mid_y - bar_h / 2, WING_BAR_W, bar_h),
                        WING_BAR_W / 2, WING_BAR_W / 2).fill()
            self._draw_gap_label("✓ inserted", NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.6, 1.0, 0.7, 1.0))

        def _draw_notice(self):
            # Faint bars + gap text — a lightweight "something was learned" flash.
            w = self.bounds().size.width
            h = self.bounds().size.height
            notch_w = w - 2 * WING_W
            mid_y = h - MENU_ROW_H / 2
            for side in (0, 1):
                for i in range(WING_BARS):
                    NSColor.colorWithCalibratedWhite_alpha_(
                        0.8, 0.15 * edge_falloff(i)).set()
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        NSMakeRect(self._bar_x(side, i, notch_w),
                                   mid_y - 8.0, WING_BAR_W, 16.0),
                        WING_BAR_W / 2, WING_BAR_W / 2).fill()
            rgb = {"success": (0.35, 0.95, 0.45),
                   "info": (0.45, 0.65, 1.0),
                   "warn": (1.0, 0.4, 0.35)}.get(self._notice_kind, (0.9, 0.9, 0.9))
            self._draw_gap_label(self._notice_text,
                                 NSColor.colorWithCalibratedRed_green_blue_alpha_(
                                     *rgb, 1.0))

        # -- collapse sweep (recording -> processing handoff) -------------------

        def startCollapse(self):
            if self._collapse_timer is not None:
                self._collapse_timer.invalidate()
            self._collapse = 0.0
            self._collapse_timer = NSTimer \
                .scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1 / 60, self, "collapseTick:", None, True)

        def collapseTick_(self, timer):
            self._collapse += (1 / 60) / COLLAPSE_SECONDS
            if self._collapse >= 1.0:
                self._collapse_timer.invalidate()
                self._collapse_timer = None
                self._collapse = 0.0
                # The done-callback re-modes the strip; visibility is then
                # re-derived by the Bubble's _enforce_visibility — a stale
                # completion can never hide a panel a newer state just showed.
                if self._on_collapse_done is not None:
                    self._on_collapse_done()
            else:
                self.setNeedsDisplay_(True)

    _classes = (BubbleView, BubblePanel, WingsView)
    return _classes


def has_notch(screen=None) -> bool:
    """True if the main screen has a camera notch (top safe-area inset)."""
    from AppKit import NSScreen
    screen = screen or NSScreen.mainScreen()
    if screen is None:
        return False
    try:
        if screen.safeAreaInsets().top > 0:
            return True
        return screen.auxiliaryTopLeftArea() is not None
    except Exception:
        return False


def notch_geometry(screen=None) -> tuple[float, float, float] | None:
    """(notch_left_x, notch_right_x, screen_max_y), or None without aux areas."""
    from AppKit import NSScreen
    screen = screen or NSScreen.mainScreen()
    if screen is None:
        return None
    try:
        aux_l = screen.auxiliaryTopLeftArea()
        aux_r = screen.auxiliaryTopRightArea()
        if aux_l is None or aux_r is None:
            return None
        f = screen.frame()
        return (aux_l.origin.x + aux_l.size.width, aux_r.origin.x,
                f.origin.y + f.size.height)
    except Exception:
        return None


class Bubble:
    """Controller for the pill panel (+ lazily-created wings panel)."""

    def __init__(self, style: str = "corner"):
        from AppKit import (
            NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
            NSStatusWindowLevel, NSScreen, NSColor,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorStationary, NSAnimationContext,
            NSViewWidthSizable, NSWindowStyleMaskNonactivatingPanel,
        )
        from Foundation import NSMakeRect
        import AppKit

        BubbleView, BubblePanel, WingsView = _bubble_classes()
        self._WingsView = WingsView
        self._BubblePanel = BubblePanel
        self._NSAnimationContext = NSAnimationContext
        self._NSWindowStyleMaskBorderless = NSWindowStyleMaskBorderless
        self._NSBackingStoreBuffered = NSBackingStoreBuffered
        self._NSStatusWindowLevel = NSStatusWindowLevel
        self._NSColor = NSColor
        # Named constant preferred; 256 == NSWindowCollectionBehaviorFullScreenAuxiliary
        # (1 << 8) on this SDK — needed to show over fullscreen apps.
        self._collection_behavior = (
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | getattr(AppKit, "NSWindowCollectionBehaviorFullScreenAuxiliary", 256))

        self.style = style
        self.is_notch = style == "notch" and has_notch()
        if style == "notch" and not self.is_notch:
            log.info("Bubble style 'notch' requested but no notch detected; "
                     "falling back to corner.")
        self._geometry = notch_geometry() if self.is_notch else None
        if self.is_notch and self._geometry is None:
            log.info("No auxiliary notch areas; recording will use the pill.")

        w = PILL_W if self.is_notch else W
        h = PILL_H if self.is_notch else H
        self._w, self._h = w, h
        self._levels = deque(maxlen=LEVEL_COUNT)
        self._ema = 0.0
        self._last_level_draw = 0.0
        self.wings = None            # NSPanel, created lazily on first recording
        self._state = "idle"
        self._notice_gen = 0
        self._vis_gen = 0
        self._notice_surface = "pill"
        self.wings_view = None
        self._sensitivity = 1.0

        # NonactivatingPanel: the cue pill is clickable WITHOUT stealing focus.
        self._pill_style_mask = (NSWindowStyleMaskBorderless
                                 | NSWindowStyleMaskNonactivatingPanel)
        screen = NSScreen.mainScreen()
        rect = NSMakeRect(*self._origin(screen), w, h)
        self.panel = BubblePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, self._pill_style_mask, NSBackingStoreBuffered, False)
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setCollectionBehavior_(self._collection_behavior)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        # NSPanel defaults to hiding when the app deactivates — the bubble
        # must stay visible while the user types in other apps.
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setHasShadow_(not self.is_notch)  # notch uses its own glow layer
        self.panel.setMovableByWindowBackground_(not self.is_notch)  # corner: draggable
        self.view = BubbleView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        self.view._is_notch = self.is_notch
        self.view._levels = self._levels
        self.view.setAutoresizingMask_(NSViewWidthSizable)
        self.panel.setContentView_(self.view)
        # idle means hidden: the bubble only appears in non-idle states.
        self.panel.setAlphaValue_(1.0)
        self.panel.orderOut_(None)

    # -- geometry ----------------------------------------------------------

    def _origin(self, screen) -> tuple[float, float]:
        if self.is_notch:
            f = screen.frame()
            max_y = f.origin.y + f.size.height
            if self._geometry is not None:
                left, right, max_y = self._geometry
                cx = (left + right) / 2
            else:
                cx = f.origin.x + f.size.width / 2
            # centered under the notch, vertically centered in the menu row
            return cx - self._w / 2, max_y - MENU_ROW_H + (MENU_ROW_H - self._h) / 2
        vf = screen.visibleFrame()
        return vf.origin.x + vf.size.width - self._w - 40, vf.origin.y + 40

    # -- wings panel --------------------------------------------------------

    def _ensure_wings(self):
        if self.wings is not None or self._geometry is None:
            return
        from Foundation import NSMakeRect
        left, right, max_y = self._geometry
        rect = NSMakeRect(left - WING_W, max_y - WING_H,
                          (right - left) + 2 * WING_W, WING_H)
        self.wings = self._BubblePanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, self._NSWindowStyleMaskBorderless, self._NSBackingStoreBuffered, False)
        self.wings.setLevel_(self._NSStatusWindowLevel)  # draws over the menu bar
        self.wings.setCollectionBehavior_(self._collection_behavior)
        self.wings.setOpaque_(False)
        self.wings.setBackgroundColor_(self._NSColor.clearColor())
        self.wings.setHidesOnDeactivate_(False)
        self.wings.setHasShadow_(False)
        # CRITICAL: the wings overlap the menus — clicks must pass through.
        self.wings.setIgnoresMouseEvents_(True)
        self.wings_view = self._WingsView.alloc().initWithFrame_(
            NSMakeRect(0, 0, rect.size.width, rect.size.height))
        self.wings_view._levels = self._levels
        self.wings_view._sensitivity = self._sensitivity
        self.wings.setContentView_(self.wings_view)
        self.wings.setAlphaValue_(0.0)

    def set_sensitivity(self, value: float) -> None:
        """Display gain for the recording waveform ([bubble] sensitivity,
        0.5-2.5). Live-updates the wings view when it exists."""
        self._sensitivity = max(0.5, min(2.5, float(value)))
        if self.wings_view is not None:
            self.wings_view._sensitivity = self._sensitivity

    # -- visibility (DETERMINISTIC — animations are cosmetic only) ------------
    #
    # `_enforce_visibility` is the single source of truth for panel
    # isVisible/alpha, derived from `self._state`. It runs synchronously at
    # the END of every state path (set_state / notice / cue / dismiss /
    # collapse completion) and it never depends on an animation having run:
    # panels are ordered front and alpha is set to 1.0 directly. A stale
    # fade completion can no longer blank the strip mid-churn (the class of
    # bug that made the strip disappear permanently in extended use).

    def _enforce_visibility(self) -> None:
        """Set final panel visibility from the state matrix. Synchronous."""
        self._vis_gen += 1
        if self._geometry is not None:
            # Notch path: strip handles real states; notice may use strip
            # (notice) or pill (cue).
            strip_states = RECORDING_STATES + ("processing", "success")
            show_strip = (self._state in strip_states
                          or (self._state == "notice"
                              and self._notice_surface == "wings")
                          or (self._collapse > 0.0
                              and self.wings is not None
                              and self.wings.isVisible()))
            show_pill = (self._state == "notice"
                         and self._notice_surface == "pill")
            if show_strip:
                self._ensure_wings()
                self.wings.orderFrontRegardless()
                self.wings.setAlphaValue_(1.0)
            elif self.wings is not None:
                self.wings.orderOut_(None)
            if show_pill:
                self.panel.orderFrontRegardless()
                self.panel.setAlphaValue_(1.0)
            else:
                self.panel.orderOut_(None)
        else:
            # Corner / no-aux path: pill handles everything.
            if self._state == "idle":
                self.panel.orderOut_(None)
            else:
                self.panel.orderFrontRegardless()
                self.panel.setAlphaValue_(1.0)

    def _show_panel(self, panel, duration=0.0):
        # Visibility is set by _enforce_visibility; this only fades in
        # cosmetically afterwards. It must NEVER determine final alpha.
        panel.orderFrontRegardless()
        panel.setAlphaValue_(1.0)

    def _hide_panel(self, panel, duration=0.0):
        # Synchronous hide — no fade, no completion handler, no race.
        panel.orderOut_(None)

    def _show_wings_mode(self, mode):
        """Notch path: the strip handles recording/processing/success."""
        self._ensure_wings()
        self.wings_view.setMode_(mode)

    # -- public API (main thread only) --------------------------------------

    def _collapse_done(self, gen: int) -> None:
        """Generation-guarded collapse completion: re-mode only if no newer
        state arrived mid-sweep; visibility re-derived afterwards either way."""
        if gen != self._vis_gen:
            return
        self._show_wings_mode("processing")
        self._enforce_visibility()

    def set_state(self, state: str) -> None:
        if state not in STATES:
            return
        # Any real state change dismisses a pending notice instantly.
        self._notice_gen += 1
        self._state = state
        wings_up = self.wings is not None and self.wings.isVisible()
        if state in RECORDING_STATES:
            self._levels.clear()
            self._ema = 0.0
        self.view.setState_(state)

        if self._geometry is not None:
            # Notch machines: the strip is the single status surface; the
            # menu-row pill only appears for edit cues (clickable).
            if state == "idle":
                if wings_up:
                    self.wings_view.stopAnimation()
            elif state in RECORDING_STATES:
                self._show_wings_mode("recording")
            elif state == "processing":
                if wings_up:
                    # collapse inward first, THEN the strip returns in blue
                    self.wings_view._on_collapse_done = \
                        lambda gen=self._vis_gen: self._collapse_done(gen)
                    self.wings_view.startCollapse()
                else:
                    self._show_wings_mode("processing")
            elif state == "success":
                self._show_wings_mode("success")
        # Corner style / no aux areas: the pill handles everything (wings are
        # only ever created with notch geometry, so this path is pill-only).
        self._enforce_visibility()

    # -- notices (idle-only visual confirmations) -----------------------------

    def notice(self, text: str, kind: str = "success", seconds: float = 1.5) -> None:
        """Flash a short confirmation (learned term, cancellation, …).

        Fires only while idle — never clobbers recording/processing/success.
        Auto-hides after `seconds`; any real set_state dismisses it instantly.
        """
        if self._state != "idle":
            log.info("notice skipped (state=%s): %s", self._state, text)
            return
        self._notice_gen += 1
        gen = self._notice_gen
        self._state = "notice"
        if self._geometry is not None:
            self._notice_surface = "wings"
            self._ensure_wings()
            self.wings_view.displayNotice_kind_(text, kind)
        else:
            self._notice_surface = "pill"
            self.view.displayNotice_kind_(text, kind)
        self._enforce_visibility()
        from PyObjCTools import AppHelper
        AppHelper.callLater(seconds, self._dismiss_notice, gen)

    def _dismiss_notice(self, gen: int) -> None:
        if gen != self._notice_gen or self._state != "notice":
            return  # superseded or already dismissed by a real state change
        self._state = "idle"
        self.view._on_click = None
        self._enforce_visibility()

    # -- edit cues (clickable pill: "wrong → right ✓?") -------------------------

    def cue(self, wrong: str, right: str, seconds: float, on_accept) -> None:
        """Show an actionable edit cue on the PILL (even on notch machines):
        `wrong → right ✓?`, blue dot. Clicking accepts (on_accept) → green
        "✓ learned" flash → hide. Timeout hides silently. One pending cue at
        a time — a new cue replaces the visible one. Never clobbers real
        states (recording/processing/success).
        """
        if self._state not in ("idle", "notice"):
            log.info("cue skipped (state=%s): %s → %s", self._state, wrong, right)
            return
        pair = f"{wrong} → {right}"
        if len(pair) > 26:
            pair = pair[:25] + "…"
        self._notice_gen += 1
        gen = self._notice_gen
        self._state = "notice"
        self._notice_surface = "pill"
        self.view.displayNotice_kind_(pair + " ✓?", "info")
        self.view._on_click = lambda: self._accept_cue(gen, wrong, right, on_accept)
        self._enforce_visibility()
        from PyObjCTools import AppHelper
        AppHelper.callLater(seconds, self._dismiss_notice, gen)

    def _accept_cue(self, gen: int, wrong: str, right: str, on_accept) -> None:
        if gen != self._notice_gen or self._state != "notice":
            return  # stale click (cue already replaced/dismissed)
        self._notice_gen += 1
        self._state = "idle"
        self.view._on_click = None
        try:
            on_accept(wrong, right)
        except Exception as e:
            log.warning("cue accept failed: %s", e)
        self.notice("✓ learned", "success", 1.0)

    def push_level(self, rms: float) -> None:
        """Feed one RMS sample into the waveform buffer (main thread only).

        An EMA (new = 0.5*old + 0.5*incoming) smooths the series so bar
        motion reads fluid instead of jumpy."""
        self._ema = LEVEL_EMA * self._ema + (1 - LEVEL_EMA) * float(rms)
        self._levels.append(self._ema)
        now = time.monotonic()
        if now - self._last_level_draw < LEVEL_MIN_INTERVAL:
            return
        self._last_level_draw = now
        if self.wings is not None and self.wings.isVisible():
            self.wings_view.setNeedsDisplay_(True)
        else:
            self.view.setNeedsDisplay_(True)
