"""Pipeline contracts: all network/audio/AX/insertion mocked. No live APIs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dictate.app import AppController
from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT


class SyncAppHelper:
    """callAfter runs immediately; callLater is deferred (recorded only).

    The real success path schedules `_finish_success` via callLater(1.2, …).
    Running that synchronously would always leave state=idle and hide the
    success handoff under test.
    """

    later_calls: list = []

    @staticmethod
    def callAfter(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    @staticmethod
    def callLater(delay, fn, *args, **kwargs):
        SyncAppHelper.later_calls.append((delay, fn, args, kwargs))


def _controller(tmp_path, *, stt=None, formatter=None, audio_len=8000, cfg_extra=None):
    audio = np.ones(audio_len, dtype=np.float32) * 0.1
    rec = FakeRecorder(audio=audio)
    stt = stt if stt is not None else FakeSTT("hello world")
    fmt = formatter if formatter is not None else FakeFormatter(result="Hello world.")
    hist = str(tmp_path / "history.jsonl")
    cfg = {
        "paths": {},
        "context": {"enabled": False},
        "formatting": {"fast_mode": False},
        "insert": {"method": "auto", "restore_clipboard": False},
        "audio": {"keep_recordings": False},
    }
    if cfg_extra:
        for k, v in cfg_extra.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    bubble = FakeBubble()
    c = AppController(cfg, rec, stt, fmt, bubble, ["golos"], [("teh", "the")], hist)
    c._fmt_context = {"app_name": "Slack", "bundle_id": "com.slack"}
    c._context = {"app_name": "Slack", "bundle_id": "com.slack", "pid": 1}
    c._fmt_context_ready.set()
    return c


@pytest.fixture
def inserts(monkeypatch):
    captured = []
    SyncAppHelper.later_calls = []

    def fake_insert(text, method="auto", restore_clipboard=False):
        captured.append({"text": text, "method": method, "ok": True})
        return True

    monkeypatch.setattr("dictate.insert.insert_text", fake_insert)
    monkeypatch.setattr("PyObjCTools.AppHelper.callAfter", SyncAppHelper.callAfter)
    monkeypatch.setattr("PyObjCTools.AppHelper.callLater", SyncAppHelper.callLater)
    return captured


def test_pipeline_success(tmp_path, inserts):
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts and inserts[0]["text"] == "Hello world."
    assert controller.state == "success"
    assert controller.last_insertion is not None
    assert controller.last_insertion["final"] == "Hello world."
    # keep_recordings=false → no path; key still present for reviewer contract
    assert controller.last_insertion.get("audio_path") is None
    hist = Path(controller.history_path)
    assert hist.exists()
    assert "hello world" in hist.read_text(encoding="utf-8")


def test_pipeline_last_insertion_propagates_audio_path(tmp_path, inserts, monkeypatch):
    """Retained WAV path is stored on last_insertion (never raw bytes)."""
    saved = str(tmp_path / "rec.wav")

    controller = _controller(
        tmp_path,
        cfg_extra={"audio": {"keep_recordings": True}},
    )
    monkeypatch.setattr(controller, "_save_recording", lambda audio: saved)
    controller._set_state("processing")
    controller._pipeline()
    assert controller.last_insertion is not None
    assert controller.last_insertion["audio_path"] == saved
    assert controller.last_insertion["raw"] == "hello world"
    assert not isinstance(controller.last_insertion["audio_path"], (bytes, bytearray))


def test_pipeline_formatter_passthrough_disabled(tmp_path, inserts):
    fmt = FakeFormatter(enabled=False, result=None)
    controller = _controller(tmp_path, formatter=fmt)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts[0]["text"] == "hello world"


def test_pipeline_partial_success_truthful_label(tmp_path, inserts):
    """Format fallback + insert → STATUS_PARTIAL and '✓ inserted raw' label."""
    fmt = FakeFormatter(fail=True)
    controller = _controller(tmp_path, formatter=fmt)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts and inserts[0]["text"] == "hello world"
    assert controller.state == "success"
    assert controller.bubble._success_label == "✓ inserted raw"
    assert "✓ inserted raw" in controller.bubble.success_labels
    # Success → idle timer still scheduled (lifecycle intact).
    assert any(
        fn.__name__ == "_finish_success" or getattr(fn, "__name__", "") == "_finish_success"
        for _d, fn, _a, _k in SyncAppHelper.later_calls
    )
    hist = Path(controller.history_path).read_text(encoding="utf-8")
    assert '"status": "partial"' in hist or '"status":"partial"' in hist
    assert "format_fallback" in hist


def test_pipeline_full_success_default_inserted_label(tmp_path, inserts):
    """Normal success keeps default green label (not 'inserted raw')."""
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._pipeline()
    assert controller.state == "success"
    assert controller.bubble._success_label == "✓ inserted"
    assert controller.bubble._success_label != "✓ inserted raw"


def test_pipeline_formatter_failure_returns_raw(tmp_path, inserts, monkeypatch):
    """Real Formatter + mocked httpx failure → raw passthrough."""
    from dictate_core.formatter import Formatter

    fmt = Formatter(
        {
            "formatting": {"enabled": True, "provider": "openrouter"},
            "openrouter": {"api_key": "sk"},
        },
        [],
        [],
    )

    class BoomClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise RuntimeError("down")

    import httpx
    monkeypatch.setattr(httpx, "Client", BoomClient)
    controller = _controller(tmp_path, formatter=fmt)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts[0]["text"] == "hello world"
    assert controller.state == "success"


def test_pipeline_cancellation_discards_insert(tmp_path, inserts):
    """Esc after STT/format: no insert, idle; recovery history is in test_recovery."""
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._cancel_requested = True
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"
    assert controller._cancel_requested is False
    assert controller.last_insertion is None


def test_pipeline_insertion_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("dictate.insert.insert_text", lambda *a, **k: False)
    monkeypatch.setattr("PyObjCTools.AppHelper.callAfter", SyncAppHelper.callAfter)
    monkeypatch.setattr("PyObjCTools.AppHelper.callLater", SyncAppHelper.callLater)
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._pipeline()
    assert controller.state == "idle"
    assert controller.last_insertion is None
    assert controller.bubble.notices
    assert "couldn't insert" in controller.bubble.notices[-1][0]
    assert controller.bubble.notices[-1][1] == "warn"


def test_pipeline_history_failure_still_inserts(tmp_path, inserts, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    # Success history is written after insert confirms (main-thread path).
    monkeypatch.setattr("dictate.history.append_history", boom)
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts
    assert controller.state == "success"


def test_pipeline_accidental_tap_short_audio(tmp_path, inserts):
    controller = _controller(tmp_path, audio_len=100)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"


def test_pipeline_empty_transcript(tmp_path, inserts):
    controller = _controller(tmp_path, stt=FakeSTT(""))
    controller._set_state("processing")
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"
    assert controller.bubble.notices
    assert "couldn't hear that" in controller.bubble.notices[-1][0]
    assert controller.bubble.notices[-1][1] == "warn"


def test_pipeline_no_stt_backend(tmp_path, inserts):
    controller = _controller(tmp_path)
    controller.stt = None
    controller._set_state("processing")
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"
    assert controller.bubble.notices
    assert "OpenRouter" in controller.bubble.notices[-1][0]
    assert controller.bubble.notices[-1][1] == "warn"


def test_pipeline_failure_notice_after_idle_not_dropped(tmp_path, inserts):
    """Recovery notices must land after idle (Bubble idle-only guard)."""
    controller = _controller(tmp_path, stt=FakeSTT(""))
    controller._set_state("processing")
    controller._pipeline()
    # Idle must appear before/with the visible notice path.
    assert "idle" in controller.bubble.states
    idle_idx = controller.bubble.states.index("idle")
    # Notice recorded (FakeBubble drops notices while non-idle).
    assert len(controller.bubble.notices) == 1
    assert controller.bubble.notices[0][1] == "warn"
    # Final controller state is idle, not stuck processing.
    assert controller.state == "idle"
    assert idle_idx >= 0


def test_pipeline_accidental_tap_no_recovery_notice(tmp_path, inserts):
    """Short accidental tap stays silent — no History warn."""
    controller = _controller(tmp_path, audio_len=100)
    controller._set_state("processing")
    controller._pipeline()
    assert controller.state == "idle"
    assert controller.bubble.notices == []


def test_pipeline_fast_mode_skips_formatter(tmp_path, inserts):
    fmt = FakeFormatter(result="SHOULD_NOT_USE")
    controller = _controller(
        tmp_path,
        formatter=fmt,
        stt=FakeSTT("teh quick"),
        cfg_extra={"formatting": {"fast_mode": True, "fast_mode_max_words": 10}},
    )
    controller.corrections = [("teh", "the")]
    controller._set_state("processing")
    controller._pipeline()
    assert fmt.calls == []
    assert inserts[0]["text"] == "the quick"
    text = Path(controller.history_path).read_text(encoding="utf-8")
    assert '"fast": true' in text


def test_pipeline_stt_exception_returns_idle(tmp_path, inserts):
    class BadSTT:
        def transcribe(self, audio, prompt=""):
            raise RuntimeError("stt down")

    controller = _controller(tmp_path, stt=BadSTT())
    controller._set_state("processing")
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"
    assert controller.bubble.notices
    msg = controller.bubble.notices[-1][0].lower()
    assert "speech recognition failed" in msg
    assert "history" in msg
    assert controller.bubble.notices[-1][1] == "warn"
