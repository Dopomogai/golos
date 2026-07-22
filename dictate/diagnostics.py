"""Local, privacy-conscious diagnostics for packaged and source builds.

Runtime logs rotate under ``~/.golos/logs/``. Export is always an explicit
user action: no telemetry, audio, transcripts, focused/visible context, API
keys, or custom prompts are uploaded or placed in the support bundle.
"""

from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
import json
import logging
import os
import platform
import re
import sys
import threading
import zipfile

from .config import DATA_DIR

LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 5
LOG_NAME = "golos.log"

_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s]: %(message)s"
_SECRET_RE = re.compile(
    r"(?i)(?:sk-or-v1-|sk-)[A-Za-z0-9_.-]{12,}|"
    r"(?:api[_ -]?key|authorization)(?:[\"'=:\s]+)[^\s,;\"]+"
)
_SENSITIVE_LINE_RE = re.compile(
    r"(?i)(Raw transcript:|Formatted:|Recorded \d+ suggestion\(s\):|"
    r"Added correction:|Added dictionary term:|Cue accepted:|Edit cue:|"
    r"Flushing pending edit cue on)"
)


def configure_logging(data_dir: Path = DATA_DIR, *, stream: bool = True) -> Path:
    """Install INFO stderr + rotating-file handlers and crash hooks.

    ``force=True`` makes Finder-launched py2app builds deterministic instead
    of relying on an unavailable console. Calling this twice is safe.
    """
    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(log_dir, 0o700)
    except OSError:
        pass
    log_path = log_dir / LOG_NAME
    file_handler = RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    handlers: list[logging.Handler] = [file_handler]
    if stream:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, format=_FORMAT, handlers=handlers, force=True,
    )
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        pass
    logging.captureWarnings(True)
    _install_exception_hooks()
    logging.getLogger(__name__).info(
        "Diagnostics logging ready: file=%s max_bytes=%d backups=%d",
        log_path, LOG_MAX_BYTES, LOG_BACKUPS,
    )
    return log_path


def _install_exception_hooks() -> None:
    if getattr(_install_exception_hooks, "_installed", False):
        return
    _install_exception_hooks._installed = True
    previous_sys = sys.excepthook

    def sys_hook(exc_type, exc, tb):
        logging.getLogger("dictate.crash").critical(
            "Uncaught main-thread exception", exc_info=(exc_type, exc, tb))
        previous_sys(exc_type, exc, tb)

    sys.excepthook = sys_hook
    previous_thread = getattr(threading, "excepthook", None)
    if previous_thread is not None:
        def thread_hook(args):
            logging.getLogger("dictate.crash").critical(
                "Uncaught worker exception thread=%s", args.thread.name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            previous_thread(args)
        threading.excepthook = thread_hook


def _safe_config(cfg: dict) -> dict:
    """Small allow-list; deliberately excludes credentials, paths, and prompts."""
    allowed = {
        "app": ("onboarded",),
        "stt": ("backend", "model", "mlx_model", "languages"),
        "formatting": (
            "enabled", "model", "fast_mode", "fast_mode_max_words",
            "send_audio", "answer_questions",
        ),
        "bubble": ("style", "sensitivity", "show_text"),
        "hotkey": ("hold_key", "double_tap"),
        "insert": ("method", "restore_clipboard"),
        "audio": ("keep_recordings",),
        "context": (
            "enabled", "app_window", "text_before_cursor",
            "focused_field_text", "visible_text", "browser", "vscode",
            "finder",
        ),
        "learning": (
            "enabled", "live_cues", "reviewer_enabled", "reviewer_model",
            "reviewer_send_audio", "reviewer_min_confidence",
        ),
    }
    out = {}
    for section, keys in allowed.items():
        src = cfg.get(section)
        if not isinstance(src, dict):
            continue
        vals = {key: src[key] for key in keys if key in src}
        if vals:
            out[section] = vals
    return out


def _redact_text(value: str) -> str:
    value = _SECRET_RE.sub("[REDACTED_SECRET]", value)
    home = str(Path.home())
    if home:
        value = value.replace(home, "~")
    return value[:1000]


def _sanitized_log(text: str) -> str:
    """Remove known text-bearing log records and formatter debug blocks."""
    out = []
    in_prompt = False
    for line in text.splitlines():
        if "=== FORMATTER SYSTEM PROMPT ===" in line:
            out.append("[REDACTED_FORMATTER_DEBUG_BLOCK]")
            in_prompt = True
            continue
        if in_prompt:
            if "=== END FORMATTER DEBUG ===" in line:
                in_prompt = False
            continue
        match = _SENSITIVE_LINE_RE.search(line)
        if match:
            line = line[:match.end()] + " [REDACTED_TEXT]"
        out.append(_redact_text(line))
    return "\n".join(out) + ("\n" if out else "")


def _history_metadata(path: Path, limit: int = 100) -> list[dict]:
    rows: deque[str] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            rows.extend(f)
    except FileNotFoundError:
        return []
    result = []
    for line in rows:
        try:
            src = json.loads(line)
        except Exception:
            continue
        context = src.get("context")
        result.append({
            "ts": src.get("ts"),
            "run_id": src.get("run_id"),
            "status": src.get("status"),
            "stage": src.get("stage"),
            "app": src.get("app"),
            "bundle_id": src.get("bundle_id"),
            "error": _redact_text(str(src.get("error") or "")) or None,
            "attempt": src.get("attempt", src.get("attempts")),
            "fast": bool(src.get("fast", False)),
            "format_fallback": bool(src.get("format_fallback", False)),
            "raw_chars": len(src.get("raw") or ""),
            "final_chars": len(src.get("final") or ""),
            "context_keys": sorted(context) if isinstance(context, dict) else [],
            "audio_retained": bool(src.get("audio")),
        })
    return result


def _app_version() -> dict:
    version = "unknown"
    build = None
    if getattr(sys, "frozen", False):
        try:
            from AppKit import NSBundle
            info = NSBundle.mainBundle().infoDictionary() or {}
            version = str(info.get("CFBundleShortVersionString", version))
            build = str(info.get("CFBundleVersion", "")) or None
        except Exception:
            pass
    else:
        try:
            from importlib.metadata import version as package_version
            version = package_version("dictate")
        except Exception:
            pass
    return {"version": version, "build": build}


def create_support_bundle(destination: Path, *, data_dir: Path = DATA_DIR,
                          cfg: dict | None = None,
                          permission_status: dict | None = None) -> Path:
    """Create a redacted zip for the user to inspect and share explicitly."""
    destination = Path(destination)
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if cfg is None:
        from .config import load_config
        cfg = load_config()
    if permission_status is None:
        try:
            from .permissions import check_all
            permission_status = check_all()
        except Exception as exc:
            permission_status = {"check_error": type(exc).__name__}

    app = _app_version()
    system = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app": app,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "permissions": permission_status,
        "log_policy": {
            "automatic_upload": False,
            "rotating_max_bytes": LOG_MAX_BYTES,
            "rotating_backups": LOG_BACKUPS,
        },
    }
    manifest = {
        "privacy": "User-created local bundle; nothing was uploaded.",
        "excluded": [
            "API keys and credentials", "transcript/final text",
            "focused/visible context text", "custom prompts", "audio files",
        ],
        "included": [
            "sanitized rotating logs", "build/system/permission metadata",
            "allow-listed settings", "last 100 run-status metadata rows",
        ],
    }
    history_path = Path(data_dir) / "history.jsonl"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        zf.writestr("system.json", json.dumps(system, indent=2, default=str) + "\n")
        zf.writestr("config-sanitized.json", json.dumps(
            _safe_config(cfg), indent=2, default=str) + "\n")
        zf.writestr("history-metadata.json", json.dumps(
            _history_metadata(history_path), indent=2, default=str) + "\n")
        log_dir = Path(data_dir) / "logs"
        for path in sorted(log_dir.glob(f"{LOG_NAME}*"))[:LOG_BACKUPS + 1]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            zf.writestr(f"logs/{path.name}", _sanitized_log(text))
    return destination


def default_bundle_name() -> str:
    return f"golos-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"


def visual_health_summary(snapshot: dict | None) -> dict:
    """Content-free strip/pill health fields for logs and support triage.

    Expects a ``Bubble.diagnostic_snapshot()`` dict (or similar). Never includes
    spoken text, paths, or window titles — only visibility / WindowServer /
    recovery counters already present on the snapshot.
    """
    if not isinstance(snapshot, dict):
        return {"available": False}
    wings = snapshot.get("wings") if isinstance(snapshot.get("wings"), dict) else {}
    pill = snapshot.get("pill") if isinstance(snapshot.get("pill"), dict) else {}
    return {
        "available": True,
        "state": snapshot.get("state"),
        "enforce_ok": snapshot.get("enforce_ok"),
        "present_token": snapshot.get("present_token"),
        "recover_attempts": snapshot.get("recover_attempts"),
        "recover_total": snapshot.get("recover_total"),
        "last_recover": snapshot.get("last_recover"),
        "wings_window": wings.get("window"),
        "wings_visible": wings.get("visible"),
        "wings_ws": wings.get("ws"),
        "wings_ws_presented": wings.get("ws_presented"),
        "pill_window": pill.get("window"),
        "pill_visible": pill.get("visible"),
        "pill_ws": pill.get("ws"),
        "pill_ws_presented": pill.get("ws_presented"),
    }
