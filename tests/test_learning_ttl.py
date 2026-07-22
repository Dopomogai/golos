"""Fake-clock tests: expire stale last_insertion once; no worker thrash."""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import pytest

from dictate import app as app_mod
from dictate import learning as learning_mod
from dictate.editwatcher import EditWatcher
from dictate.learning import (
    capture_edit,
    edit_window_seconds,
    eligible_last_insertion,
    expire_last_insertion,
    insertion_within_edit_window,
    release_last_insertion,
)


class FakeClock:
    """Injectable wall clock for learning TTL (not monotonic)."""

    def __init__(self, t: float = 1_000.0):
        self.t = float(t)

    def time(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock(1_000.0)
    monkeypatch.setattr(learning_mod.time, "time", c.time)
    return c


def _li(clock: FakeClock, **extra) -> dict:
    row = {
        "ts": clock.t,
        "raw": "teh",
        "final": "teh",
        "app_name": "Notes",
        "bundle_id": "com.apple.Notes",
        "pid": 4242,
    }
    row.update(extra)
    return row


def _controller(clock: FakeClock, tmp_path, *, window: float = 600.0, li=None):
    suggestions = tmp_path / "suggestions.jsonl"
    ctrl = SimpleNamespace(
        cfg={
            "learning": {
                "enabled": True,
                "edit_window_seconds": window,
                "live_cues": True,
                "live_cue_seconds": 8,
            },
            "paths": {"suggestions": str(suggestions)},
        },
        last_insertion=li if li is not None else _li(clock),
        _watcher=None,
        bubble=SimpleNamespace(
            cues=[],
            cue=lambda *a, **k: None,
            notice=lambda *a, **k: None,
        ),
        accept_cue=lambda wrong, right: None,
        present_reviewer_suggestions=None,
    )
    return ctrl


def test_edit_window_seconds_default_and_override():
    assert edit_window_seconds({}) == 600.0
    assert edit_window_seconds({"learning": {}}) == 600.0
    assert edit_window_seconds({"learning": {"edit_window_seconds": 120}}) == 120.0


def test_insertion_within_window_boundary(clock):
    cfg = {"learning": {"edit_window_seconds": 600}}
    li = _li(clock)
    assert insertion_within_edit_window(li, cfg, now=clock.t) is True
    assert insertion_within_edit_window(li, cfg, now=clock.t + 600) is True
    assert insertion_within_edit_window(li, cfg, now=clock.t + 600.001) is False
    assert insertion_within_edit_window(None, cfg, now=clock.t) is False


def test_eligible_expires_once_then_silent(clock, tmp_path, caplog):
    ctrl = _controller(clock, tmp_path, window=600.0)
    li = ctrl.last_insertion
    assert eligible_last_insertion(ctrl, now=clock.t) is li

    clock.advance(601.0)
    with caplog.at_level(logging.INFO, logger="dictate.learning"):
        assert eligible_last_insertion(ctrl) is None
        assert ctrl.last_insertion is None
        expiry_logs = [r for r in caplog.records if "expired" in r.getMessage().lower()]
        assert len(expiry_logs) == 1
        # Content-free: no insertion text leaked into the log line.
        msg = expiry_logs[0].getMessage()
        assert "teh" not in msg
        assert "Notes" not in msg

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="dictate.learning"):
        for _ in range(50):
            assert eligible_last_insertion(ctrl) is None
        assert not any("expired" in r.getMessage().lower() for r in caplog.records)
        assert not any("too old" in r.getMessage().lower() for r in caplog.records)


def test_expire_does_not_clear_newer_insertion(clock, tmp_path):
    ctrl = _controller(clock, tmp_path)
    old = ctrl.last_insertion
    newer = _li(clock, final="newer paste", raw="newer paste")
    ctrl.last_insertion = newer

    assert expire_last_insertion(ctrl, old) is False
    assert ctrl.last_insertion is newer
    assert release_last_insertion(ctrl, old) is False
    assert ctrl.last_insertion is newer

    assert release_last_insertion(ctrl, newer) is True
    assert ctrl.last_insertion is None


def test_capture_edit_expected_identity_and_no_clear_of_newer(
    clock, tmp_path, monkeypatch,
):
    ctrl = _controller(clock, tmp_path)
    old = ctrl.last_insertion
    newer = _li(clock, final="brand new", raw="brand new")
    ctrl.last_insertion = newer

    # Worker retained older dict; must not touch the newer insertion.
    assert capture_edit(ctrl, text="brand new fixed", expected=old) == []
    assert ctrl.last_insertion is newer

    # Age expiry on the current insertion clears once, identity-safe.
    clock.advance(700)
    assert capture_edit(ctrl, text="anything") == []
    assert ctrl.last_insertion is None


def test_capture_edit_releases_only_matching_insertion(
    clock, tmp_path, monkeypatch,
):
    ctrl = _controller(clock, tmp_path, li=_li(clock, final="teh", raw="teh"))
    li = ctrl.last_insertion

    monkeypatch.setattr(
        learning_mod, "propose_pairs",
        lambda li_, text, cfg, **k: ([("teh", "the")], {
            "provenance": "deterministic", "from_reviewer": False,
        }),
    )
    pairs = capture_edit(ctrl, text="the")
    assert pairs == [("teh", "the")]
    assert ctrl.last_insertion is None
    # Re-run with the same retained dict is a no-op for controller state.
    ctrl.last_insertion = _li(clock, final="other")
    assert release_last_insertion(ctrl, li) is False
    assert ctrl.last_insertion is not None


def test_on_app_switch_stale_starts_zero_workers_over_1000_switches(
    clock, tmp_path, monkeypatch,
):
    """Long-session thrash regression: 1000 switches after TTL → 0 threads."""
    from dictate.app import AppController
    from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT

    starts: list = []

    class TrackingThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            starts.append(target)

        def start(self):
            return None

    monkeypatch.setattr(app_mod.threading, "Thread", TrackingThread)

    ctrl = AppController(
        {
            "paths": {},
            "context": {"enabled": False},
            "formatting": {},
            "insert": {},
            "audio": {"keep_recordings": False},
            "learning": {"enabled": True, "edit_window_seconds": 600},
        },
        FakeRecorder(),
        FakeSTT(),
        FakeFormatter(),
        FakeBubble(),
        [],
        [],
        "",
    )
    ctrl.last_insertion = _li(clock)
    clock.advance(601.0)

    for i in range(1000):
        ctrl.on_app_switch(f"com.other.app.{i % 17}")

    assert starts == []
    assert ctrl.last_insertion is None


def test_on_app_switch_fresh_still_starts_worker(clock, monkeypatch):
    from dictate.app import AppController
    from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT

    starts: list = []

    class TrackingThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            starts.append((target, args))

        def start(self):
            return None

    monkeypatch.setattr(app_mod.threading, "Thread", TrackingThread)

    ctrl = AppController(
        {
            "paths": {},
            "context": {"enabled": False},
            "formatting": {},
            "insert": {},
            "audio": {"keep_recordings": False},
            "learning": {"enabled": True, "edit_window_seconds": 600},
        },
        FakeRecorder(),
        FakeSTT(),
        FakeFormatter(),
        FakeBubble(),
        [],
        [],
        "",
    )
    li = _li(clock)
    ctrl.last_insertion = li
    ctrl.on_app_switch("com.other.app")
    assert len(starts) == 1
    assert starts[0][0] == ctrl._capture_on_switch
    assert starts[0][1] == (li,)
    assert ctrl.last_insertion is li


def test_editwatcher_start_and_poll_expire(clock, tmp_path, monkeypatch):
    ctrl = _controller(clock, tmp_path, window=10.0)
    watcher = EditWatcher(ctrl)
    ctrl._watcher = watcher

    scheduled: list = []

    class FakeAppHelper:
        @staticmethod
        def callLater(delay, fn, *args):
            scheduled.append((delay, fn, args))

        @staticmethod
        def callAfter(fn, *args):
            fn(*args)

    import sys
    monkeypatch.setitem(
        sys.modules,
        "PyObjCTools",
        SimpleNamespace(AppHelper=FakeAppHelper),
    )
    monkeypatch.setitem(
        sys.modules,
        "PyObjCTools.AppHelper",
        FakeAppHelper,
    )

    watcher.start()
    assert watcher._insertion is ctrl.last_insertion
    assert scheduled  # armed a poll

    gen = watcher._gen
    clock.advance(11.0)
    # Drive one poll tick with the armed generation.
    watcher._poll(gen)
    assert ctrl.last_insertion is None
    assert watcher._insertion is None
    # Superseded gen: further polls are no-ops (no new worker).
    workers_before = threading.active_count()
    watcher._poll(gen)
    assert threading.active_count() == workers_before


def test_timed_capture_skips_when_expired(clock, monkeypatch):
    from dictate.app import AppController
    from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT

    async_calls: list = []

    def fake_async(ctrl, on_done):
        async_calls.append(1)

    monkeypatch.setattr(learning_mod, "capture_edit_async", fake_async)

    ctrl = AppController(
        {
            "paths": {},
            "context": {"enabled": False},
            "formatting": {},
            "insert": {},
            "audio": {"keep_recordings": False},
            "learning": {"enabled": True, "edit_window_seconds": 600},
        },
        FakeRecorder(),
        FakeSTT(),
        FakeFormatter(),
        FakeBubble(),
        [],
        [],
        "",
    )
    ctrl.last_insertion = _li(clock)
    clock.advance(601.0)
    ctrl._capture_pending_edit()
    assert async_calls == []
    assert ctrl.last_insertion is None
