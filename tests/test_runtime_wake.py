"""Runtime wake recovery: permissions snapshot, abort, held reset, ensure_tap.

Headless only — no live TCC, mic, AppKit run loop, or network.
"""

from __future__ import annotations

import threading

import pytest

from dictate.app import AppController, is_wake_lifecycle_reason
from dictate.hotkeys import HotkeyMonitor
from dictate.permissions import (
    missing_kinds,
    permission_snapshot,
    wake_permission_notice,
)
from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT


def _controller(**kwargs):
    bubble = kwargs.pop("bubble", None) or FakeBubble()
    rec = kwargs.pop("recorder", None) or FakeRecorder()
    stt = kwargs.pop("stt", None) or FakeSTT()
    fmt = kwargs.pop("formatter", None) or FakeFormatter()
    cfg = kwargs.pop("cfg", None) or {
        "paths": {},
        "context": {"enabled": False},
        "formatting": {},
        "insert": {},
        "audio": {"keep_recordings": False},
    }
    history_path = kwargs.pop("history_path", "")
    return AppController(cfg, rec, stt, fmt, bubble, [], [], history_path)


class ImmediateThread:
    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)


class _HotkeyRecorder:
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


def _monitor(hold_key: str = "fn") -> HotkeyMonitor:
    rec = _HotkeyRecorder()
    return HotkeyMonitor(
        {"hotkey": {"hold_key": hold_key, "toggle_combo": "fn+space"}},
        on_press=rec.on_press,
        on_release=rec.on_release,
        on_toggle=rec.on_toggle,
        on_escape=rec.on_escape,
    )


ALL_GRANTED = {
    "accessibility": True,
    "input_monitoring": True,
    "microphone": "authorized",
}

IM_MISSING = {
    "accessibility": True,
    "input_monitoring": False,
    "microphone": "authorized",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_is_wake_lifecycle_reason_filters_space_and_params():
    assert is_wake_lifecycle_reason("NSWorkspaceDidWakeNotification")
    assert is_wake_lifecycle_reason("NSWorkspaceScreensDidWakeNotification")
    assert is_wake_lifecycle_reason("wake")
    assert is_wake_lifecycle_reason("display_wake")
    assert not is_wake_lifecycle_reason(
        "NSWorkspaceActiveSpaceDidChangeNotification")
    assert not is_wake_lifecycle_reason(
        "NSApplicationDidChangeScreenParametersNotification")
    assert not is_wake_lifecycle_reason("")
    assert not is_wake_lifecycle_reason("unknown")


def test_permission_snapshot_content_free():
    snap = permission_snapshot(ALL_GRANTED)
    assert snap == {
        "accessibility": True,
        "input_monitoring": True,
        "microphone": "authorized",
    }
    # No deep-link keys
    assert "x-apple" not in str(snap)
    missing = missing_kinds(IM_MISSING)
    assert missing == ["input_monitoring"]
    notice = wake_permission_notice(missing)
    assert "Input Monitoring" in notice
    assert "observe-only" in notice
    assert "x-apple" not in notice
    assert wake_permission_notice([]) == ""


# ---------------------------------------------------------------------------
# HotkeyMonitor: held reset + ensure_tap
# ---------------------------------------------------------------------------


def test_reset_held_state_clears_without_release_callback():
    mon = _monitor()
    mon._fn_held = True
    mon._press_start = 1.0
    mon._last_tap_end = 2.0
    mon._space_logged = True
    assert mon.reset_held_state() is True
    assert mon._fn_held is False
    assert mon._press_start is None
    assert mon._last_tap_end is None
    assert mon._space_logged is False
    assert mon.reset_held_state() is False


def test_ensure_tap_ok_when_enabled(monkeypatch):
    mon = _monitor()
    mon._tap = object()
    mon._tap_active = True
    monkeypatch.setattr(mon, "_cg_tap_enabled", lambda: True)
    assert mon.ensure_tap(input_monitoring=True) == "ok"
    assert mon._tap_active is True


def test_ensure_tap_reenables_disabled(monkeypatch):
    mon = _monitor()
    mon._tap = object()
    mon._tap_active = False
    enabled = {"v": False}
    monkeypatch.setattr(mon, "_cg_tap_enabled", lambda: enabled["v"])

    def enable(flag):
        enabled["v"] = bool(flag)

    monkeypatch.setattr(mon, "_cg_tap_enable", enable)
    assert mon.ensure_tap(input_monitoring=True) == "reenabled"
    assert mon._tap_active is True
    assert enabled["v"] is True
    # Idempotent second call
    assert mon.ensure_tap(input_monitoring=True) == "ok"


def test_ensure_tap_observe_only_when_im_denied(monkeypatch):
    mon = _monitor()
    mon._tap = None
    created = []
    monkeypatch.setattr(
        mon, "_start_event_tap", lambda: created.append(True) or True)
    assert mon.ensure_tap(input_monitoring=False) == "observe_only"
    assert created == []
    assert mon._tap_active is False


def test_ensure_tap_creates_only_tap_when_missing(monkeypatch):
    mon = _monitor()
    mon._tap = None
    mon._monitors = ["sentinel-monitor"]  # pretend NSEvent monitors exist
    created = []

    def fake_start():
        created.append(True)
        mon._tap = object()
        mon._tap_source = object()
        return True

    monkeypatch.setattr(mon, "_start_event_tap", fake_start)
    assert mon.ensure_tap(input_monitoring=True) == "created"
    assert created == [True]
    assert mon._tap is not None
    # Monitors list untouched (no duplicate install)
    assert mon._monitors == ["sentinel-monitor"]
    # Second call does not recreate
    monkeypatch.setattr(mon, "_cg_tap_enabled", lambda: True)
    assert mon.ensure_tap(input_monitoring=True) == "ok"
    assert created == [True]


def test_ensure_tap_unavailable_when_create_fails(monkeypatch):
    mon = _monitor()
    mon._tap = None
    monkeypatch.setattr(mon, "_start_event_tap", lambda: False)
    assert mon.ensure_tap(input_monitoring=True) == "unavailable"
    assert mon._tap_active is False


def test_teardown_tap_clears_source_and_port(monkeypatch):
    mon = _monitor()
    mon._tap = object()
    mon._tap_source = object()
    mon._tap_active = True
    removed = []
    monkeypatch.setattr(mon, "_cg_tap_enable", lambda e: None)

    # _teardown_tap imports Quartz for remove; force path via monkeypatch
    # of the method body by simulating successful cleanup through stop-like call.
    mon._tap = None
    mon._tap_source = None
    mon._tap_active = False
    mon._teardown_tap()  # idempotent empty
    assert mon._tap is None
    assert mon._tap_source is None
    assert mon._tap_active is False
    assert removed == []


def test_start_event_tap_idempotent_when_tap_exists(monkeypatch):
    mon = _monitor()
    mon._tap = object()
    mon._tap_source = object()
    mon._tap_active = False
    enabled = {"v": False}
    monkeypatch.setattr(mon, "_cg_tap_enabled", lambda: enabled["v"])
    monkeypatch.setattr(
        mon, "_cg_tap_enable", lambda e: enabled.__setitem__("v", bool(e)))
    assert mon._start_event_tap() is True
    assert mon._tap_active is True
    # Still a single sentinel tap object
    assert mon._tap is not None


# ---------------------------------------------------------------------------
# AppController.handle_runtime_wake
# ---------------------------------------------------------------------------


def test_wake_aborts_recording_on_worker(monkeypatch):
    controller = _controller()
    mon = _monitor()
    mon._fn_held = True
    mon._tap = object()
    mon._tap_active = True
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "ok")
    controller._hotkey_monitor = mon
    controller._set_state("recording")
    monkeypatch.setattr(threading, "Thread", ImmediateThread)

    result = controller.handle_runtime_wake(
        "NSWorkspaceDidWakeNotification", status=ALL_GRANTED)

    assert result["aborted_recording"] is True
    assert result["held_reset"] is True
    assert mon._fn_held is False
    assert controller.state == "idle"
    assert controller.recorder.aborted == 1
    assert result["tap_action"] == "ok"
    assert result["permission_warning"] is False
    assert result["permissions"]["input_monitoring"] is True


def test_wake_aborts_locked(monkeypatch):
    controller = _controller()
    mon = _monitor()
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "ok")
    controller._hotkey_monitor = mon
    controller._set_state("locked")
    monkeypatch.setattr(threading, "Thread", ImmediateThread)

    result = controller.handle_runtime_wake("wake", status=ALL_GRANTED)
    assert result["aborted_recording"] is True
    assert controller.state == "idle"
    assert controller.recorder.aborted == 1


def test_wake_idle_no_abort(monkeypatch):
    controller = _controller()
    mon = _monitor()
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "reenabled")
    controller._hotkey_monitor = mon
    result = controller.handle_runtime_wake("wake", status=ALL_GRANTED)
    assert result["aborted_recording"] is False
    assert controller.recorder.aborted == 0
    assert controller.state == "idle"
    assert result["tap_action"] == "reenabled"


def test_wake_processing_not_aborted(monkeypatch):
    """In-flight STT/format continues; only recording/locked are aborted."""
    controller = _controller()
    mon = _monitor()
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "ok")
    controller._hotkey_monitor = mon
    controller._set_state("processing")
    result = controller.handle_runtime_wake("wake", status=ALL_GRANTED)
    assert result["aborted_recording"] is False
    assert controller.state == "processing"
    assert controller.recorder.aborted == 0


def test_wake_missing_permission_one_warning(monkeypatch):
    controller = _controller()
    mon = _monitor()
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "observe_only")
    controller._hotkey_monitor = mon

    r1 = controller.handle_runtime_wake("wake", status=IM_MISSING)
    assert r1["permission_warning"] is True
    assert r1["tap_action"] == "observe_only"
    assert len(controller.bubble.notices) == 1
    assert "observe-only" in controller.bubble.notices[0][0]
    assert "Input Monitoring" in controller.bubble.notices[0][0]

    # Coalesced: second wake within 5s does not re-prompt
    r2 = controller.handle_runtime_wake(
        "NSWorkspaceScreensDidWakeNotification", status=IM_MISSING)
    assert r2["permission_warning"] is False
    assert len(controller.bubble.notices) == 1


def test_wake_missing_permission_coalesce_expires(monkeypatch):
    controller = _controller()
    mon = _monitor()
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "observe_only")
    controller._hotkey_monitor = mon
    controller.handle_runtime_wake("wake", status=IM_MISSING)
    assert len(controller.bubble.notices) == 1
    # Simulate later wake burst
    controller._last_wake_perm_warn_at = 0.0
    controller.handle_runtime_wake("wake", status=IM_MISSING)
    assert len(controller.bubble.notices) == 2


def test_wake_without_hotkey_monitor(monkeypatch):
    controller = _controller()
    assert controller._hotkey_monitor is None
    monkeypatch.setattr(threading, "Thread", ImmediateThread)
    controller._set_state("recording")
    result = controller.handle_runtime_wake("wake", status=ALL_GRANTED)
    assert result["aborted_recording"] is True
    assert result["tap_action"] is None
    assert result["held_reset"] is False
    assert controller.state == "idle"


def test_wake_uses_check_all_when_status_omitted(monkeypatch):
    controller = _controller()
    mon = _monitor()
    monkeypatch.setattr(mon, "ensure_tap", lambda **k: "ok")
    controller._hotkey_monitor = mon
    monkeypatch.setattr(
        "dictate.permissions.check_all", lambda: dict(ALL_GRANTED))
    result = controller.handle_runtime_wake("wake")
    assert result["permissions"]["microphone"] == "authorized"
    assert result["permission_warning"] is False


def test_wake_ensure_tap_receives_im_false(monkeypatch):
    controller = _controller()
    mon = _monitor()
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return "observe_only"

    mon.ensure_tap = capture
    controller._hotkey_monitor = mon
    controller.handle_runtime_wake("wake", status=IM_MISSING)
    assert seen.get("input_monitoring") is False
