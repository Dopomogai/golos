"""Insert text at the cursor of the frontmost app.

Two methods:
- **type** (default for single-line text): synthetic keystrokes via
  CGEventKeyboardSetUnicodeString, ~40 chars per event. Newlines become
  Return key events. No pasteboard is touched.
- **paste** (default for multi-line): temporary clipboard write + synthetic
  Cmd+V, then an **asynchronous, changeCount/CAS-guarded** restore of the
  previous pasteboard (including non-text types when snapshotable).

Why not leave the transcript on the clipboard by default?
  Leaving dictated text on the global pasteboard indefinitely is a privacy
  and UX bug (Cmd+V long after dictation pastes old speech).

Why not the old synchronous restore?
  A blocking 1.5 s sleep on the insert path raced slow targets / Universal
  Clipboard stalls into pasting the *old* content, and blocked the caller.

Default paste policy (`restore_clipboard=true`):
  1. Snapshot pasteboard items (data copies; non-text preserved when possible).
  2. Write the transcript; record changeCount (CAS token).
  3. Settle briefly, post Cmd+V, return immediately (no long main-thread sleep).
  4. After PASTE_RESTORE_DELAY on a daemon thread, restore only if
     changeCount is still our token — never clobber a copy the user made
     after Golos posted the paste.

Escape hatch: `restore_clipboard=false` leaves the transcript (target-app
compat / extremely slow paste consumers). Full clipboard-free path:
`method=type` (including multi-line).

`[insert] method` in config: auto | type | paste.
Without Accessibility permission macOS silently drops the synthetic events —
we log that loudly.

Never log transcript or clipboard contents.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

CHUNK = 40
PASTE_RESTORE_DELAY = 1.5
# Brief settle so the pasteboard write is visible before Cmd+V.
PASTE_SETTLE_DELAY = 0.06

_restore_warned = False

# Test hooks (headless): inject scheduling without real threads/AppKit.
_schedule_restore: Callable[..., None] | None = None


def _frontmost_name() -> str:
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is not None:
            return app.localizedName() or "unknown app"
    except Exception:
        pass
    return "unknown app"


def _check_ax() -> bool:
    """Return whether macOS currently trusts this exact app identity.

    Unsigned development and DMG builds can each have a separate TCC entry.
    Posting events without this permission produces a false-looking success:
    Quartz accepts the events, but macOS silently drops them.
    """
    try:
        from ApplicationServices import AXIsProcessTrusted
        if not AXIsProcessTrusted():
            log.error(
                "Accessibility permission NOT granted — macOS will SILENTLY DROP "
                "this insertion. Fix: System Settings → Privacy & Security → "
                "Accessibility, enable golos.app (or its launching terminal), "
                "then restart golos. "
                "Open now with: open \"%s\"",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            )
            return False
        return True
    except Exception:
        # Preserve the prior best-effort behavior if the permission API itself
        # is unavailable; the Quartz import below remains the platform guard.
        log.warning("Could not preflight Accessibility permission.", exc_info=True)
        return True


def _type_text(text: str) -> None:
    """Type the text with synthetic keystrokes (no pasteboard).

    Newlines are posted as Return (kVK_Return); other characters use Unicode
    string events in CHUNK-sized runs. This is the clipboard-free multi-line
    path when ``method=type``.
    """
    from Quartz import (
        CGEventCreateKeyboardEvent, CGEventKeyboardSetUnicodeString,
        CGEventPost, kCGHIDEventTap,
    )

    kVK_Return = 0x24

    def _post_return() -> None:
        down = CGEventCreateKeyboardEvent(None, kVK_Return, True)
        up = CGEventCreateKeyboardEvent(None, kVK_Return, False)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)
        time.sleep(0.01)

    def _post_unicode(chunk: str) -> None:
        if not chunk:
            return
        down = CGEventCreateKeyboardEvent(None, 0, True)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(down, len(chunk), chunk)
        CGEventKeyboardSetUnicodeString(up, len(chunk), chunk)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)
        time.sleep(0.01)

    # Split on newlines so multi-line method=type never needs the pasteboard.
    parts = text.split("\n")
    for i, part in enumerate(parts):
        for j in range(0, len(part), CHUNK):
            _post_unicode(part[j:j + CHUNK])
        if i < len(parts) - 1:
            _post_return()


def _copy_nsdata(data: Any) -> Any | None:
    """Return an independent NSData copy, or None if empty/unavailable."""
    if data is None:
        return None
    try:
        length = data.length()
        if length == 0:
            return None
        return data.copy()
    except Exception:
        try:
            # Fallback: re-wrap bytes so clearContents cannot invalidate us.
            from Foundation import NSData
            raw = bytes(data)
            if not raw:
                return None
            return NSData.dataWithBytes_length_(raw, len(raw))
        except Exception:
            return None


def _snapshot_pasteboard(pb: Any) -> list[dict[Any, Any]]:
    """Copy pasteboard item payloads (all types) for later restore.

    Returns a list of type→NSData maps (one per pasteboard item). Empty list
    means the board was empty or unreadable — restore will clear it.
    """
    snapshot: list[dict[Any, Any]] = []
    try:
        items = pb.pasteboardItems()
    except Exception:
        items = None

    if items:
        for item in items:
            entry: dict[Any, Any] = {}
            try:
                types = item.types() or []
            except Exception:
                types = []
            for ptype in types:
                try:
                    data = _copy_nsdata(item.dataForType_(ptype))
                except Exception:
                    data = None
                if data is not None:
                    entry[ptype] = data
            if entry:
                snapshot.append(entry)
        if snapshot:
            return snapshot

    # Fallback: plain string only (older pasteboard state / no items).
    try:
        from AppKit import NSPasteboardTypeString
        from Foundation import NSData
        s = pb.stringForType_(NSPasteboardTypeString)
        if s is not None:
            raw = str(s).encode("utf-8")
            data = NSData.dataWithBytes_length_(raw, len(raw))
            snapshot.append({NSPasteboardTypeString: data})
    except Exception:
        pass
    return snapshot


def _restore_pasteboard_snapshot(pb: Any, snapshot: list[dict[Any, Any]]) -> None:
    """Replace pasteboard contents with a prior item snapshot (no content logs)."""
    from AppKit import NSPasteboardItem

    pb.clearContents()
    if not snapshot:
        return
    new_items = []
    for entry in snapshot:
        item = NSPasteboardItem.alloc().init()
        for ptype, data in entry.items():
            try:
                item.setData_forType_(data, ptype)
            except Exception:
                log.debug("skip restore type during pasteboard restore", exc_info=True)
        new_items.append(item)
    if new_items:
        pb.writeObjects_(new_items)


def should_restore_pasteboard(current_count: int, expected_count: int) -> bool:
    """CAS check: restore only if changeCount still matches our write.

    Pure function for headless tests. If the user (or another app) changed the
    pasteboard after our temporary write, changeCount advances and we must not
    overwrite their copy.
    """
    return current_count == expected_count


def _default_schedule_restore(
    delay: float,
    restore_fn: Callable[[], None],
) -> None:
    """Sleep off the AppKit main thread, then run restore_fn on the main loop.

    Uses AppHelper.callAfter when available so NSPasteboard mutations stay on
    the main thread; falls back to calling restore_fn directly if AppHelper
    is missing (tests / non-AppKit hosts).
    """

    def worker() -> None:
        time.sleep(delay)
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(restore_fn)
        except Exception:
            try:
                restore_fn()
            except Exception:
                log.warning("pasteboard restore failed", exc_info=True)

    threading.Thread(
        target=worker, name="golos-pasteboard-restore", daemon=True,
    ).start()


def _paste_text(text: str, restore_clipboard: bool = True) -> None:
    """Clipboard + synthetic Cmd+V, optional async CAS-guarded restore.

    Default restore_clipboard=True schedules a deferred restore that:
    - does not block this caller for PASTE_RESTORE_DELAY;
    - restores only when changeCount still matches our temporary write;
    - preserves prior non-text types when the snapshot captured them.

    restore_clipboard=False leaves the temporary write (compat escape hatch
    for targets that read the pasteboard long after Cmd+V). That re-opens the
    "transcript stays on the clipboard" privacy/UX issue by design.
    """
    global _restore_warned
    from AppKit import NSPasteboard, NSPasteboardTypeString
    from Quartz import (
        CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
        kCGHIDEventTap, kCGEventFlagMaskCommand,
    )

    pb = NSPasteboard.generalPasteboard()
    snapshot: list[dict[Any, Any]] | None = None
    if restore_clipboard:
        snapshot = _snapshot_pasteboard(pb)

    t0 = time.time()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    our_count = pb.changeCount()
    log.info("pasteboard temporary write took %.2fs", time.time() - t0)
    time.sleep(PASTE_SETTLE_DELAY)

    kVK_Command = 0x37
    kVK_ANSI_V = 0x09

    cmd_down = CGEventCreateKeyboardEvent(None, kVK_Command, True)
    v_down = CGEventCreateKeyboardEvent(None, kVK_ANSI_V, True)
    v_up = CGEventCreateKeyboardEvent(None, kVK_ANSI_V, False)
    cmd_up = CGEventCreateKeyboardEvent(None, kVK_Command, False)
    CGEventSetFlags(v_down, kCGEventFlagMaskCommand)
    CGEventSetFlags(v_up, kCGEventFlagMaskCommand)

    for ev in (cmd_down, v_down, v_up, cmd_up):
        CGEventPost(kCGHIDEventTap, ev)

    if not restore_clipboard:
        log.info(
            "pasteboard left after paste (restore_clipboard=false; "
            "transcript remains until something else replaces it)",
        )
        return

    if not _restore_warned:
        _restore_warned = True
        log.info(
            "restore_clipboard=true: scheduling async CAS restore after %.1fs "
            "(skips if pasteboard changeCount advances — e.g. user copied). "
            "Slow targets that read the pasteboard after restore can still "
            "see prior contents; use restore_clipboard=false or method=type "
            "for those apps.",
            PASTE_RESTORE_DELAY,
        )

    # Capture locals for the deferred closure; never capture `text`.
    expected_count = our_count
    snap = snapshot if snapshot is not None else []

    def _do_restore() -> None:
        try:
            current = pb.changeCount()
            if not should_restore_pasteboard(current, expected_count):
                log.info(
                    "pasteboard restore skipped (changeCount %s != %s)",
                    current, expected_count,
                )
                return
            t1 = time.time()
            _restore_pasteboard_snapshot(pb, snap)
            log.info(
                "pasteboard restored after paste (%.2fs, changeCount matched)",
                time.time() - t1,
            )
        except Exception:
            log.warning("pasteboard restore failed", exc_info=True)

    scheduler = _schedule_restore or _default_schedule_restore
    scheduler(PASTE_RESTORE_DELAY, _do_restore)


def insert_text(text: str, method: str = "auto",
                restore_clipboard: bool = True) -> bool:
    """Insert `text` into the frontmost application.

    Returns True after posting events. Missing Accessibility is detected before
    posting and returns False; a compatible target can still reject events, so
    True is not proof of target-app delivery. Call on the main thread when
    possible. Paste path only settles briefly (~60 ms); long restore delay is
    always asynchronous and must not hold an AppKit lock.
    """
    if not text:
        return False
    try:
        from Quartz import CGEventPost  # noqa: F401 — PyObjC availability check
    except ImportError:
        log.error("PyObjC not available; cannot insert text.")
        return False

    if not _check_ax():
        return False

    target = _frontmost_name()
    if method == "auto":
        method = "paste" if "\n" in text else "type"
    log.info("Inserting %d chars into %s (method=%s)", len(text), target, method)
    if method == "type":
        _type_text(text)
    else:
        _paste_text(text, restore_clipboard=restore_clipboard)
    log.info("Insertion posted (%d chars -> %s, method=%s)", len(text), target, method)
    return True
