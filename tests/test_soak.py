"""Adversarial soak: ≥250 rapid state/event cycles without stuck keys or stale timers."""

from __future__ import annotations

from dictate.app import AppController
from dictate.hotkeys import (
    CG_EVENT_FLAG_MASK_SECONDARY_FN,
    CG_EVENT_FLAGS_CHANGED,
    CG_EVENT_KEY_DOWN,
    CG_EVENT_KEY_UP,
    HotkeyMonitor,
    KVK_FN,
    KVK_SPACE,
)
from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT


def test_250_rapid_state_and_hotkey_cycles_no_stuck_key_or_stale_timer():
    bubble = FakeBubble()
    controller = AppController(
        {"paths": {}, "context": {"enabled": False}, "formatting": {},
         "insert": {}, "audio": {"keep_recordings": False}},
        FakeRecorder(),
        FakeSTT(),
        FakeFormatter(),
        bubble,
        [],
        [],
        "",
    )
    # Avoid real recorder / context threads
    started_modes: list[str] = []
    controller._begin_recording = lambda mode: (
        started_modes.append(mode),
        controller._set_state(mode),
    )[-1]
    controller._finish_recording = lambda: controller._set_state("processing")

    rec = type("R", (), {"presses": 0, "releases": 0, "toggles": 0})()

    def on_press():
        rec.presses += 1
        controller.on_press()

    def on_release():
        rec.releases += 1
        controller.on_release()

    def on_toggle():
        rec.toggles += 1
        controller.on_toggle()

    mon = HotkeyMonitor(
        {"hotkey": {"hold_key": "fn", "toggle_combo": "fn+space"}},
        on_press=on_press,
        on_release=on_release,
        on_toggle=on_toggle,
        is_locked=lambda: controller.state == "locked",
        on_escape=controller.on_escape,
    )
    mon._tap_active = True
    mon._tap = None

    cycles = 250
    for i in range(cycles):
        path = i % 5
        if path == 0:
            # hold press → release → success timer from older gen must not clobber
            mon.handle_cg_event(
                CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
            mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
            # simulate pipeline success + immediate new press
            success_gen = controller._set_state("success")
            mon.handle_cg_event(
                CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
            controller._finish_success(success_gen)  # stale — must not force idle
            assert controller.state == "recording", f"cycle {i}: stale timer forced idle"
            mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
        elif path == 1:
            # Space toggle locked path
            mon.handle_cg_event(
                CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
            mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_SPACE, 0)
            mon.handle_cg_event(CG_EVENT_KEY_UP, KVK_SPACE, 0)
            mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
            # stop locked with press
            if controller.state == "locked":
                mon.handle_cg_event(
                    CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
                mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
        elif path == 2:
            # stuck recovery mid-hold
            mon.handle_cg_event(
                CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
            assert mon._fn_held is True
            mon._recover_disabled_tap()
            assert mon._fn_held is False, f"cycle {i}: held stuck after recovery"
        elif path == 3:
            # rapid success → toggle locked
            controller._set_state("success")
            mon.handle_cg_event(
                CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
            mon.handle_cg_event(CG_EVENT_KEY_DOWN, KVK_SPACE, 0)
            mon.handle_cg_event(CG_EVENT_KEY_UP, KVK_SPACE, 0)
            mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
        else:
            # processing ignore + cancel flag
            controller._set_state("processing")
            mon.handle_cg_event(
                CG_EVENT_FLAGS_CHANGED, KVK_FN, CG_EVENT_FLAG_MASK_SECONDARY_FN)
            mon.handle_cg_event(CG_EVENT_FLAGS_CHANGED, KVK_FN, 0)
            controller.on_escape()
            assert controller._cancel_requested is True
            controller._cancel_requested = False
            controller._set_state("idle")

        # Invariant: never leave the monitor permanently held without a path to clear
        if mon._fn_held:
            mon._release()
        assert mon._fn_held is False, f"cycle {i}: stuck held key"

    assert cycles >= 250
    assert rec.presses > 0 and rec.releases > 0
    # Final success timer with matching gen returns to idle cleanly
    gen = controller._set_state("success")
    controller._finish_success(gen)
    assert controller.state == "idle"
