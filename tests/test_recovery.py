"""Durable failed-run persistence and retry foundations.

Headless only: temp history paths, mocked STT/format/insert, no real ~/.golos.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dictate.app import AppController
from dictate.history import (
    STAGE_COMPLETE,
    STAGE_FORMAT,
    STAGE_INSERT,
    STAGE_STT,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    append_failure,
    append_history,
    best_available_text,
    copy_ready,
    group_history_for_home,
    latest_view_for_run,
    load_history,
    load_history_home,
    load_raw_lines,
    normalize_record,
    records_for_run,
    retry_capabilities,
)
from dictate_core.stt import load_wav, write_wav
from tests.conftest import FakeBubble, FakeFormatter, FakeRecorder, FakeSTT
from tests.test_pipeline import SyncAppHelper, _controller


# ---------------------------------------------------------------------------
# Schema / load compatibility
# ---------------------------------------------------------------------------


def test_legacy_success_record_normalizes(tmp_path):
    """Pre-recovery JSONL lines remain readable and success/complete."""
    path = tmp_path / "history.jsonl"
    legacy = {
        "ts": "2024-01-01T00:00:00+00:00",
        "app": "Notes",
        "bundle_id": "com.apple.Notes",
        "raw": "hello",
        "final": "Hello.",
        "context": {},
        "audio": None,
        "fast": False,
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    rows = load_history(str(path))
    assert len(rows) == 1
    rec = rows[0]
    assert rec["status"] == STATUS_SUCCESS
    assert rec["stage"] == STAGE_COMPLETE
    assert rec["raw"] == "hello"
    assert rec["final"] == "Hello."
    assert rec["audio_retained"] is False
    assert rec["schema_version"] == 1


def test_append_history_success_has_v2_fields(tmp_path):
    path = tmp_path / "h.jsonl"
    rec = append_history(
        str(path), "Slack", "com.slack", "raw", "Final.",
        context={"app_name": "Slack"}, audio=None, fast=True,
    )
    assert rec["schema_version"] == 2
    assert rec["status"] == STATUS_SUCCESS
    assert rec["stage"] == STAGE_COMPLETE
    assert rec["run_id"]
    assert rec["attempt"] == 0
    assert rec["audio_retained"] is False
    loaded = json.loads(path.read_text(encoding="utf-8").strip())
    assert loaded["fast"] is True
    assert loaded["final"] == "Final."


def test_mixed_legacy_and_v2_load_order(tmp_path):
    path = tmp_path / "h.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": "t1", "app": "A", "bundle_id": "a",
            "raw": "old", "final": "Old.", "context": {}, "audio": None, "fast": False,
        }) + "\n")
    append_history(str(path), "B", "b", "new", "New.")
    rows = load_history(str(path), newest_first=True)
    assert len(rows) == 2
    assert rows[0]["raw"] == "new"  # newest first
    assert rows[1]["raw"] == "old"
    assert rows[1]["schema_version"] == 1
    assert rows[0]["schema_version"] == 2


def test_copy_ready_prefers_final_then_raw():
    assert copy_ready({"final": "F", "raw": "R"})["source"] == "final"
    assert copy_ready({"final": "F", "raw": "R"})["text"] == "F"
    assert copy_ready({"final": "", "raw": "R"})["source"] == "raw"
    assert copy_ready({"final": "", "raw": ""})["available"] is False
    assert best_available_text({"final": "", "raw": "  x  "}) == "  x  "


def test_retry_capabilities_stt_needs_audio_on_disk(tmp_path):
    wav = tmp_path / "a.wav"
    write_wav(str(wav), np.zeros(1600, dtype=np.float32))
    rec = {
        "status": STATUS_FAILED,
        "stage": STAGE_STT,
        "audio": str(wav),
        "raw": "",
        "final": "",
    }
    caps = retry_capabilities(rec)
    assert caps["can_retry_stt"] is True
    assert caps["has_audio"] is True
    assert caps["audio_retained"] is True

    missing = dict(rec, audio=str(tmp_path / "gone.wav"))
    caps2 = retry_capabilities(missing)
    assert caps2["can_retry_stt"] is False
    assert caps2["audio_retained"] is False
    assert caps2["reason"] and "audio" in caps2["reason"]


def test_audio_retained_false_when_path_missing_on_disk(tmp_path):
    """UI truth: non-empty path alone must not claim retained audio."""
    missing = str(tmp_path / "deleted.wav")
    rec = append_failure(
        str(tmp_path / "h.jsonl"),
        stage=STAGE_STT,
        error="stt down",
        app_name="Slack",
        bundle_id="com.slack",
        raw_text="",
        final_text="",
        audio=missing,
    )
    # Writer may store path for diagnostics, but flag is disk-honest.
    assert rec["audio"] == missing
    assert rec["audio_retained"] is False
    loaded = load_history(str(tmp_path / "h.jsonl"))[0]
    assert loaded["audio"] == missing
    assert loaded["audio_retained"] is False
    norm = normalize_record({"audio": missing, "raw": "x", "final": "X"})
    assert norm["audio_retained"] is False


def test_retry_capabilities_insert_and_format():
    rec = {
        "status": STATUS_FAILED,
        "stage": STAGE_INSERT,
        "raw": "hello",
        "final": "Hello.",
        "audio": None,
    }
    caps = retry_capabilities(rec)
    assert caps["can_retry_insert"] is True
    assert caps["can_retry_format"] is True
    assert caps["can_retry_stt"] is False


# ---------------------------------------------------------------------------
# Pipeline failure writes
# ---------------------------------------------------------------------------


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


def test_stt_exception_writes_failure(tmp_path, inserts):
    class BadSTT:
        def transcribe(self, audio, prompt=""):
            raise RuntimeError("stt down")

    controller = _controller(tmp_path, stt=BadSTT())
    controller._set_state("processing")
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"
    rows = load_history(controller.history_path)
    assert len(rows) == 1
    rec = rows[0]
    assert rec["status"] == STATUS_FAILED
    assert rec["stage"] == STAGE_STT
    assert "stt" in (rec.get("error") or "").lower()
    assert rec["run_id"]
    assert rec["app"] == "Slack"


def test_stt_missing_backend_writes_failure(tmp_path, inserts):
    controller = _controller(tmp_path)
    controller.stt = None
    controller._set_state("processing")
    controller._pipeline()
    rows = load_history(controller.history_path)
    assert len(rows) == 1
    assert rows[0]["stage"] == STAGE_STT
    assert rows[0]["status"] == STATUS_FAILED
    assert "STT" in (rows[0].get("error") or "") or "stt" in (
        rows[0].get("error") or "").lower()


def test_formatter_fallback_inserts_raw_and_records_partial(tmp_path, inserts, monkeypatch):
    """Real Formatter + httpx failure → raw passthrough + partial record."""
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
    rows = load_history(controller.history_path)
    assert len(rows) == 1
    assert rows[0]["status"] == STATUS_PARTIAL
    assert rows[0]["raw"] == "hello world"
    assert rows[0]["final"] == "hello world"
    assert rows[0]["format_fallback"] is True


def test_formatter_raise_uses_raw_and_records_partial(tmp_path, inserts):
    """Raising formatter → raw fallback, insert + partial history."""
    fmt = FakeFormatter(fail=True)
    controller = _controller(tmp_path, formatter=fmt)
    controller._set_state("processing")
    controller._pipeline()
    assert inserts and inserts[0]["text"] == "hello world"
    assert controller.state == "success"
    rows = load_history(controller.history_path)
    assert rows[0]["status"] == STATUS_PARTIAL
    assert rows[0]["format_fallback"] is True
    assert rows[0]["final"] == "hello world"


def test_insertion_failure_writes_failure_with_text(tmp_path, monkeypatch):
    monkeypatch.setattr("dictate.insert.insert_text", lambda *a, **k: False)
    monkeypatch.setattr("PyObjCTools.AppHelper.callAfter", SyncAppHelper.callAfter)
    monkeypatch.setattr("PyObjCTools.AppHelper.callLater", SyncAppHelper.callLater)
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._pipeline()
    assert controller.state == "idle"
    assert controller.last_insertion is None
    rows = load_history(controller.history_path)
    assert len(rows) == 1
    rec = rows[0]
    assert rec["status"] == STATUS_FAILED
    assert rec["stage"] == STAGE_INSERT
    assert rec["raw"] == "hello world"
    assert rec["final"] == "Hello world."
    assert "insert" in (rec.get("error") or "").lower()
    # Copy-ready still works for History UI.
    cr = controller.copy_ready_for_record(rec)
    assert cr["available"] is True
    assert cr["text"] == "Hello world."
    assert cr["source"] == "final"


def test_success_writes_only_after_insert(tmp_path, inserts):
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._pipeline()
    rows = load_raw_lines(controller.history_path)
    assert len(rows) == 1
    assert rows[0]["status"] == STATUS_SUCCESS
    assert rows[0]["stage"] == STAGE_COMPLETE
    assert rows[0]["schema_version"] == 2
    assert rows[0]["run_id"]
    assert controller.last_insertion["run_id"] == rows[0]["run_id"]


def test_audio_not_retained_when_keep_recordings_false(tmp_path, inserts):
    controller = _controller(
        tmp_path,
        cfg_extra={"audio": {"keep_recordings": False}},
    )
    controller._set_state("processing")
    controller._pipeline()
    rec = load_history(controller.history_path)[0]
    assert rec["audio"] is None
    assert rec["audio_retained"] is False


def test_audio_retained_path_when_keep_recordings_true(tmp_path, inserts, monkeypatch):
    saved = str(tmp_path / "rec.wav")
    write_wav(saved, np.ones(8000, dtype=np.float32) * 0.1)
    controller = _controller(
        tmp_path,
        cfg_extra={"audio": {"keep_recordings": True}},
    )
    monkeypatch.setattr(controller, "_save_recording", lambda audio: saved)
    controller._set_state("processing")
    controller._pipeline()
    rec = load_history(controller.history_path)[0]
    assert rec["audio"] == saved
    assert rec["audio_retained"] is True


def test_empty_transcript_writes_retryable_failure_history(tmp_path, inserts):
    controller = _controller(tmp_path, stt=FakeSTT(""))
    controller._set_state("processing")
    controller._pipeline()
    rows = load_history(controller.history_path)
    assert len(rows) == 1
    assert rows[0]["status"] == STATUS_FAILED
    assert rows[0]["stage"] == STAGE_STT
    assert "empty transcript" in rows[0]["error"]


def test_accidental_tap_does_not_write_history(tmp_path, inserts):
    controller = _controller(tmp_path, audio_len=100)
    controller._set_state("processing")
    controller._pipeline()
    assert not Path(controller.history_path).exists()


def test_processing_cancel_writes_cancelled_history(tmp_path, inserts):
    """Esc after STT/format: one schema-v2 cancelled record, no insert."""
    controller = _controller(tmp_path)
    controller._set_state("processing")
    controller._cancel_requested = True
    controller._pipeline()
    assert inserts == []
    assert controller.state == "idle"
    assert controller.last_insertion is None
    rows = load_history(controller.history_path)
    assert len(rows) == 1
    rec = rows[0]
    assert rec["schema_version"] == 2
    assert rec["status"] == STATUS_CANCELLED
    assert rec["stage"] == STAGE_INSERT
    assert rec["raw"] == "hello world"
    assert rec["final"] == "Hello world."
    assert rec["run_id"]
    assert rec["attempt"] == 0
    assert rec["app"] == "Slack"
    assert rec["bundle_id"] == "com.slack"
    assert rec["fast"] is False
    assert rec["format_fallback"] is False
    assert rec.get("error") is None
    cr = controller.copy_ready_for_record(rec)
    assert cr["available"] is True
    assert cr["text"] == "Hello world."
    assert cr["source"] == "final"
    assert cr["status"] == STATUS_CANCELLED


def test_processing_cancel_retains_audio_and_fast_honestly(
        tmp_path, inserts, monkeypatch):
    """Cancelled record keeps audio path + fast flag when those applied."""
    saved = str(tmp_path / "cancel.wav")
    write_wav(saved, np.ones(8000, dtype=np.float32) * 0.1)
    controller = _controller(
        tmp_path,
        cfg_extra={
            "audio": {"keep_recordings": True},
            "formatting": {"fast_mode": True, "fast_mode_max_words": 10},
        },
    )
    monkeypatch.setattr(controller, "_save_recording", lambda audio: saved)
    controller._set_state("processing")
    controller._cancel_requested = True
    controller._pipeline()
    assert inserts == []
    rec = load_history(controller.history_path)[0]
    assert rec["status"] == STATUS_CANCELLED
    assert rec["stage"] == STAGE_INSERT
    assert rec["audio"] == saved
    assert rec["audio_retained"] is True
    assert rec["fast"] is True
    # Fast mode skips formatter; final is literal-corrected raw.
    assert rec["raw"] == "hello world"
    assert rec["final"] == "hello world"


def test_processing_cancel_with_format_fallback(tmp_path, inserts):
    """Cancelled after raising formatter still records format_fallback."""
    controller = _controller(tmp_path, formatter=FakeFormatter(fail=True))
    controller._set_state("processing")
    controller._cancel_requested = True
    controller._pipeline()
    assert inserts == []
    rec = load_history(controller.history_path)[0]
    assert rec["status"] == STATUS_CANCELLED
    assert rec["stage"] == STAGE_INSERT
    assert rec["format_fallback"] is True
    assert rec["raw"] == "hello world"
    assert rec["final"] == "hello world"


def test_recording_escape_does_not_write_history(tmp_path, monkeypatch):
    """Live-recording Esc remains a true abort — no history line."""
    import threading

    controller = _controller(tmp_path)
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
    assert not Path(controller.history_path).exists()


# ---------------------------------------------------------------------------
# Retry foundations (no auto-insert by default)
# ---------------------------------------------------------------------------


def _failed_insert_record(tmp_path, monkeypatch, *, keep_audio=False):
    monkeypatch.setattr("dictate.insert.insert_text", lambda *a, **k: False)
    monkeypatch.setattr("PyObjCTools.AppHelper.callAfter", SyncAppHelper.callAfter)
    monkeypatch.setattr("PyObjCTools.AppHelper.callLater", SyncAppHelper.callLater)
    cfg = {"audio": {"keep_recordings": keep_audio}}
    controller = _controller(tmp_path, cfg_extra=cfg)
    if keep_audio:
        wav = str(tmp_path / "r.wav")
        write_wav(wav, np.ones(8000, dtype=np.float32) * 0.05)
        monkeypatch.setattr(controller, "_save_recording", lambda a: wav)
    controller._set_state("processing")
    controller._pipeline()
    return controller, load_history(controller.history_path)[0]


def test_retry_format_without_insert(tmp_path, monkeypatch):
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    original_lines = load_raw_lines(controller.history_path)
    assert len(original_lines) == 1
    assert original_lines[0]["status"] == STATUS_FAILED

    # Fresh formatter for retry path
    controller.formatter = FakeFormatter(result="Retried final.")
    result = controller.retry_failed_stage(failed, stage=STAGE_FORMAT, insert=False)
    assert result["ok"] is True
    assert result["inserted"] is False
    assert result["text"] == "Retried final."
    assert result["source"] == "final"

    lines = load_raw_lines(controller.history_path)
    assert len(lines) == 2
    # Original failure preserved
    assert lines[0]["status"] == STATUS_FAILED
    assert lines[0]["attempt"] == 0
    # New attempt appended
    assert lines[1]["kind"] == "attempt"
    assert lines[1]["attempt"] == 1
    assert lines[1]["run_id"] == lines[0]["run_id"]
    assert lines[1]["final"] == "Retried final."
    assert lines[1]["status"] == STATUS_SUCCESS


def test_retry_formatter_failure_is_partial_and_copyable(tmp_path, monkeypatch):
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    controller.formatter = FakeFormatter(fail=True)
    result = controller.retry_failed_stage(
        failed, stage=STAGE_FORMAT, insert=False)
    assert result["ok"] is True
    assert result["text"] == failed["raw"]
    assert result["record"]["status"] == STATUS_PARTIAL
    assert result["record"]["format_fallback"] is True


def test_retry_stt_with_audio(tmp_path, monkeypatch):
    controller, failed = _failed_insert_record(
        tmp_path, monkeypatch, keep_audio=True)
    # Force stage to stt-style failure for capability clarity
    failed_stt = dict(failed)
    failed_stt["stage"] = STAGE_STT
    failed_stt["status"] = STATUS_FAILED
    failed_stt["raw"] = ""
    failed_stt["final"] = ""
    append_failure(
        controller.history_path,
        stage=STAGE_STT,
        error="stt: simulated",
        app_name=failed["app"],
        bundle_id=failed["bundle_id"],
        raw_text="",
        final_text="",
        audio=failed.get("audio"),
        run_id=failed["run_id"],
        attempt=0,
    )
    # Use the written STT failure as source
    stt_fail = [r for r in load_history(controller.history_path)
                if r["stage"] == STAGE_STT][0]

    controller.stt = FakeSTT("retry raw")
    controller.formatter = FakeFormatter(result="Retry Final.")
    result = controller.retry_failed_stage(stt_fail, stage=STAGE_STT, insert=False)
    assert result["ok"] is True
    assert result["audio_retained"] is True
    assert result["inserted"] is False
    assert "retry" in (result["text"] or "").lower() or result["text"]
    assert result["record"]["attempt"] >= 1
    # Original STT failure still present
    raw_lines = load_raw_lines(controller.history_path)
    stt_failures = [r for r in raw_lines
                    if r.get("stage") == STAGE_STT and r.get("status") == STATUS_FAILED]
    assert stt_failures


def test_retry_stt_without_audio_reports_honestly(tmp_path, monkeypatch):
    controller, failed = _failed_insert_record(
        tmp_path, monkeypatch, keep_audio=False)
    stt_fail = {
        **failed,
        "stage": STAGE_STT,
        "status": STATUS_FAILED,
        "raw": "",
        "final": "",
        "audio": None,
        "audio_retained": False,
        "error": "stt down",
    }
    result = controller.retry_failed_stage(stt_fail, stage=STAGE_STT, insert=False)
    assert result["ok"] is False
    assert result["audio_retained"] is False
    assert result["inserted"] is False
    assert "audio" in (result["error"] or "").lower()
    # Attempt still recorded
    assert result["record"] is not None
    assert result["record"]["status"] == STATUS_FAILED


def test_retry_does_not_auto_insert(tmp_path, monkeypatch):
    inserts = []

    def capture_insert(text, method="auto", restore_clipboard=False):
        inserts.append(text)
        return True

    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    monkeypatch.setattr("dictate.insert.insert_text", capture_insert)
    controller.formatter = FakeFormatter(result="No auto paste")
    result = controller.retry_failed_stage(failed, stage=STAGE_FORMAT)
    assert result["ok"] is True
    assert result["inserted"] is False
    assert inserts == []  # default insert=False


def test_retry_insert_failure_default_skips_formatter(tmp_path, monkeypatch):
    """Default retry on insert-stage failure: reuse text, no model tokens."""
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    assert failed["stage"] == STAGE_INSERT
    assert failed["final"]
    controller.formatter = FakeFormatter(result="SHOULD_NOT_FORMAT")
    result = controller.retry_failed_stage(failed)  # default stage priority
    assert result["ok"] is True
    assert result["inserted"] is False
    assert result["stage"] == STAGE_INSERT
    assert result["text"] == failed["final"]
    assert controller.formatter.calls == []  # no formatter / no tokens


def test_retry_default_priority_stt_then_insert_then_format(tmp_path, monkeypatch):
    """Default stage selection: STT > INSERT > FORMAT."""
    controller, failed = _failed_insert_record(
        tmp_path, monkeypatch, keep_audio=True)
    # Insert failure with audio+final → default is INSERT (not FORMAT).
    controller.formatter = FakeFormatter(result="NO")
    r_insert = controller.retry_failed_stage(failed)
    assert r_insert["stage"] == STAGE_INSERT
    assert controller.formatter.calls == []

    # STT failure with audio on disk → default is STT.
    stt_fail = {
        **failed,
        "stage": STAGE_STT,
        "status": STATUS_FAILED,
        "raw": "",
        "final": "",
        "error": "stt down",
    }
    controller.stt = FakeSTT("from audio")
    controller.formatter = FakeFormatter(result="Formatted from STT")
    r_stt = controller.retry_failed_stage(stt_fail)
    assert r_stt["ok"] is True
    assert r_stt["stage"] in (STAGE_STT, STAGE_FORMAT)
    assert controller.stt.calls  # STT ran
    assert controller.formatter.calls  # format after STT


def test_retry_explicit_insert_flag(tmp_path, monkeypatch):
    inserts = []

    def capture_insert(text, method="auto", restore_clipboard=False):
        inserts.append(text)
        return True

    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    monkeypatch.setattr("dictate.insert.insert_text", capture_insert)
    result = controller.retry_failed_stage(
        failed, stage=STAGE_INSERT, insert=True)
    assert result["ok"] is True
    assert result["inserted"] is True
    assert inserts == [failed["final"] or failed["raw"]]


def test_controller_copy_ready_and_capabilities(tmp_path, monkeypatch):
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    cr = controller.copy_ready_for_record(failed)
    assert cr["available"]
    caps = controller.retry_capabilities_for_record(failed)
    assert caps["can_retry_insert"] is True
    assert caps["can_retry_stt"] is False


def test_latest_view_for_run_merges_attempts(tmp_path):
    path = str(tmp_path / "h.jsonl")
    first = append_failure(
        path, stage=STAGE_INSERT, error="insertion failed",
        app_name="Slack", bundle_id="com.slack",
        raw_text="raw", final_text="Final.",
        run_id="abc123", attempt=0,
    )
    append_history(
        path, "Slack", "com.slack", "raw", "Retried.",
        run_id="abc123", attempt=1, stage=STAGE_FORMAT,
        status=STATUS_SUCCESS, kind="attempt",
    )
    view = latest_view_for_run(path, "abc123")
    assert view["final"] == "Retried."
    assert view["attempts_count"] == 2
    assert view["run_id"] == "abc123"
    # Original line intact
    assert load_raw_lines(path)[0]["final"] == "Final."
    assert records_for_run(path, "abc123")[0]["error"] == "insertion failed"


# ---------------------------------------------------------------------------
# History home grouping + retry/live coordination
# ---------------------------------------------------------------------------


def test_group_history_for_home_one_row_per_run_id(tmp_path):
    """Home list collapses multi-attempt runs; legacy lines stay single."""
    path = str(tmp_path / "h.jsonl")
    # Legacy success (no run_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": "2024-01-01T00:00:00+00:00",
            "app": "Notes", "bundle_id": "com.apple.Notes",
            "raw": "legacy", "final": "Legacy.", "context": {},
            "audio": None, "fast": False,
        }) + "\n")
    # Run A: failure then success retry
    append_failure(
        path, stage=STAGE_INSERT, error="insert fail",
        app_name="Slack", bundle_id="com.slack",
        raw_text="a raw", final_text="A fail.",
        run_id="run-a", attempt=0,
    )
    append_history(
        path, "Slack", "com.slack", "a raw", "A ok.",
        run_id="run-a", attempt=1, stage=STAGE_COMPLETE,
        status=STATUS_SUCCESS, kind="attempt",
    )
    # Run B: single success
    append_history(
        path, "Mail", "com.apple.mail", "b raw", "B.",
        run_id="run-b", attempt=0,
    )

    rows = load_history(path, newest_first=True)
    # Un-grouped: 4 lines (legacy + A0 + A1 + B)
    assert len(rows) == 4

    home = group_history_for_home(rows)
    # Grouped: legacy + A (merged) + B = 3
    assert len(home) == 3
    by_rid = {r.get("run_id"): r for r in home if r.get("run_id")}
    assert by_rid["run-a"]["final"] == "A ok."
    assert by_rid["run-a"]["attempts_count"] == 2
    assert by_rid["run-b"]["attempts_count"] == 1
    legacy = [r for r in home if not r.get("run_id")]
    assert len(legacy) == 1
    assert legacy[0]["raw"] == "legacy"
    assert legacy[0].get("attempts_count", 1) == 1
    # Newest-first: run-b then run-a then legacy
    assert home[0]["run_id"] == "run-b"
    assert home[1]["run_id"] == "run-a"
    # JSONL not rewritten
    raw_n = len(load_raw_lines(path))
    assert raw_n == 4
    # Convenience loader
    home2 = load_history_home(path, limit=10)
    assert len(home2) == 3
    assert home2[1]["attempts_count"] == 2


def test_retry_busy_while_live_processing_appends_no_attempt(tmp_path, monkeypatch):
    """Retry during live processing → busy; no misleading attempt line."""
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    before = load_raw_lines(controller.history_path)
    controller._set_state("processing")
    result = controller.retry_failed_stage(failed, stage=STAGE_FORMAT)
    assert result["ok"] is False
    assert result.get("busy") is True
    assert result.get("record") is None
    after = load_raw_lines(controller.history_path)
    assert after == before
    assert controller.pipeline_owner() is None


def test_retry_busy_while_live_owns_pipeline(tmp_path, monkeypatch):
    """Retry refused while live owns shared STT/formatter (even if idle)."""
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    assert controller.try_acquire_pipeline(controller.PIPELINE_LIVE)
    before = load_raw_lines(controller.history_path)
    result = controller.retry_failed_stage(failed, stage=STAGE_FORMAT)
    assert result["busy"] is True
    assert result["record"] is None
    assert load_raw_lines(controller.history_path) == before
    controller.release_pipeline(controller.PIPELINE_LIVE)


def test_retry_releases_ownership_after_success(tmp_path, monkeypatch):
    """Successful retry frees the pipeline for the next live/retry."""
    controller, failed = _failed_insert_record(tmp_path, monkeypatch)
    controller.formatter = FakeFormatter(result="Retried.")
    result = controller.retry_failed_stage(failed, stage=STAGE_FORMAT)
    assert result["ok"] is True
    assert result.get("busy") is not True
    assert controller.pipeline_owner() is None
    # Immediate second retry must not get a stuck busy
    result2 = controller.retry_failed_stage(
        result["record"], stage=STAGE_FORMAT)
    assert result2.get("busy") is not True


def test_hotkey_blocked_while_history_retry_owns_pipeline(tmp_path):
    """Hold/toggle during History retry: no recording + idle-safe notice."""
    controller = _controller(tmp_path)
    started = []
    controller._begin_recording = started.append
    assert controller.try_acquire_pipeline(controller.PIPELINE_HISTORY_RETRY)
    controller.on_press()
    assert started == []
    assert controller.state == "idle"
    assert any(
        "History retry is still running" in (n[0] or "")
        for n in controller.bubble.notices
    )
    controller.bubble.notices.clear()
    controller.on_toggle()
    assert started == []
    assert any(
        "History retry is still running" in (n[0] or "")
        for n in controller.bubble.notices
    )
    controller.release_pipeline(controller.PIPELINE_HISTORY_RETRY)
    # After release, normal press starts recording.
    controller.on_press()
    assert started == ["recording"]


def test_normalize_record_null_safe():
    n = normalize_record({"raw": None, "final": None, "app": "X"})
    assert n["raw"] == ""
    assert n["final"] == ""
    assert n["status"] == STATUS_SUCCESS  # legacy default
    assert normalize_record(None) is None
    assert normalize_record("bad") is None


def test_load_wav_roundtrip(tmp_path):
    p = tmp_path / "t.wav"
    audio = np.linspace(-0.5, 0.5, 1600, dtype=np.float32)
    write_wav(str(p), audio)
    loaded = load_wav(str(p))
    assert loaded.shape == audio.shape
    assert abs(float(loaded.mean()) - float(audio.mean())) < 0.01
