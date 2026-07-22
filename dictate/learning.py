"""Self-improving dictionary: notice manual edits to inserted text, propose corrections.

Flow: after each successful paste the AppController keeps a `last_insertion`
record. Edit-capture triggers (next recording, app switch, 45s timer, the
"Check for edits" button) read the text field via Accessibility and diff it
against the insertion; pairs go to suggestions.jsonl. The Settings → History
tab lists aggregated suggestions with promote/dismiss actions.

Age gate: `eligible_last_insertion` is the single edit-window check. Past
`[learning] edit_window_seconds` the pending insertion is cleared once
(identity-safe), the EditWatcher for that insertion is stopped, and one
content-free expiry line is logged — then silence (no thrashing workers).

Optional [learning] reviewer (OpenRouter, audio-aware) may propose candidates
when enabled; deterministic suggest_pairs remains the offline/failure fallback.
Nothing is auto-promoted — human approval only.

The pure text-diff helpers live in dictate_core.learning (UI-free).
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dictate_core.learning import (  # noqa: F401  (re-exported for the app)
    extract_replacement_pairs, normalize_visible, norm_text,
    pair_is_plausible, suggest_pairs,
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


def append_suggestions(
    path: str,
    app_name: str,
    pairs: list[tuple[str, str]],
    *,
    provenance: str | None = None,
    model: str | None = None,
    confidence: float | None = None,
    confidences: list[float | None] | None = None,
) -> None:
    """Append (wrong, right) rows to suggestions.jsonl (local only; no network).

    Optional provenance/model/confidence fields are stored for newer rows;
    aggregate_suggestions still keys only on (wrong, right) so older rows
    and mixed sources keep working.
    """
    if not pairs:
        return
    ts = datetime.now(timezone.utc).isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for i, (wrong, right) in enumerate(pairs):
            row: dict = {
                "ts": ts,
                "app": app_name,
                "wrong": wrong,
                "right": right,
            }
            if provenance:
                row["provenance"] = provenance
            if model:
                row["model"] = model
            conf = None
            if confidences is not None and i < len(confidences):
                conf = confidences[i]
            elif confidence is not None:
                conf = confidence
            if conf is not None:
                row["confidence"] = conf
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    log.info("Recorded %d suggestion(s).", len(pairs))
    log.debug("Suggestion pairs: %s",
              "; ".join(f"{w!r} -> {r!r}" for w, r in pairs))


def propose_pairs(
    li: dict,
    text: str,
    cfg: dict,
    *,
    chat_post=None,
) -> tuple[list[tuple[str, str]], dict]:
    """Propose correction pairs for one insertion + observed field text.

    Tries the optional OpenRouter learning reviewer at most once per
    insertion (`li["_reviewer_done"]`). Falls back to deterministic
    suggest_pairs when the reviewer is disabled, keyless, errors, times
    out, returns malformed JSON, or yields no credible candidates.

    Returns (pairs, meta) where meta may include provenance, model,
    confidences, and from_reviewer. Never auto-promotes.
    """
    meta: dict = {"provenance": "deterministic", "from_reviewer": False}
    inserted = li.get("final", "") or ""
    raw = li.get("raw", "") or inserted
    learning = cfg.get("learning") or {}
    if not learning.get("enabled", True):
        return [], meta

    ins_n = norm_text(normalize_visible(inserted))
    full_n = norm_text(normalize_visible(text))
    if not ins_n or not full_n:
        return [], meta
    # Untouched field: do not burn the single reviewer attempt.
    if ins_n in full_n:
        return [], meta

    pairs: list[tuple[str, str]] = []
    confidences: list[float | None] = []

    from dictate_core.learning_reviewer import (
        candidates_to_pairs,
        review_edit,
        reviewer_config,
    )

    rcfg = reviewer_config(cfg)
    if rcfg["enabled"] and not li.get("_reviewer_done"):
        # At most one reviewer attempt per insertion (success or fail).
        li["_reviewer_done"] = True
        try:
            candidates = review_edit(
                raw=raw,
                inserted=inserted,
                edited=text,
                cfg=cfg,
                audio_path=li.get("audio_path"),
                chat_post=chat_post,
            )
            if candidates:
                pairs = candidates_to_pairs(candidates)
                confidences = [c.confidence for c in candidates]
                meta = {
                    "provenance": "reviewer",
                    "from_reviewer": True,
                    "model": rcfg["model"],
                    "confidences": confidences,
                }
                log.info("Learning reviewer proposed %d candidate(s).", len(pairs))
        except Exception as e:
            log.warning("Learning reviewer failed (%s); deterministic fallback.", e)

    if not pairs:
        pairs = suggest_pairs(text, inserted)
        meta = {"provenance": "deterministic", "from_reviewer": False}

    return pairs, meta


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
    """Set of (wrong, right) pairs the user has dismissed (never re-suggest)."""
    return {(r.get("wrong", ""), r.get("right", "")) for r in _read_jsonl(path)}


def dismiss_pair(path: str, wrong: str, right: str) -> None:
    """Append one dismissed pair (append-only log; aggregate filters it out)."""
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
    """Append one wrong\\tright line to corrections.tsv (caller reloads live)."""
    with open(corrections_path, "a", encoding="utf-8") as f:
        f.write(f"{wrong}\t{right}\n")
    log.info("Added one correction.")


def promote_to_dictionary(dictionary_path: str, term: str) -> None:
    """Append one vocabulary term to dictionary.txt (caller reloads live)."""
    with open(dictionary_path, "a", encoding="utf-8") as f:
        f.write(term.strip() + "\n")
    log.info("Added one dictionary term.")


# ---------------------------------------------------------------------------
# edit-window eligibility (authoritative age gate)


def edit_window_seconds(cfg: dict) -> float:
    """Configured `[learning] edit_window_seconds` (default 600)."""
    learning = cfg.get("learning") or {}
    return float(learning.get("edit_window_seconds", 600))


def insertion_within_edit_window(
    li: dict | None,
    cfg: dict,
    *,
    now: float | None = None,
) -> bool:
    """True when *li* is present and not older than the edit window."""
    if not li:
        return False
    if now is None:
        now = time.time()
    ts = li.get("ts") or 0
    return (now - float(ts)) <= edit_window_seconds(cfg)


def _stop_watcher_for_insertion(app_controller, li: dict, reason: str) -> None:
    watcher = getattr(app_controller, "_watcher", None)
    if watcher is None:
        return
    if getattr(watcher, "_insertion", None) is li:
        watcher.stop(reason)


def release_last_insertion(app_controller, li: dict) -> bool:
    """Clear *last_insertion* only if it is still the same object as *li*.

    Concurrent timer / app-switch workers that retained an older dict must not
    wipe a newer insertion that landed while they were in flight.
    """
    if getattr(app_controller, "last_insertion", None) is not li:
        return False
    app_controller.last_insertion = None
    return True


def expire_last_insertion(app_controller, li: dict) -> bool:
    """Expire one insertion: identity-safe clear, stop its watcher, log once.

    Returns True only when *li* was still current and was cleared. Repeat
    calls (or a worker holding a superseded dict) are silent no-ops.
    """
    if getattr(app_controller, "last_insertion", None) is not li:
        return False
    app_controller.last_insertion = None
    _stop_watcher_for_insertion(app_controller, li, "edit window expired")
    # Content-free: no transcript, app name, or path — ops signal only.
    log.info("Learning insertion expired.")
    return True


def eligible_last_insertion(
    app_controller,
    *,
    now: float | None = None,
) -> dict | None:
    """Authoritative gate: return *last_insertion* if still within the window.

    When the pending insertion is older than `[learning] edit_window_seconds`,
    clear it exactly once (identity-safe), stop its EditWatcher generation,
    log one content-free expiry line, and return None. Subsequent calls with
    no pending insertion are silent — no worker thrash, no repeat logs.
    """
    li = getattr(app_controller, "last_insertion", None)
    if not li:
        return None
    if insertion_within_edit_window(li, app_controller.cfg, now=now):
        return li
    expire_last_insertion(app_controller, li)
    return None


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


def capture_edit(
    app_controller,
    text: str | None = None,
    *,
    expected: dict | None = None,
) -> list[tuple[str, str]]:
    """Look for manual edits to the last insertion; record suggestions.

    Triggers: start of every recording, the "Check for edits" button, an
    app-switch away from the insertion app (text read from the old app's pid
    is passed in), and a 45s fallback timer. When `text` is given, the
    frontmost-app check and the AX read are skipped (caller already read the
    right field). Silent-ish on any failure (INFO log).

    *expected*, when given, must still be the controller's eligible insertion
    (identity); a worker that retained an older dict after a newer paste is
    a silent no-op.
    """
    cfg = app_controller.cfg
    learning = cfg.get("learning", {})
    if not learning.get("enabled", True):
        return []
    li = eligible_last_insertion(app_controller)
    if not li:
        return []
    if expected is not None and li is not expected:
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
    pairs, meta = propose_pairs(li, text, cfg)
    # Dedupe against pairs the live edit watcher already cued/recorded for
    # this insertion — nothing gets recorded twice.
    watcher = getattr(app_controller, "_watcher", None)
    if watcher is not None and watcher.seen:
        pairs = [p for p in pairs if p not in watcher.seen]
    if pairs:
        # Recorded: drop only this insertion (never a newer concurrent one).
        release_last_insertion(app_controller, li)
        append_suggestions(
            cfg["paths"]["suggestions"],
            li.get("app_name", ""),
            pairs,
            provenance=meta.get("provenance"),
            model=meta.get("model"),
            confidences=meta.get("confidences"),
        )
        if meta.get("from_reviewer") and hasattr(
                app_controller, "present_reviewer_suggestions"):
            # Distinct cue path: suggestion-ready animation + interactive cue.
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(
                    app_controller.present_reviewer_suggestions, pairs, meta)
            except Exception as e:
                log.info("Could not present reviewer suggestions: %s", e)
    return pairs
