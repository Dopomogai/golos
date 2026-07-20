#!/usr/bin/env python3
"""End-to-end proof that multi-line insertion survives (paste path).

Opens TextEdit, inserts "alpha\nbeta\ngamma" via the real insert_text
(auto -> paste for multi-line), reads the document text back through
ACCESSIBILITY (not AppleScript — no Automation consent needed), asserts all
three lines in order, then terminates TextEdit without saving.

Run: .venv/bin/python scripts/test_multiline_insert.py
Requires Accessibility permission for the host terminal.
"""

import subprocess
import sys
import time

TEXT = "alpha\nbeta\ngamma"


def textedit_pid():
    from AppKit import NSWorkspace
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == "com.apple.TextEdit":
            return app.processIdentifier()
    return None


def ax_doc_text(pid: int):
    """Text of the focused text area of TextEdit via AX."""
    from ApplicationServices import (
        AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
    )
    ax_app = AXUIElementCreateApplication(pid)
    err, window = AXUIElementCopyAttributeValue(ax_app, "AXFocusedWindow", None)
    if err != 0 or window is None:
        err, window = AXUIElementCopyAttributeValue(ax_app, "AXMainWindow", None)
    if err != 0 or window is None:
        return None
    err, children = AXUIElementCopyAttributeValue(window, "AXChildren", None)
    if err != 0:
        return None

    def find_text_area(el, depth=0):
        if depth > 4:
            return None
        err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
        if err == 0 and role == "AXTextArea":
            err, value = AXUIElementCopyAttributeValue(el, "AXValue", None)
            if err == 0 and isinstance(value, str):
                return value
        err, kids = AXUIElementCopyAttributeValue(el, "AXChildren", None)
        if err == 0 and kids:
            for k in kids:
                found = find_text_area(k, depth + 1)
                if found is not None:
                    return found
        return None

    for child in children or []:
        found = find_text_area(child)
        if found is not None:
            return found
    return None


def main() -> int:
    subprocess.run(["open", "-a", "TextEdit"], check=True)
    for _ in range(30):
        time.sleep(0.3)
        if textedit_pid() is not None:
            break
    pid = textedit_pid()
    if pid is None:
        print("FAIL: TextEdit did not start")
        return 1
    print(f"TextEdit running (pid {pid})")
    time.sleep(1.0)  # frontmost + window ready

    from dictate.insert import insert_text
    ok = insert_text(TEXT, method="auto")
    print(f"insert_text returned {ok} (method=auto -> paste for multi-line)")
    time.sleep(0.8)

    doc = ax_doc_text(pid)
    if doc is None:
        print("FAIL: could not read the document text via AX")
        result = 1
    else:
        print(f"document text read back: {doc!r}")
        lines = doc.splitlines()
        expected = TEXT.splitlines()
        if lines[:3] == expected:
            print("PASS: all three lines present in order (alpha / beta / gamma)")
            result = 0
        else:
            print(f"FAIL: expected first 3 lines {expected}, got {lines[:3]!r}")
            result = 1

    # terminate TextEdit without saving (force — no save prompt, no AppleScript)
    from AppKit import NSWorkspace
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == "com.apple.TextEdit":
            app.forceTerminate()
    print("TextEdit force-terminated (no save dialog)")
    return result


if __name__ == "__main__":
    sys.exit(main())
