#!/usr/bin/env python3
"""Headless regression checks for hotkey routing (no UI / no live key events).

Covers pure flag decisions, CGEventTap modifier delivery, NSEvent fallback,
tap+monitor no double-fire, Space/F5 swallow semantics, and disabled-tap
recovery that clears stuck held state.
"""

from __future__ import annotations

from dictate.hotkeys import (
    CG_EVENT_FLAG_MASK_ALTERNATE,
    CG_EVENT_FLAG_MASK_COMMAND,
    CG_EVENT_FLAG_MASK_SECONDARY_FN,
    CG_EVENT_FLAGS_CHANGED,
    CG_EVENT_KEY_DOWN,
    CG_EVENT_KEY_UP,
    HotkeyMonitor,
    KVK_F5,
    KVK_FN,
    KVK_RIGHT_COMMAND,
    KVK_RIGHT_OPTION,
    KVK_SPACE,
    modifier_hold_down,
    should_consume,
)


class _Recorder:
    def __init__(self):
        self.presses = 0
        self.releases = 0
        self.toggles = 0
        self.escapes = 0

    def on_press(self):
        self.presses += 1

    def on_release(self):
        self.releases += 1

    def on_toggle(self):
        self.toggles += 1

    def on_escape(self):
        self.escapes += 1


def _monitor(hold_key: str = "fn", locked: bool = False) -> tuple[HotkeyMonitor, _Recorder]:
    rec = _Recorder()
    mon = HotkeyMonitor(
        {"hotkey": {"hold_key": hold_key, "toggle_combo": "fn+space"}},
        on_press=rec.on_press,
        on_release=rec.on_release,
        on_toggle=rec.on_toggle,
        is_locked=lambda: locked,
        on_escape=rec.on_escape,
    )
    return mon, rec


class _FakeNSEvent:
    def __init__(self, keycode: int, flags: int = 0):
        self._keycode = keycode
        self._flags = flags

    def keyCode(self):
        return self._keycode

    def modifierFlags(self):
        return self._flags


# -- pure helpers -------------------------------------------------------------

def test_fn_flag_mask_matches_quartz_secondary_fn():
    """Named constant must be 0x800000 (kCGEventFlagMaskSecondaryFn), not 0x200000."""
    assert CG_EVENT_FLAG_MASK_SECONDARY_FN == 0x800000
    # Old wrong mask must not be treated as SecondaryFn.
    assert not should_consume(KVK_SPACE, False, 0x200000)
    assert should_consume(KVK_SPACE, False, 0x800000)
    assert should_consume(KVK_SPACE, True, 0)
    assert not should_consume(KVK_SPACE, False, 0)
    assert not should_consume(KVK_F5, True, 0x800000)


def test_modifier_hold_down_keycode_and_flags():
    assert modifier_hold_down("fn", KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN) is True
    assert modifier_hold_down("fn", KVK_FN, 0) is False
    assert modifier_hold_down("fn", KVK_RIGHT_OPTION, CG_EVENT_FLAG_MASK_SECONDARY_FN) is None
    assert modifier_hold_down("right_option", KVK_RIGHT_OPTION,
                              CG_EVENT_FLAG_MASK_ALTERNATE) is True
    assert modifier_hold_down("right_option", KVK_RIGHT_OPTION, 0) is False
    # Left option shares the Alternate flag but wrong keycode → ignore.
    assert modifier_hold_down("right_option", 58, CG_EVENT_FLAG_MASK_ALTERNATE) is None
    assert modifier_hold_down("right_command", KVK_RIGHT_COMMAND,
                              CG_EVENT_FLAG_MASK_COMMAND) is True
    assert modifier_hold_down("right_command", KVK_RIGHT_COMMAND, 0) is False
    assert modifier_hold_down("f5", KVK_F5, 0) is None


# -- CGEventTap modifier path -------------------------------------------------

def test_tap_modifier_fn_down_up_once():
    mon, rec = _monitor("fn")
    mon._tap_active = True

    pass_through = mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert pass_through is True  # modifiers are never swallowed
    assert mon._fn_held is True
    assert rec.presses == 1
    assert rec.releases == 0

    # Repeat flagsChanged with fn still down must not double-press.
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert rec.presses == 1

    mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
    assert mon._fn_held is False
    assert rec.releases == 1


def test_tap_modifier_right_option_and_command():
    mon, rec = _monitor("right_option")
    mon._tap_active = True
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_RIGHT_OPTION, CG_EVENT_FLAG_MASK_ALTERNATE)
    mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_RIGHT_OPTION, 0)
    assert (rec.presses, rec.releases) == (1, 1)

    mon, rec = _monitor("right_command")
    mon._tap_active = True
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_RIGHT_COMMAND, CG_EVENT_FLAG_MASK_COMMAND)
    mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_RIGHT_COMMAND, 0)
    assert (rec.presses, rec.releases) == (1, 1)


# -- NSEvent fallback + no double-fire ----------------------------------------

def test_nsevent_fallback_when_tap_inactive():
    mon, rec = _monitor("fn")
    mon._tap_active = False
    mon._flags_changed(_FakeNSEvent(KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN))
    assert rec.presses == 1
    mon._flags_changed(_FakeNSEvent(KVK_FN, 0))
    assert rec.releases == 1


def test_tap_plus_monitor_no_double_fire():
    mon, rec = _monitor("fn")
    mon._tap_active = True

    # Tap delivers press/release.
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
    assert (rec.presses, rec.releases) == (1, 1)

    # NSEvent flagsChanged must not fire again while tap owns the path.
    mon._flags_changed(_FakeNSEvent(KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN))
    mon._flags_changed(_FakeNSEvent(KVK_FN, 0))
    assert (rec.presses, rec.releases) == (1, 1)


# -- Space combo + F5 ---------------------------------------------------------

def test_space_down_toggles_once_up_swallowed():
    mon, rec = _monitor("fn")
    mon._tap_active = True
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert mon._fn_held is True

    # keyDown: toggle + swallow
    assert mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_SPACE, 0) is False
    assert rec.toggles == 1
    # keyUp: swallow, no second toggle
    assert mon.handle_cg_event(CG_EVENT_KEY_UP, KVK_SPACE, 0) is False
    assert rec.toggles == 1

    # Event-local SecondaryFn fallback when _fn_held was missed.
    mon2, rec2 = _monitor("fn")
    mon2._tap_active = True
    assert mon2._fn_held is False
    assert mon2.handle_cg_event(
        CG_EVENT_KEY_DOWN, KVK_SPACE, CG_EVENT_FLAG_MASK_SECONDARY_FN) is False
    assert rec2.toggles == 1
    # Wrong legacy mask must not trigger consume.
    mon3, rec3 = _monitor("fn")
    assert mon3.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_SPACE, 0x200000) is True
    assert rec3.toggles == 0


def test_f5_down_up_swallowed_once_each():
    mon, rec = _monitor("f5")
    mon._tap_active = True

    assert mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_F5, 0) is False
    assert rec.presses == 1
    assert mon._fn_held is True

    # Second keyDown while held (auto-repeat) must not double-press.
    assert mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_F5, 0) is False
    assert rec.presses == 1

    assert mon.handle_cg_event(CG_EVENT_KEY_UP, KVK_F5, 0) is False
    assert rec.releases == 1
    assert mon._fn_held is False

    # NSEvent path must not double-fire while tap is active.
    mon._key_down(_FakeNSEvent(KVK_F5))
    mon._key_up(_FakeNSEvent(KVK_F5))
    assert (rec.presses, rec.releases) == (1, 1)


def test_f5_nsevent_fallback_when_tap_inactive():
    mon, rec = _monitor("f5")
    mon._tap_active = False
    mon._key_down(_FakeNSEvent(KVK_F5))
    mon._key_up(_FakeNSEvent(KVK_F5))
    assert (rec.presses, rec.releases) == (1, 1)


# -- disabled-tap recovery ----------------------------------------------------

def test_disabled_tap_recovery_clears_stuck_held():
    mon, rec = _monitor("fn")
    mon._tap_active = True
    mon._tap = None  # no real Mach port; recovery skips CGEventTapEnable
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert mon._fn_held is True
    assert rec.presses == 1

    # Simulate missed release + macOS disable: force one release, not stuck.
    mon._recover_disabled_tap()
    assert mon._fn_held is False
    assert rec.releases == 1

    # Next press works (was a permanent no-op when stuck held).
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert rec.presses == 2

    # Recovery while not held must not invent a release.
    mon._release()
    mon._recover_disabled_tap()
    assert rec.releases == 2  # only the genuine release above


def main() -> int:
    tests = [
        test_fn_flag_mask_matches_quartz_secondary_fn,
        test_modifier_hold_down_keycode_and_flags,
        test_tap_modifier_fn_down_up_once,
        test_tap_modifier_right_option_and_command,
        test_nsevent_fallback_when_tap_inactive,
        test_tap_plus_monitor_no_double_fire,
        test_space_down_toggles_once_up_swallowed,
        test_f5_down_up_swallowed_once_each,
        test_f5_nsevent_fallback_when_tap_inactive,
        test_disabled_tap_recovery_clears_stuck_held,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f" FAIL {fn.__name__}: {e}")
    print(f"{'PASS' if failed == 0 else 'FAIL'}: {len(tests) - failed}/{len(tests)} hotkey event cases")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
