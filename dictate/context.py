"""Frontmost-app context: name, bundle id, focused window title.

Window title needs Accessibility permission; degrade gracefully to app name only.
"""

import logging

log = logging.getLogger(__name__)


def frontmost_context() -> dict:
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


def text_before_cursor(max_chars: int = 500) -> str:
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


def visible_text(max_chars: int = 4000) -> str:
    """Text the user is looking at (for citation mode): the focused element's
    AXValue; if that's short (< 200 chars), the focused window's first
    AXTextArea/AXScrollArea child's AXValue. Normalized, LAST max_chars.
    "" on any failure."""
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return ""
        err, value = AXUIElementCopyAttributeValue(focused, "AXValue", None)
        if err == 0 and isinstance(value, str) and len(value) >= 200:
            return normalize_visible(value)[-max_chars:]

        # Fallback: dig a text area out of the focused window.
        err, window = AXUIElementCopyAttributeValue(focused, "AXWindow", None)
        if err != 0 or window is None:
            return ""
        err, children = AXUIElementCopyAttributeValue(window, "AXChildren", None)
        if err != 0 or not children:
            return ""
        for child in children:
            try:
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
