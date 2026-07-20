"""Headless AppController state transitions (fakes/mocks, no UI)."""

from __future__ import annotations

import threading

import numpy as np
import pytest

from dictate.app import AppController, _history_context
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
    c = AppController(cfg, rec, stt, fmt, bubble, [], [], history_path)
    return c


def test_press_during_success_starts_recording():
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    controller._set_state("success")
    controller.on_press()
    assert started == ["recording"]


def test_toggle_during_success_starts_locked_recording():
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    controller._set_state("success")
    controller.on_toggle()
    assert started == ["locked"]


def test_press_during_history_retry_does_not_record():
    """Immediate-repeat after success stays OK; only history_retry blocks."""
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    # Free pipeline + success: normal immediate re-press.
    controller._set_state("success")
    controller.on_press()
    assert started == ["recording"]
    started.clear()
    controller._set_state("idle")
    assert controller.try_acquire_pipeline(controller.PIPELINE_HISTORY_RETRY)
    controller.on_press()
    assert started == []
    assert controller.bubble.notices
    assert "History retry is still running" in controller.bubble.notices[-1][0]
    controller.release_pipeline(controller.PIPELINE_HISTORY_RETRY)


def test_old_success_timer_cannot_cancel_new_recording():
    controller = _controller()
    success_gen = controller._set_state("success")
    controller._set_state("recording")
    controller._finish_success(success_gen)
    assert controller.state == "recording"
    assert controller.bubble.states == ["success", "recording"]


def test_current_success_timer_returns_to_idle():
    controller = _controller()
    success_gen = controller._set_state("success")
    controller._finish_success(success_gen)
    assert controller.state == "idle"
    assert controller.bubble.states == ["success", "idle"]


def test_idle_press_begins_recording():
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    controller.on_press()
    assert started == ["recording"]


def test_recording_release_finishes():
    controller = _controller()
    finished = []
    controller._finish_recording = lambda: finished.append(True)
    controller._set_state("recording")
    controller.on_release()
    assert finished == [True]


def test_locked_ignores_release():
    controller = _controller()
    finished = []
    controller._finish_recording = lambda: finished.append(True)
    controller._set_state("locked")
    controller.on_release()
    assert finished == []


def test_locked_press_finishes():
    controller = _controller()
    finished = []
    controller._finish_recording = lambda: finished.append(True)
    controller._set_state("locked")
    controller.on_press()
    assert finished == [True]


def test_toggle_recording_to_locked():
    controller = _controller()
    controller._set_state("recording")
    controller.on_toggle()
    assert controller.state == "locked"


def test_toggle_locked_finishes():
    controller = _controller()
    finished = []
    controller._finish_recording = lambda: finished.append(True)
    controller._set_state("locked")
    controller.on_toggle()
    assert finished == [True]


def test_processing_ignores_press_and_toggle():
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    controller._set_state("processing")
    controller.on_press()
    controller.on_toggle()
    assert started == []
    assert controller.state == "processing"


def test_escape_cancels_recording(monkeypatch):
    controller = _controller()
    discarded = []
    controller._set_state("recording")
    controller._discard_recording = lambda: discarded.append(True)

    class ImmediateThread:
        def __init__(self, target=None, daemon=None, args=(), kwargs=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}

        def start(self):
            if self.target:
                self.target(*self.args, **self.kwargs)

    monkeypatch.setattr(threading, "Thread", ImmediateThread)
    controller.on_escape()
    assert controller.state == "idle"
    assert discarded == [True]
    assert controller.bubble.notices
    assert controller.bubble.notices[-1][0] == "cancelled"


def test_escape_during_processing_sets_cancel_flag():
    controller = _controller()
    controller._set_state("processing")
    controller.on_escape()
    assert controller._cancel_requested is True
    assert controller.state == "processing"


def test_begin_recording_starts_recorder_and_state(monkeypatch):
    controller = _controller()

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            # Do not run context worker (would import AppKit context)
            pass

    monkeypatch.setattr(threading, "Thread", ImmediateThread)
    controller._begin_recording("recording")
    assert controller.recorder.started == 1
    assert controller.state == "recording"
    assert controller._cancel_requested is False


def test_begin_recording_mic_failure_stays_idle(monkeypatch):
    rec = FakeRecorder()

    def boom():
        raise OSError("no mic")

    rec.start = boom
    controller = _controller(recorder=rec)
    controller._begin_recording("recording")
    assert controller.state == "idle"


def test_on_state_change_callback():
    controller = _controller()
    seen = []
    controller.on_state_change = seen.append
    controller._set_state("recording")
    assert seen == ["recording"]


def test_on_state_change_exception_swallowed():
    controller = _controller()
    controller.on_state_change = lambda s: (_ for _ in ()).throw(RuntimeError("ui"))
    gen = controller._set_state("success")
    assert gen == controller._state_gen
    assert controller.state == "success"


def test_hotkey_test_handler_intercepts_press_release():
    controller = _controller()
    events = []
    controller.hotkey_test_handler = events.append
    controller.on_press()
    controller.on_release()
    assert events == ["press", "release"]
    assert controller.state == "idle"


def test_history_context_truncates_workspace_files():
    files = "\n".join(f"f{i}" for i in range(60))
    out = _history_context({"workspace_files": files, "app_name": "X"})
    assert out["workspace_files"].endswith("…")
    assert out["workspace_files"].count("\n") <= 51
    assert out["app_name"] == "X"


def test_finish_success_wrong_state_noop():
    controller = _controller()
    gen = controller._set_state("success")
    controller.state = "processing"  # desync edge
    controller._finish_success(gen)
    assert controller.state == "processing"
