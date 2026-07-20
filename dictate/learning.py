"""Self-improving dictionary: notice manual edits to inserted text, propose corrections.

Flow: after each successful paste the AppController keeps a `last_insertion`
record. Edit-capture triggers (next recording, app switch, 45s timer, the
"Check for edits" button) read the text field via Accessibility and diff it
against the insertion; pairs go to suggestions.jsonl. The Settings → History
tab lists aggregated suggestions with promote/dismiss actions.

The pure text-diff helpers live in dictate_core.learning (UI-free).
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dictate_core.learning import (  # noqa: F401  (re-exported for the app)
    extract_replacement_pairs, norm_text, pair_is_plausible, suggest_pairs,
)

log = logging.getLogger(__name__)

MAX_AX_CHARS = 20_000


# ---------------------------------------------------------------------------
# Accessibility read


def read_focused_text() -> str | None:
    """AXValue of the focused UI element, capped at 20k chars. None on failure."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return None
        err, value = AXUIElementCopyAttributeValue(focused, "AXValue", None)
        if err == 0 and isinstance(value, str):
            return value[:MAX_AX_CHARS]
    except Exception as e:
        log.info("Could not read focused text (Accessibility granted?): %s", e)
    return None


def read_focused_text_for_pid(pid: int) -> str | None:
    """Best-effort AX read of another app's focused element (used when the
    user has already switched away from the insertion app)."""
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
        )
        ax_app = AXUIElementCreateApplication(pid)
        err, focused = AXUIElementCopyAttributeValue(ax_app, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return None
        err, value = AXUIElementCopyAttributeValue(focused, "AXValue", None)
        if err == 0 and isinstance(value, str):
            return value[:MAX_AX_CHARS]
    except Exception as e:
        log.info("Could not read focused text of pid %s: %s", pid, e)
    return None


def read_selection() -> str | None:
    """AXSelectedText of the focused element. None on failure."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return None
        err, value = AXUIElementCopyAttributeValue(focused, "AXSelectedText", None)
        if err == 0 and isinstance(value, str) and value.strip():
            return value.strip()
    except Exception as e:
        log.info("Could not read selection (Accessibility granted?): %s", e)
    return None


# ---------------------------------------------------------------------------
# suggestions store


def append_suggestions(path: str, app_name: str, pairs: list[tuple[str, str]]) -> None:
    if not pairs:
        return
    ts = datetime.now(timezone.utc).isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for wrong, right in pairs:
            f.write(json.dumps({"ts": ts, "app": app_name,
                                "wrong": wrong, "right": right},
                               ensure_ascii=False) + "\n")
    log.info("Recorded %d suggestion(s): %s", len(pairs),
             "; ".join(f"{w!r} -> {r!r}" for w, r in pairs))


def _read_jsonl(path: str) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_dismissed(path: str) -> set[tuple[str, str]]:
    return {(r.get("wrong", ""), r.get("right", "")) for r in _read_jsonl(path)}


def dismiss_pair(path: str, wrong: str, right: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "wrong": wrong, "right": right},
                           ensure_ascii=False) + "\n")


def aggregate_suggestions(path: str, dismissed_path: str) -> list[dict]:
    """Aggregate suggestions.jsonl into candidates sorted by count desc.

    Each entry: {wrong, right, count, last_app}. Dismissed pairs excluded."""
    dismissed = load_dismissed(dismissed_path)
    counts: dict[tuple[str, str], dict] = {}
    for rec in _read_jsonl(path):
        key = (rec.get("wrong", ""), rec.get("right", ""))
        if not all(key) or key in dismissed:
            continue
        entry = counts.setdefault(key, {"wrong": key[0], "right": key[1],
                                        "count": 0, "last_app": ""})
        entry["count"] += 1
        entry["last_app"] = rec.get("app", "")
    return sorted(counts.values(), key=lambda e: -e["count"])


# ---------------------------------------------------------------------------
# promote actions (used by the Settings buttons)


def promote_to_corrections(corrections_path: str, wrong: str, right: str) -> None:
    with open(corrections_path, "a", encoding="utf-8") as f:
        f.write(f"{wrong}\t{right}\n")
    log.info("Added correction: %r -> %r", wrong, right)


def promote_to_dictionary(dictionary_path: str, term: str) -> None:
    with open(dictionary_path, "a", encoding="utf-8") as f:
        f.write(term.strip() + "\n")
    log.info("Added dictionary term: %r", term)


# ---------------------------------------------------------------------------
# main entry


def capture_edit_async(app_controller, on_done) -> None:
    """Worker-thread variant: AX reads + diff OFF the main thread (a slow
    scrollback can stall the run loop). on_done(pairs) is invoked on the main
    loop via AppHelper.callAfter."""
    from PyObjCTools import AppHelper

    def work():
        pairs = capture_edit(app_controller)
        AppHelper.callAfter(on_done, pairs)

    threading.Thread(target=work, daemon=True).start()


def capture_edit(app_controller, text: str | None = None) -> list[tuple[str, str]]:
    """Look for manual edits to the last insertion; record suggestions.

    Triggers: start of every recording, the "Check for edits" button, an
    app-switch away from the insertion app (text read from the old app's pid
    is passed in), and a 45s fallback timer. When `text` is given, the
    frontmost-app check and the AX read are skipped (caller already read the
    right field). Silent-ish on any failure (INFO log).
    """
    cfg = app_controller.cfg
    learning = cfg.get("learning", {})
    if not learning.get("enabled", True):
        return []
    li = getattr(app_controller, "last_insertion", None)
    if not li:
        return []
    window = learning.get("edit_window_seconds", 600)
    age = time.time() - li.get("ts", 0)
    if age > window:
        log.info("Last insertion too old for edit capture (%.0fs > %ds).", age, window)
        return []
    if text is None:
        from .context import frontmost_context
        front = frontmost_context()
        if li.get("bundle_id") and front.get("bundle_id") != li["bundle_id"]:
            log.info("Frontmost app changed since insertion; skipping edit capture.")
            return []
        text = read_focused_text()
    if not text:
        log.info("No focused text to compare against; skipping edit capture.")
        return []
    pairs = suggest_pairs(text, li.get("final", ""))
    # Dedupe against pairs the live edit watcher already cued/recorded for
    # this insertion — nothing gets recorded twice.
    watcher = getattr(app_controller, "_watcher", None)
    if watcher is not None and watcher.seen:
        pairs = [p for p in pairs if p not in watcher.seen]
    if pairs:
        # Recorded: don't report the same insertion again.
        app_controller.last_insertion = None
        append_suggestions(cfg["paths"]["suggestions"],
                           li.get("app_name", ""), pairs)
    return pairs
