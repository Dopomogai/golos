"""Append-only dictation history + durable recovery log (JSONL under ~/.golos/).

Successful pipelines write one line with raw + final transcript, app identity,
a truncated formatter context, optional local wav path, and a `fast` flag.

Failed pipelines also write a durable record so STT / format / insert failures
do not lose the dictation. Retries append new attempt lines linked by
`run_id` — originals are never rewritten or deleted.

Schema v2 adds recovery fields while remaining backward compatible with
legacy success lines (no `schema_version` / `status` / `run_id`). Settings
and loaders normalize via `normalize_record` / `load_history`.

Thread-safe: a process-wide lock serializes concurrent writers.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()

SCHEMA_VERSION = 2

# Pipeline stages (where a run may stop or complete).
STAGE_STT = "stt"
STAGE_FORMAT = "format"
STAGE_INSERT = "insert"
STAGE_COMPLETE = "complete"

# Terminal / intermediate statuses for a single immutable attempt line.
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_PARTIAL = "partial"  # format fell back to raw; insert may still succeed

STAGES = (STAGE_STT, STAGE_FORMAT, STAGE_INSERT, STAGE_COMPLETE)
STATUSES = (STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELLED, STATUS_PARTIAL)


def new_run_id() -> str:
    """Stable id for one dictation run (original + its retry attempts)."""
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate_context(context: dict | None) -> dict:
    """Context dict for history.jsonl: workspace_files truncated to 50 lines."""
    if not context:
        return {}
    ctx = dict(context)
    files = ctx.get("workspace_files")
    if isinstance(files, str) and files.count("\n") > 50:
        ctx["workspace_files"] = "\n".join(files.splitlines()[:50]) + "\n…"
    return ctx


def _audio_retained(audio: str | None) -> bool:
    """Honest retention flag: True only when the WAV path exists on disk.

    A non-empty path alone is not enough (file may have been deleted). Callers
    may still store the path for diagnostics; never claim retained audio when
    the file is missing.
    """
    if not audio:
        return False
    try:
        return Path(str(audio)).is_file()
    except (TypeError, OSError, ValueError):
        return False


def build_record(
    *,
    app_name: str = "",
    bundle_id: str = "",
    raw_text: str | None = None,
    final_text: str | None = None,
    context: dict | None = None,
    audio: str | None = None,
    fast: bool = False,
    run_id: str | None = None,
    attempt: int = 0,
    stage: str = STAGE_COMPLETE,
    status: str = STATUS_SUCCESS,
    error: str | None = None,
    format_fallback: bool = False,
    kind: str = "run",
) -> dict[str, Any]:
    """Build a schema-v2 history / recovery record (not yet written)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,  # "run" (first write) or "attempt" (retry)
        "run_id": run_id or new_run_id(),
        "attempt": int(attempt),
        "ts": _now_iso(),
        "app": app_name or "",
        "bundle_id": bundle_id or "",
        "raw": raw_text if raw_text is not None else None,
        "final": final_text if final_text is not None else None,
        "context": _truncate_context(context),
        "audio": audio,
        "audio_retained": _audio_retained(audio),
        "fast": bool(fast),
        "stage": stage,
        "status": status,
        "error": error,
        "format_fallback": bool(format_fallback),
    }


def append_record(path: str, record: dict) -> dict:
    """Append one JSONL line. Returns the record written (may fill ts/run_id)."""
    out = dict(record)
    out.setdefault("schema_version", SCHEMA_VERSION)
    out.setdefault("ts", _now_iso())
    out.setdefault("run_id", new_run_id())
    out.setdefault("attempt", 0)
    out.setdefault("kind", "run" if out["attempt"] == 0 else "attempt")
    out.setdefault("context", {})
    out.setdefault("audio_retained", _audio_retained(out.get("audio")))
    line = json.dumps(out, ensure_ascii=False)
    with _lock:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return out


def append_history(path: str, app_name: str, bundle_id: str,
                   raw_text: str, final_text: str,
                   context: dict | None = None,
                   audio: str | None = None,
                   fast: bool = False,
                   run_id: str | None = None,
                   attempt: int = 0,
                   stage: str = STAGE_COMPLETE,
                   status: str = STATUS_SUCCESS,
                   error: str | None = None,
                   format_fallback: bool = False,
                   kind: str | None = None) -> dict:
    """Append one history record.

    Success path (default): stage=complete, status=success — same fields as
    the legacy writer, plus schema v2 recovery metadata.

    `audio` is a local filesystem path (or None), never wav bytes.
    """
    rec = build_record(
        app_name=app_name,
        bundle_id=bundle_id,
        raw_text=raw_text,
        final_text=final_text,
        context=context,
        audio=audio,
        fast=fast,
        run_id=run_id,
        attempt=attempt,
        stage=stage,
        status=status,
        error=error,
        format_fallback=format_fallback,
        kind=kind or ("run" if attempt == 0 else "attempt"),
    )
    return append_record(path, rec)


def append_failure(
    path: str,
    *,
    stage: str,
    error: str,
    app_name: str = "",
    bundle_id: str = "",
    raw_text: str | None = None,
    final_text: str | None = None,
    context: dict | None = None,
    audio: str | None = None,
    fast: bool = False,
    run_id: str | None = None,
    attempt: int = 0,
    format_fallback: bool = False,
    kind: str | None = None,
) -> dict:
    """Append a durable failed-run record for the given pipeline stage."""
    return append_history(
        path,
        app_name,
        bundle_id,
        raw_text if raw_text is not None else "",
        final_text if final_text is not None else "",
        context=context,
        audio=audio,
        fast=fast,
        run_id=run_id,
        attempt=attempt,
        stage=stage,
        status=STATUS_FAILED,
        error=str(error) if error is not None else "unknown error",
        format_fallback=format_fallback,
        kind=kind,
    )


def normalize_record(raw: dict | None) -> dict | None:
    """Upgrade a legacy or partial record to a unified view for UI / retry.

    Legacy success lines (no schema_version) become status=success,
    stage=complete. Missing fields get safe defaults. Does not mutate `raw`.
    """
    if not isinstance(raw, dict):
        return None
    rec = dict(raw)
    version = rec.get("schema_version")
    if version is None:
        # Legacy success-only lines from pre-recovery history.
        rec["schema_version"] = 1
        rec.setdefault("status", STATUS_SUCCESS)
        rec.setdefault("stage", STAGE_COMPLETE)
        rec.setdefault("error", None)
        rec.setdefault("run_id", None)
        rec.setdefault("attempt", 0)
        rec.setdefault("kind", "run")
        rec.setdefault("format_fallback", False)
    else:
        rec.setdefault("status", STATUS_SUCCESS)
        rec.setdefault("stage", STAGE_COMPLETE)
        rec.setdefault("error", None)
        rec.setdefault("run_id", rec.get("run_id"))
        rec.setdefault("attempt", 0)
        rec.setdefault("kind", "run")
        rec.setdefault("format_fallback", False)
    rec.setdefault("app", "")
    rec.setdefault("bundle_id", "")
    rec.setdefault("raw", rec.get("raw") if rec.get("raw") is not None else "")
    rec.setdefault("final", rec.get("final") if rec.get("final") is not None else "")
    rec.setdefault("context", {})
    rec.setdefault("audio", None)
    rec.setdefault("fast", False)
    rec["audio_retained"] = _audio_retained(rec.get("audio"))
    # Coerce null-ish text to empty string for consumers that expect str.
    if rec["raw"] is None:
        rec["raw"] = ""
    if rec["final"] is None:
        rec["final"] = ""
    return rec


def load_history(path: str, *, limit: int = 500, newest_first: bool = True) -> list[dict]:
    """Load up to `limit` history lines, normalized. Missing file → []."""
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        norm = normalize_record(raw)
        if norm is not None:
            records.append(norm)
    if newest_first:
        records = list(reversed(records[-limit:])) if limit else list(reversed(records))
    elif limit:
        records = records[-limit:]
    return records


def load_raw_lines(path: str) -> list[dict]:
    """Load every parseable JSON object in order (no reverse, no normalize)."""
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def best_available_text(record: dict | None) -> str | None:
    """Best copyable text: prefer final, else raw. None if neither usable."""
    if not record:
        return None
    final = (record.get("final") or "").strip()
    if final:
        return record.get("final") or final
    raw = (record.get("raw") or "").strip()
    if raw:
        return record.get("raw") or raw
    return None


def copy_ready(record: dict | None) -> dict[str, Any]:
    """Structured copy payload for History UI.

    Returns:
      text: str | None — best available text
      source: "final" | "raw" | None
      available: bool
      status / stage / run_id for display
    """
    norm = normalize_record(record) if record else None
    if not norm:
        return {
            "text": None,
            "source": None,
            "available": False,
            "status": None,
            "stage": None,
            "run_id": None,
            "error": None,
        }
    final = (norm.get("final") or "").strip()
    raw = (norm.get("raw") or "").strip()
    if final:
        source, text = "final", norm.get("final") or final
    elif raw:
        source, text = "raw", norm.get("raw") or raw
    else:
        source, text = None, None
    return {
        "text": text,
        "source": source,
        "available": text is not None and bool(str(text).strip()),
        "status": norm.get("status"),
        "stage": norm.get("stage"),
        "run_id": norm.get("run_id"),
        "error": norm.get("error"),
        "audio_retained": norm.get("audio_retained", False),
        "app": norm.get("app", ""),
        "bundle_id": norm.get("bundle_id", ""),
    }


def retry_capabilities(record: dict | None) -> dict[str, Any]:
    """What a later Settings UI may offer for this record.

    Insertion is never auto-enabled here — re-insert is always an explicit
    UI action (see AppController.retry_failed_stage contract).
    """
    norm = normalize_record(record) if record else None
    if not norm:
        return {
            "can_retry_stt": False,
            "can_retry_format": False,
            "can_retry_insert": False,
            "has_audio": False,
            "audio_retained": False,
            "has_raw": False,
            "has_final": False,
            "is_failed": False,
            "reason": "no record",
        }
    has_audio = bool(norm.get("audio")) and Path(str(norm["audio"])).is_file()
    has_raw = bool((norm.get("raw") or "").strip())
    has_final = bool((norm.get("final") or "").strip())
    status = norm.get("status")
    stage = norm.get("stage")
    is_failed = status == STATUS_FAILED
    # STT retry needs retained WAV on disk (privacy: never invent audio).
    can_retry_stt = is_failed and stage == STAGE_STT and has_audio
    # Format retry needs raw text (audio optional for send_audio path).
    can_retry_format = has_raw and (
        is_failed and stage in (STAGE_FORMAT, STAGE_INSERT, STAGE_STT)
        or status in (STATUS_SUCCESS, STATUS_PARTIAL)
    )
    # Insert "retry" is copy-ready only at controller level — capability is
    # "has text to insert/copy", not permission to auto-paste.
    can_retry_insert = is_failed and stage == STAGE_INSERT and (has_final or has_raw)
    reason = None
    if is_failed and stage == STAGE_STT and not has_audio:
        reason = "audio not retained; cannot re-run STT"
    elif not is_failed and not has_raw and not has_final:
        reason = "no text available"
    return {
        "can_retry_stt": bool(can_retry_stt),
        "can_retry_format": bool(can_retry_format and has_raw),
        "can_retry_insert": bool(can_retry_insert),
        "has_audio": has_audio,
        "audio_retained": bool(norm.get("audio_retained")),
        "has_raw": has_raw,
        "has_final": has_final,
        "is_failed": is_failed,
        "stage": stage,
        "status": status,
        "run_id": norm.get("run_id"),
        "reason": reason,
    }


def next_attempt_number(path: str, run_id: str | None) -> int:
    """Highest attempt for run_id in the log + 1. Missing → 1 (first retry)."""
    if not run_id:
        return 1
    n = 0
    found = False
    for rec in load_raw_lines(path):
        if rec.get("run_id") == run_id:
            found = True
            try:
                n = max(n, int(rec.get("attempt") or 0))
            except (TypeError, ValueError):
                pass
    return (n + 1) if found else 1


def records_for_run(path: str, run_id: str) -> list[dict]:
    """All normalized lines for a run_id, chronological."""
    out = []
    for rec in load_raw_lines(path):
        if rec.get("run_id") == run_id:
            norm = normalize_record(rec)
            if norm:
                out.append(norm)
    return out


def merge_attempt_views(attempts: list[dict]) -> dict | None:
    """Merge chronological attempts into one derived latest view (pure).

    Original attempt lines stay on disk; this only builds a snapshot. Newest
    non-empty text / status / stage win. Sets ``attempts_count``.
    """
    if not attempts:
        return None
    view = dict(attempts[0])
    for a in attempts[1:]:
        for key in ("raw", "final", "audio", "status", "stage", "error",
                    "fast", "format_fallback", "context", "app", "bundle_id",
                    "attempt", "kind", "ts"):
            val = a.get(key)
            if key in ("raw", "final"):
                if val is not None and str(val).strip():
                    view[key] = val
            elif val is not None:
                view[key] = val
        view["audio_retained"] = _audio_retained(view.get("audio"))
    view["audio_retained"] = _audio_retained(view.get("audio"))
    view["attempts_count"] = len(attempts)
    return view


def latest_view_for_run(path: str, run_id: str) -> dict | None:
    """Merge attempts for a run into a single latest view (for UI).

    Original failure lines stay on disk; this only builds a derived snapshot
    from the newest attempt's fields. Does not rewrite or delete JSONL.
    """
    attempts = records_for_run(path, run_id)
    return merge_attempt_views(attempts)


def group_history_for_home(
    records: list[dict],
    *,
    limit: int | None = None,
) -> list[dict]:
    """Home list: one latest derived row per ``run_id``; legacy rows stay single.

    ``records`` must be normalized and newest-first (as from ``load_history``).
    Lines that share a non-empty ``run_id`` collapse via
    :func:`merge_attempt_views` (same semantics as ``latest_view_for_run``).
    Pre-recovery legacy lines (no ``run_id``) appear individually with
    ``attempts_count=1``. JSONL is never rewritten or deleted.
    """
    # Collect chronological attempt lists while preserving first (newest)
    # display index for ordering.
    by_run: dict[str, list[dict]] = {}
    first_index: dict[str, int] = {}
    singles: list[tuple[int, dict]] = []

    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        rid = rec.get("run_id") or None
        if not rid:
            row = dict(rec)
            row.setdefault("attempts_count", 1)
            singles.append((i, row))
            continue
        if rid not in by_run:
            first_index[rid] = i
            by_run[rid] = []
        by_run[rid].append(rec)

    items: list[tuple[int, dict]] = list(singles)
    for rid, newest_first in by_run.items():
        # merge_attempt_views expects chronological (oldest first).
        chronological = list(reversed(newest_first))
        view = merge_attempt_views(chronological)
        if view is not None:
            items.append((first_index[rid], view))

    items.sort(key=lambda pair: pair[0])
    out = [view for _, view in items]
    if limit is not None and limit >= 0:
        out = out[:limit]
    return out


def load_history_home(path: str, *, limit: int = 500) -> list[dict]:
    """Load history for Settings home: grouped by run_id, newest first.

    Convenience over ``load_history`` + ``group_history_for_home``. Does not
    mutate the on-disk JSONL log.
    """
    # Load a generous window so multi-attempt runs still group after limit.
    raw_limit = max(limit * 4, limit, 500) if limit else 0
    records = load_history(path, limit=raw_limit or 500, newest_first=True)
    return group_history_for_home(records, limit=limit if limit else None)
