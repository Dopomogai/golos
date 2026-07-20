"""Insert text at the cursor of the frontmost app.

Two methods:
- **type** (default for single-line text): synthetic keystrokes via
  CGEventKeyboardSetUnicodeString, ~40 chars per event. No pasteboard is
  touched at all.
- **paste** (default for multi-line): clipboard + synthetic Cmd+V. The
  pasteboard KEEPS the transcript afterwards (like mainstream dictation
  apps): restoring the old clipboard raced the target app into pasting that
  OLD content when NSPasteboard.setString stalled (Universal Clipboard).
  `[insert] restore_clipboard = true` opts back into restoring (1500 ms).

`[insert] method` in config: auto | type | paste.
Without Accessibility permission macOS silently drops the synthetic events —
we log that loudly.
"""

import logging
import time

log = logging.getLogger(__name__)

CHUNK = 40
PASTE_RESTORE_DELAY = 1.5

_restore_warned = False


def _frontmost_name() -> str:
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is not None:
            return app.localizedName() or "unknown app"
    except Exception:
        pass
    return "unknown app"


def _check_ax() -> None:
    try:
        from ApplicationServices import AXIsProcessTrusted
        if not AXIsProcessTrusted():
            log.error(
                "Accessibility permission NOT granted — macOS will SILENTLY DROP "
                "this insertion. Fix: System Settings → Privacy & Security → "
                "Accessibility, enable your terminal, then restart dictate. "
                "Open now with: open \"%s\"",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            )
    except Exception:
        pass


def _type_text(text: str) -> None:
    """Type the text with synthetic keystrokes (no pasteboard)."""
    from Quartz import (
        CGEventCreateKeyboardEvent, CGEventKeyboardSetUnicodeString,
        CGEventPost, kCGHIDEventTap,
    )
    for i in range(0, len(text), CHUNK):
        chunk = text[i:i + CHUNK]
        down = CGEventCreateKeyboardEvent(None, 0, True)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(down, len(chunk), chunk)
        CGEventKeyboardSetUnicodeString(up, len(chunk), chunk)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)
        time.sleep(0.01)


def _paste_text(text: str, restore_clipboard: bool = False) -> None:
    """Clipboard + synthetic Cmd+V.

    Default: the pasteboard keeps the transcript (no restore — restoring
    raced the target app into pasting the OLD clipboard when setString
    stalled). restore_clipboard=True opts back into restoring after 1500 ms.
    """
    global _restore_warned
    from AppKit import NSPasteboard, NSPasteboardTypeString
    from Quartz import (
        CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
        kCGHIDEventTap, kCGEventFlagMaskCommand,
    )

    pb = NSPasteboard.generalPasteboard()
    old_string = pb.stringForType_(NSPasteboardTypeString) \
        if restore_clipboard else None

    t0 = time.time()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    log.info("pasteboard setString took %.2fs", time.time() - t0)
    time.sleep(0.06)  # let the pasteboard settle

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

    if restore_clipboard:
        if not _restore_warned:
            _restore_warned = True
            log.info("restore_clipboard=true: restoring after %.1fs — note this "
                     "can race slow target apps into pasting the OLD clipboard.",
                     PASTE_RESTORE_DELAY)
        time.sleep(PASTE_RESTORE_DELAY)  # target app must consume the paste first
        t0 = time.time()
        if old_string is not None:
            pb.clearContents()
            pb.setString_forType_(old_string, NSPasteboardTypeString)
        log.info("pasteboard restored (restore took %.2fs)", time.time() - t0)
    else:
        log.info("clipboard now holds the transcript")


def insert_text(text: str, method: str = "auto",
                restore_clipboard: bool = False) -> bool:
    """Insert `text` into the frontmost application.

    Returns True after posting events (macOS may still drop them without
    Accessibility — we cannot observe delivery). Call on the main thread when
    possible; paste path sleeps and must not run under a held AppKit lock.
    """
    if not text:
        return False
    try:
        from Quartz import CGEventPost  # noqa: F401 — PyObjC availability check
    except ImportError:
        log.error("PyObjC not available; cannot insert text.")
        return False

    target = _frontmost_name()
    if method == "auto":
        method = "paste" if "\n" in text else "type"
    log.info("Inserting %d chars into %s (method=%s)", len(text), target, method)
    _check_ax()

    if method == "type":
        _type_text(text)
    else:
        _paste_text(text, restore_clipboard=restore_clipboard)
    log.info("Insertion posted (%d chars -> %s, method=%s)", len(text), target, method)
    return True
