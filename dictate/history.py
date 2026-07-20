"""Append-only dictation history (JSONL)."""

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
