"""Append-only dictation history (JSONL under ~/.golos/).

Each successful pipeline writes one line with raw + final transcript, app
identity, a truncated formatter context, optional local wav path, and a
`fast` flag. Never pruned by the app; Settings → History only reads it.
Thread-safe: a process-wide lock serializes concurrent pipeline writers.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()


def append_history(path: str, app_name: str, bundle_id: str,
                   raw_text: str, final_text: str,
                   context: dict | None = None,
                   audio: str | None = None,
                   fast: bool = False) -> None:
    """Append one history record. `audio` is a local filesystem path (or None),
    never wav bytes — history must not bloat with binary payloads."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app": app_name,
        "bundle_id": bundle_id,
        "raw": raw_text,
        "final": final_text,
        "context": context or {},
        "audio": audio,
        "fast": fast,
    }
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
