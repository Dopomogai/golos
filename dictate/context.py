"""Frontmost-app context: name, bundle id, focused window title, pid.

Window title and field text need Accessibility; degrade gracefully when
missing. Privacy: `pid` is local bookkeeping only (edit capture after app
switch) and must never be sent to the formatter. App identity and scraped
field/window text leave the Mac only when the formatter is enabled and the
matching [context] toggles allow them — see AppController._prepare_context.

Text roles for the formatter (kept separate on purpose):
  focused_field_text  — full AXValue of the focused input (what the user
                        is composing), capped
  text_before_cursor  — slice of that field before the caret (continuation)
  visible_text        — surrounding/on-screen reading context, never a
                        silent reuse of the focused field
"""

import logging

log = logging.getLogger(__name__)

# Caps keep formatter payloads bounded (no PID; text only).
_FOCUSED_FIELD_MAX = 4000
_VISIBLE_TEXT_MAX = 4000
_TEXT_BEFORE_CURSOR_MAX = 500


def frontmost_context() -> dict:
    """Snapshot of the frontmost app. Keys: app_name, bundle_id, window_title, pid.

    Best-effort: missing Accessibility yields empty window_title; failures
    never raise. Safe to call from a worker thread (AppKit NSWorkspace + AX).
    """
    ctx = {"app_name": "", "bundle_id": "", "window_title": "", "pid": None}
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is not None:
            ctx["app_name"] = app.localizedName() or ""
            ctx["bundle_id"] = app.bundleIdentifier() or ""
            ctx["pid"] = app.processIdentifier()
    except Exception as e:
        log.warning("Could not get frontmost application: %s", e)

    try:
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
        )
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is not None:
            ax_app = AXUIElementCreateApplication(app.processIdentifier())
            err, window = AXUIElementCopyAttributeValue(ax_app, "AXFocusedWindow", None)
            if err == 0 and window is not None:
                err, title = AXUIElementCopyAttributeValue(window, "AXTitle", None)
                if err == 0 and isinstance(title, str):
                    ctx["window_title"] = title
    except Exception:
        # Accessibility permission not granted (or no focused window) — fine.
        pass
    return ctx


def text_before_cursor(max_chars: int = _TEXT_BEFORE_CURSOR_MAX) -> str:
    """Up to `max_chars` of text immediately before the cursor in the focused
    field (AXValue + AXSelectedTextRange). "" on any failure — this is a
    best-effort formatter nicety, never a blocker."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
            AXValueGetValue, kAXValueCFRangeType,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return ""
        err, value = AXUIElementCopyAttributeValue(focused, "AXValue", None)
        if err != 0 or not isinstance(value, str) or not value:
            return ""
        err, range_value = AXUIElementCopyAttributeValue(
            focused, "AXSelectedTextRange", None)
        if err != 0 or range_value is None:
            return ""
        ok, cf_range = AXValueGetValue(range_value, kAXValueCFRangeType, None)
        if not ok:
            return ""
        # PyObjC may return a CFRange struct (.location) or a plain
        # (location, length) tuple depending on version — handle both.
        location = getattr(cf_range, "location", None)
        if location is None:
            location = cf_range[0]
        return value[max(0, int(location) - max_chars):int(location)]
    except Exception as e:
        log.info("Could not read text before cursor: %s", e)
        return ""


from dictate_core.learning import normalize_visible  # noqa: F401,E402


def focused_field_text(max_chars: int = _FOCUSED_FIELD_MAX) -> str:
    """Full accessible text of the currently focused input/control (what the
    user is producing). Last `max_chars` when longer. "" on any failure —
    best-effort; never blocks dictation."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return ""
        err, value = AXUIElementCopyAttributeValue(focused, "AXValue", None)
        if err != 0 or not isinstance(value, str) or not value:
            return ""
        if len(value) > max_chars:
            return value[-max_chars:]
        return value
    except Exception as e:
        log.info("Could not read focused field text: %s", e)
        return ""


def _ax_elements_equal(a, b) -> bool:
    """Best-effort AXUIElement identity; False when comparison is impossible."""
    if a is None or b is None:
        return False
    try:
        return bool(a == b)
    except Exception:
        return False


def visible_text(max_chars: int = _VISIBLE_TEXT_MAX) -> str:
    """Surrounding / on-screen reading context for citation mode.

    Never silently reuses the focused field's AXValue — that belongs in
    focused_field_text. Best-effort: first suitable AXTextArea/AXScrollArea
    under the focused window, skipping the focused element itself.
    Normalized, LAST max_chars. Empty string when inaccessible is fine.
    """
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(
            system, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return ""

        err, window = AXUIElementCopyAttributeValue(focused, "AXWindow", None)
        if err != 0 or window is None:
            return ""
        err, children = AXUIElementCopyAttributeValue(window, "AXChildren", None)
        if err != 0 or not children:
            return ""
        for child in children:
            try:
                if _ax_elements_equal(child, focused):
                    continue
                err, role = AXUIElementCopyAttributeValue(child, "AXRole", None)
                if err != 0 or role not in ("AXTextArea", "AXScrollArea"):
                    continue
                err, value = AXUIElementCopyAttributeValue(child, "AXValue", None)
                if err == 0 and isinstance(value, str) and value:
                    return normalize_visible(value)[-max_chars:]
            except Exception:
                continue
    except Exception as e:
        log.info("Could not read visible text: %s", e)
    return ""
