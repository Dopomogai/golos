"""Global hotkey monitoring via NSEvent global monitors (observe-only) + a
CGEventTap for the keys we must swallow and for deterministic modifier holds.

Hold-to-talk key (configurable, [hotkey] hold_key):
- "fn" (globe, default) / "right_option" / "right_command": modifiers.
  When the CGEventTap is active they are delivered via flagsChanged on the
  tap (keycode-filtered). NSEvent flagsChanged is the observe-only fallback
  when the tap cannot be created.
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
KVK_FN = 63  # Globe / fn on Apple keyboards

HOLD_KEYS = ("fn", "right_option", "right_command", "f5")

# Modifier hold keys → physical keycode (right-side only for option/command).
MODIFIER_HOLD_KEYCODES = {
    "fn": KVK_FN,
    "right_option": KVK_RIGHT_OPTION,
    "right_command": KVK_RIGHT_COMMAND,
}

# Quartz CGEvent flag masks (named constants so pure helpers stay headless).
# kCGEventFlagMaskSecondaryFn == 0x800000 — same numeric value as
# NSEventModifierFlagFunction; the old 0x200000 literal was wrong and broke
# the event-local fallback when _fn_held missed a press.
CG_EVENT_FLAG_MASK_SECONDARY_FN = 0x800000
CG_EVENT_FLAG_MASK_ALTERNATE = 0x00080000
CG_EVENT_FLAG_MASK_COMMAND = 0x00100000

MODIFIER_HOLD_FLAG_MASKS = {
    "fn": CG_EVENT_FLAG_MASK_SECONDARY_FN,
    "right_option": CG_EVENT_FLAG_MASK_ALTERNATE,
    "right_command": CG_EVENT_FLAG_MASK_COMMAND,
}

# CGEvent type integers (match Quartz) — kept here for headless tests.
CG_EVENT_KEY_DOWN = 10
CG_EVENT_KEY_UP = 11
CG_EVENT_FLAGS_CHANGED = 12
CG_EVENT_TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
CG_EVENT_TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFF

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
    when our flagsChanged path missed the press (e.g. fullscreen apps).
    Uses kCGEventFlagMaskSecondaryFn (== CG_EVENT_FLAG_MASK_SECONDARY_FN).
    """
    return keycode == KVK_SPACE and (
        fn_held or bool(flags & CG_EVENT_FLAG_MASK_SECONDARY_FN))


def modifier_hold_down(hold_key: str, keycode: int, flags: int) -> bool | None:
    """Pure flagsChanged decision for a configured modifier hold key.

    Returns True when the hold key is down, False when up, or None when this
    event is not the configured modifier (wrong keycode or non-modifier hold).
    Only the physical keycode for that hold key is considered (fn=63,
    right_option=61, right_command=54) so left option/command never match.
    """
    expected = MODIFIER_HOLD_KEYCODES.get(hold_key)
    if expected is None or keycode != expected:
        return None
    mask = MODIFIER_HOLD_FLAG_MASKS[hold_key]
    return bool(flags & mask)


class HotkeyMonitor:
    """Posts on_press / on_release / on_toggle / on_escape from global key events.

    Two complementary paths (both deliver on the main run loop):
    - NSEvent global monitors: observe-only — modifiers via flagsChanged,
      F5/Space/Esc via keyDown/keyUp when no tap is active.
    - CGEventTap: owns modifier hold-key flagsChanged (keycode-filtered),
      and can *swallow* Space (and F5 when hold_key=f5) so the target app
      never sees them. When the tap is active, the monitor path must not
      double-fire the same combo (see _key_down / _key_up / _flags_changed
      early returns).

    Failure mode: without Input Monitoring the tap is None and Space still
    types a character while the hold key is down (observe-only fallback).
    """

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
        """Read [hotkey] hold_key / toggle_combo; invalid hold_key falls back to fn."""
        hk = cfg.get("hotkey", {})
        hold_key = hk.get("hold_key", "fn")
        if hold_key not in HOLD_KEYS:
            log.warning("Unknown hold_key %r; falling back to 'fn'.", hold_key)
            hold_key = "fn"
        self.hold_key = hold_key
        self.toggle_combo = hk.get("toggle_combo", "fn+space")

    def start(self) -> None:
        """Install NSEvent monitors + CGEventTap. Call on the main thread.

        Retained objects: each addGlobalMonitor… return value and the tap
        Mach port must stay reachable (held on self) until stop(); CFRunLoop
        source is tied to the current run loop (the main one at app launch).
        """
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
        """Tear down monitors and disable the tap (idempotent if already stopped)."""
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

    # -- event tap: modifiers + swallow Space (combo) and F5 (hold key) -------

    def _start_event_tap(self) -> bool:
        """Install a CGEventTap for modifier flagsChanged, combo Space, and
        (when hold_key=f5) F5 itself. Returns True when active. Falls back
        to observe-only NSEvent monitors when creation fails."""
        try:
            from Quartz import (
                CGEventTapCreate, CGEventMaskBit, CGEventTapEnable,
                CGEventGetIntegerValueField, CGEventGetFlags,
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionDefault, kCGEventKeyDown, kCGEventKeyUp,
                kCGEventFlagsChanged, kCGKeyboardEventKeycode,
                kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput,
                CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
                CFRunLoopAddSource, kCFRunLoopCommonModes,
            )
        except ImportError as e:
            log.warning("Event tap unavailable (%s); observe-only fallback.", e)
            return False

        def callback(proxy, event_type, event, refcon):
            # Disabled-tap notifications have no usable key event payload.
            if event_type in (kCGEventTapDisabledByTimeout,
                              kCGEventTapDisabledByUserInput):
                self._recover_disabled_tap()
                return event
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            flags = CGEventGetFlags(event)
            return event if self.handle_cg_event(event_type, keycode, flags) else None

        mask = (CGEventMaskBit(kCGEventKeyDown)
                | CGEventMaskBit(kCGEventKeyUp)
                | CGEventMaskBit(kCGEventFlagsChanged))
        tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
            mask, callback, None)
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

    def handle_cg_event(self, event_type: int, keycode: int, flags: int) -> bool:
        """Process a CGEventTap event by type/keycode/flags.

        Returns True when the event should pass through to the focused app,
        False when it must be swallowed (Space combo, F5 hold key). Pure
        enough for headless tests — no Quartz event objects required.

        Disabled-tap recovery is handled separately in the real callback
        (before keycode is read); tests call `_recover_disabled_tap` directly.
        """
        if event_type == CG_EVENT_FLAGS_CHANGED:
            # Modifier hold keys: observe only — never swallow flagsChanged
            # so the system still sees the real modifier state.
            down = modifier_hold_down(self.hold_key, keycode, flags)
            if down is True:
                self._press()
            elif down is False:
                self._release()
            return True

        if keycode == KVK_ESCAPE:
            # never swallowed — the controller decides if it means "cancel"
            self.on_escape()
            return True

        if self.hold_key == "f5" and keycode == KVK_F5:
            # keyDown starts hold-to-talk; keyUp ends it. Both swallowed
            # so F5 never reaches the focused app while it is the hold key.
            if event_type == CG_EVENT_KEY_DOWN:
                self._press()
            elif event_type == CG_EVENT_KEY_UP:
                self._release()
            return False

        if should_consume(keycode, self._fn_held, flags):
            # Space combo: fire toggle only on keyDown (keyUp would
            # double-toggle). Swallow both so no space character is typed.
            if event_type == CG_EVENT_KEY_DOWN:
                if not self._space_logged:
                    self._space_logged = True
                    log.info("space seen via event tap (held=%s, fn_flag=%s)",
                             self._fn_held,
                             bool(flags & CG_EVENT_FLAG_MASK_SECONDARY_FN))
                self.on_toggle()
            return False  # consumed (down AND up): no space reaches the app

        return True

    def _recover_disabled_tap(self) -> None:
        """Re-enable after macOS disables the tap; clear stuck held state.

        Safest reconciliation: if we still think the hold key is down, force
        exactly one `_release()` so a missed flagsChanged-up cannot leave
        recording stuck and cannot make the next press a permanent no-op.
        At most one pipeline completion; no duplicate toggle. If the key is
        still physically held, the user must release and press again (macOS
        will not re-send flagsChanged until the next real transition).
        """
        if self._fn_held:
            log.warning("Event tap disabled while hold key marked held — "
                        "forcing release to avoid stuck state.")
            self._release()
        if self._tap is not None:
            from Quartz import CGEventTapEnable
            CGEventTapEnable(self._tap, True)
        else:
            # Headless / tests: still mark the logical path re-enabled.
            pass

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
        """True/False on transitions of a modifier hold key, None when unrelated.

        NSEvent fallback path only (when the CGEventTap is not active).
        """
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
        # When the CGEventTap is active it owns modifier hold-key transitions;
        # handling them here too would double-fire on_press/on_release.
        if self._tap_active:
            return
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
        # Observe-only path. When the CGEventTap is active it already owns
        # Esc/F5/Space; handling them here too would double-fire callbacks.
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
        # F5 release only: modifiers release via flagsChanged. Same tap-vs-
        # monitor exclusivity as _key_down.
        if self.hold_key == "f5" and event.keyCode() == KVK_F5:
            if not self._tap_active:
                self._release()
