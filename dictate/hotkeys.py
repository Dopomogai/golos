"""Global hotkey monitoring via NSEvent global monitors (observe-only) + a
CGEventTap for the keys we must swallow.

Hold-to-talk key (configurable, [hotkey] hold_key):
- "fn" (globe, default) / "right_option" / "right_command": modifiers,
  detected via flagsChanged (NSEventModifierFlagFunction/Option/Command).
- "f5": a regular key (keyCode 96) — detected via keyDown/keyUp, and
  CONSUMED by the event tap so F5 does nothing else while it's the hold key.

Toggle combo: "<hold key>+space" (Space swallowed via the tap) and/or
"double_fn" (double-tap the hold key to lock).

Requires Input Monitoring permission. Handlers run on the main thread.
"""

import logging
import time

log = logging.getLogger(__name__)

KVK_SPACE = 49
KVK_ESCAPE = 53
KVK_RIGHT_OPTION = 61
KVK_RIGHT_COMMAND = 54
KVK_F5 = 96

HOLD_KEYS = ("fn", "right_option", "right_command", "f5")

# double-tap tuning (seconds)
TAP_MAX_DURATION = 0.400  # a hold longer than this is never a "tap"
TAP_MAX_GAP = 0.350       # two taps further apart than this are not a double-tap


def double_tap_decision(now: float, press_duration: float,
                        last_tap_end: float | None,
                        tap_max: float = TAP_MAX_DURATION,
                        gap_max: float = TAP_MAX_GAP) -> tuple[str, float | None]:
    """Classify a just-finished key press. Pure function (timestamps in, verdict out).

    Returns (verdict, new_last_tap_end):
    - "hold":       long press — normal push-to-talk release.
    - "tap":        short press — normal release, but remember it for double-tap detection.
    - "double_tap": short press right after a previous tap — toggle locked mode.
    """
    if press_duration > tap_max:
        return "hold", last_tap_end
    if last_tap_end is not None and (now - last_tap_end) <= gap_max:
        return "double_tap", None
    return "tap", now


def should_consume(keycode: int, fn_held: bool, flags: int) -> bool:
    """Pure decision for the event tap: swallow Space while the hold key is held.

    `flags` are the CGEvent's own modifier flags; fn may register there even
    when our flagsChanged monitor missed the press (e.g. fullscreen apps).
    kCGEventFlagMaskSecondaryFn == 0x200000.
    """
    return keycode == KVK_SPACE and (fn_held or bool(flags & 0x200000))


class HotkeyMonitor:
    """Posts on_press / on_release / on_toggle callbacks from global key events."""

    def __init__(self, cfg: dict, on_press, on_release, on_toggle, is_locked=None,
                 on_escape=None):
        self.on_press = on_press
        self.on_release = on_release
        self.on_toggle = on_toggle
        self.on_escape = on_escape or (lambda: None)
        self._is_locked = is_locked or (lambda: False)
        self._fn_held = False          # the hold key (any of the four)
        self._press_start: float | None = None
        self._last_tap_end: float | None = None
        self._space_logged = False   # reset on each hold-key press
        self._monitors = []
        self._tap = None
        self._tap_active = False
        self.configure(cfg)

    def configure(self, cfg: dict) -> None:
        hk = cfg.get("hotkey", {})
        hold_key = hk.get("hold_key", "fn")
        if hold_key not in HOLD_KEYS:
            log.warning("Unknown hold_key %r; falling back to 'fn'.", hold_key)
            hold_key = "fn"
        self.hold_key = hold_key
        self.toggle_combo = hk.get("toggle_combo", "fn+space")

    def start(self) -> None:
        from AppKit import (
            NSEvent, NSEventMaskFlagsChanged, NSEventMaskKeyDown, NSEventMaskKeyUp,
        )

        self._monitors.append(NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskFlagsChanged, self._flags_changed))
        self._monitors.append(NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._key_down))
        self._monitors.append(NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyUp, self._key_up))
        self._tap_active = self._start_event_tap()
        log.info("Hotkey monitor started (hold_key=%s, toggle=%s%s, combo path: %s).",
                 self.hold_key, self.toggle_combo,
                 " + fn+space" if self.toggle_combo != "fn+space" else "",
                 "event tap (blocking)" if self._tap_active
                 else "monitor (observe-only)")

    def stop(self) -> None:
        from AppKit import NSEvent
        for m in self._monitors:
            NSEvent.removeMonitor_(m)
        self._monitors = []
        if self._tap is not None:
            from Quartz import CGEventTapEnable
            CGEventTapEnable(self._tap, False)
            self._tap = None
            self._tap_active = False

    def reconfigure(self, cfg: dict) -> None:
        """Live rebind: stop, re-read config, start again (no app restart)."""
        self.stop()
        self.configure(cfg)
        self.start()
        log.info("Hold key rebound live: %s", self.hold_key)

    # -- event tap: swallow Space (combo) and F5 (hold key) -------------------

    def _start_event_tap(self) -> bool:
        """Install a CGEventTap consuming the combo Space and, for hold_key=f5,
        F5 itself. Returns True when active. Falls back to observe-only."""
        try:
            from Quartz import (
                CGEventTapCreate, CGEventMaskBit, CGEventTapEnable,
                CGEventGetIntegerValueField, CGEventGetFlags,
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionDefault, kCGEventKeyDown, kCGEventKeyUp,
                kCGKeyboardEventKeycode, kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput, CFMachPortCreateRunLoopSource,
                CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopCommonModes,
            )
        except ImportError as e:
            log.warning("Event tap unavailable (%s); observe-only fallback.", e)
            return False

        def callback(proxy, event_type, event, refcon):
            if event_type in (kCGEventTapDisabledByTimeout,
                              kCGEventTapDisabledByUserInput):
                CGEventTapEnable(self._tap, True)
                return event
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            flags = CGEventGetFlags(event)
            if keycode == KVK_ESCAPE:
                # never swallowed — the controller decides if it means "cancel"
                self.on_escape()
                return event
            if self.hold_key == "f5" and keycode == KVK_F5:
                if event_type == kCGEventKeyDown:
                    self._press()
                else:
                    self._release()
                return None  # F5 does nothing else while it's the hold key
            if should_consume(keycode, self._fn_held, flags):
                if event_type == kCGEventKeyDown:
                    if not self._space_logged:
                        self._space_logged = True
                        log.info("space seen via event tap (held=%s, fn_flag=%s)",
                                 self._fn_held, bool(flags & 0x200000))
                    self.on_toggle()
                return None  # consumed (down AND up): no space reaches the app
            return event

        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
            CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp),
            callback, None)
        if tap is None:
            log.warning("Could not create event tap (Input Monitoring "
                        "permission missing?); observe-only fallback — "
                        "fn+Space will also type a space.")
            return False
        self._tap = tap
        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        return True

    # -- shared press/release routing ------------------------------------------

    def _press(self) -> None:
        if self._is_locked():
            # Locked recording: ANY press of the hold key ends it. Route
            # straight to on_press with no tap/double-tap bookkeeping, and
            # don't mark the key as held (the release is then a no-op here).
            self.on_press()
            return
        if not self._fn_held:
            self._fn_held = True
            self._press_start = time.monotonic()
            self._space_logged = False
            self.on_press()

    def _release(self) -> None:
        if self._fn_held:
            self._fn_held = False
            self._handle_release()

    # -- modifier hold keys (fn / right option / right command) -----------------

    def _hold_key_down(self, event) -> bool | None:
        """True/False on transitions of a modifier hold key, None when unrelated."""
        from AppKit import (NSEventModifierFlagFunction, NSEventModifierFlagOption,
                            NSEventModifierFlagCommand)

        flags = event.modifierFlags()
        if self.hold_key == "right_option":
            if event.keyCode() != KVK_RIGHT_OPTION:
                return None
            return bool(flags & NSEventModifierFlagOption)
        if self.hold_key == "right_command":
            if event.keyCode() != KVK_RIGHT_COMMAND:
                return None
            return bool(flags & NSEventModifierFlagCommand)
        if self.hold_key == "fn":
            return bool(flags & NSEventModifierFlagFunction)
        return None  # f5: handled via regular key events

    def _flags_changed(self, event) -> None:
        down = self._hold_key_down(event)
        if down is None:
            return
        if down:
            self._press()
        else:
            self._release()

    def _handle_release(self) -> None:
        if self.toggle_combo == "double_fn" and self._press_start is not None:
            now = time.monotonic()
            verdict, self._last_tap_end = double_tap_decision(
                now, now - self._press_start, self._last_tap_end)
            self._press_start = None
            if verdict == "double_tap":
                log.info("Double-tap %s detected — toggling locked mode.", self.hold_key)
                self.on_toggle()
                return
        self.on_release()

    # -- regular key events (f5 hold key, space combo, esc) ----------------------

    def _key_down(self, event) -> None:
        if event.keyCode() == KVK_ESCAPE:
            if not self._tap_active:
                self.on_escape()  # tap route handles it when active (no double-fire)
            return
        if self.hold_key == "f5" and event.keyCode() == KVK_F5:
            if not self._tap_active:
                self._press()
            return
        if event.keyCode() != KVK_SPACE:
            return
        if self._tap_active:
            return  # the event tap owns the combo — never double-fire
        from AppKit import NSEventModifierFlagFunction
        fn_flag = bool(event.modifierFlags() & NSEventModifierFlagFunction)
        if not self._space_logged:
            self._space_logged = True
            log.info("space seen (held=%s, fn_flag=%s)", self._fn_held, fn_flag)
        if self._fn_held or fn_flag:
            self.on_toggle()

    def _key_up(self, event) -> None:
        if self.hold_key == "f5" and event.keyCode() == KVK_F5:
            if not self._tap_active:
                self._release()
