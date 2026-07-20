"""Hotkey decision/event matrix (headless; no live key events)."""

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
    double_tap_decision,
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


def test_fn_flag_mask_matches_quartz_secondary_fn():
    assert CG_EVENT_FLAG_MASK_SECONDARY_FN == 0x800000
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
    assert modifier_hold_down("right_option", 58, CG_EVENT_FLAG_MASK_ALTERNATE) is None
    assert modifier_hold_down("right_command", KVK_RIGHT_COMMAND,
                              CG_EVENT_FLAG_MASK_COMMAND) is True
    assert modifier_hold_down("right_command", KVK_RIGHT_COMMAND, 0) is False
    assert modifier_hold_down("f5", KVK_F5, 0) is None


def test_tap_modifier_fn_down_up_once():
    mon, rec = _monitor("fn")
    mon._tap_active = True
    pass_through = mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert pass_through is True
    assert mon._fn_held is True
    assert rec.presses == 1
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
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
    assert (rec.presses, rec.releases) == (1, 1)
    mon._flags_changed(_FakeNSEvent(KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN))
    mon._flags_changed(_FakeNSEvent(KVK_FN, 0))
    assert (rec.presses, rec.releases) == (1, 1)


def test_space_down_toggles_once_up_swallowed():
    mon, rec = _monitor("fn")
    mon._tap_active = True
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_SPACE, 0) is False
    assert rec.toggles == 1
    assert mon.handle_cg_event(CG_EVENT_KEY_UP, KVK_SPACE, 0) is False
    assert rec.toggles == 1

    mon2, rec2 = _monitor("fn")
    mon2._tap_active = True
    assert mon2.handle_cg_event(
        CG_EVENT_KEY_DOWN, KVK_SPACE, CG_EVENT_FLAG_MASK_SECONDARY_FN) is False
    assert rec2.toggles == 1
    mon3, rec3 = _monitor("fn")
    assert mon3.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_SPACE, 0x200000) is True
    assert rec3.toggles == 0


def test_f5_down_up_swallowed_once_each():
    mon, rec = _monitor("f5")
    mon._tap_active = True
    assert mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_F5, 0) is False
    assert rec.presses == 1
    assert mon._fn_held is True
    assert mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_F5, 0) is False
    assert rec.presses == 1
    assert mon.handle_cg_event(CG_EVENT_KEY_UP, KVK_F5, 0) is False
    assert rec.releases == 1
    assert mon._fn_held is False
    mon._key_down(_FakeNSEvent(KVK_F5))
    mon._key_up(_FakeNSEvent(KVK_F5))
    assert (rec.presses, rec.releases) == (1, 1)


def test_f5_nsevent_fallback_when_tap_inactive():
    mon, rec = _monitor("f5")
    mon._tap_active = False
    mon._key_down(_FakeNSEvent(KVK_F5))
    mon._key_up(_FakeNSEvent(KVK_F5))
    assert (rec.presses, rec.releases) == (1, 1)


def test_disabled_tap_recovery_clears_stuck_held():
    mon, rec = _monitor("fn")
    mon._tap_active = True
    mon._tap = None
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert mon._fn_held is True
    mon._recover_disabled_tap()
    assert mon._fn_held is False
    assert rec.releases == 1
    mon.handle_cg_event(
        CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
    assert rec.presses == 2
    mon._release()
    mon._recover_disabled_tap()
    assert rec.releases == 2


def test_double_tap_decision_matrix():
    assert double_tap_decision(1.0, 0.5, None) == ("hold", None)
    assert double_tap_decision(1.0, 0.1, None)[0] == "tap"
    tap_end = double_tap_decision(1.0, 0.1, None)[1]
    assert double_tap_decision(1.2, 0.1, tap_end) == ("double_tap", None)
    assert double_tap_decision(2.0, 0.1, tap_end)[0] == "tap"


def test_configure_hold_key():
    mon, _rec = _monitor("fn")
    mon.configure({"hotkey": {"hold_key": "f5", "toggle_combo": "fn+space"}})
    assert mon.hold_key == "f5"
    mon.configure({"hotkey": {"hold_key": "not-a-key"}})
    assert mon.hold_key == "fn"
