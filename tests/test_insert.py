"""Insertion permission preflight and clipboard-policy tests (UI-free).

Guardrails: no real NSPasteboard mutation, no synthetic keys, no network/mic.
"""

import sys
import types

from dictate import insert
from dictate.app import _needs_onboarding


def _stub_quartz(monkeypatch):
    """Satisfy insert_text's PyObjC availability check without real Quartz."""
    quartz = types.ModuleType("Quartz")
    quartz.CGEventPost = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "Quartz", quartz)


def test_missing_accessibility_stops_before_posting(monkeypatch):
    """Never report success when macOS would silently drop every event."""
    posted = []
    _stub_quartz(monkeypatch)
    monkeypatch.setattr(insert, "_check_ax", lambda: False)
    monkeypatch.setattr(insert, "_type_text", lambda text: posted.append(text))

    assert insert.insert_text("hello", method="type") is False
    assert posted == []


def test_accessibility_preflight_allows_post(monkeypatch):
    posted = []
    _stub_quartz(monkeypatch)
    monkeypatch.setattr(insert, "_check_ax", lambda: True)
    monkeypatch.setattr(insert, "_frontmost_name", lambda: "Test App")
    monkeypatch.setattr(insert, "_type_text", lambda text: posted.append(text))

    assert insert.insert_text("hello", method="type") is True
    assert posted == ["hello"]


def test_auto_single_line_uses_type(monkeypatch):
    typed, pasted = [], []
    _stub_quartz(monkeypatch)
    monkeypatch.setattr(insert, "_check_ax", lambda: True)
    monkeypatch.setattr(insert, "_frontmost_name", lambda: "Test App")
    monkeypatch.setattr(insert, "_type_text", lambda text: typed.append(text))
    monkeypatch.setattr(
        insert, "_paste_text",
        lambda text, restore_clipboard=True: pasted.append(
            (text, restore_clipboard)))

    assert insert.insert_text("one line", method="auto") is True
    assert typed == ["one line"]
    assert pasted == []


def test_auto_multiline_uses_paste_with_restore_default(monkeypatch):
    typed, pasted = [], []
    _stub_quartz(monkeypatch)
    monkeypatch.setattr(insert, "_check_ax", lambda: True)
    monkeypatch.setattr(insert, "_frontmost_name", lambda: "Test App")
    monkeypatch.setattr(insert, "_type_text", lambda text: typed.append(text))
    monkeypatch.setattr(
        insert, "_paste_text",
        lambda text, restore_clipboard=True: pasted.append(
            (text, restore_clipboard)))

    assert insert.insert_text("a\nb", method="auto") is True
    assert typed == []
    assert pasted == [("a\nb", True)]


def test_insert_text_default_restore_clipboard_is_true(monkeypatch):
    """API default flipped: do not leave transcript on the pasteboard."""
    seen = []
    _stub_quartz(monkeypatch)
    monkeypatch.setattr(insert, "_check_ax", lambda: True)
    monkeypatch.setattr(insert, "_frontmost_name", lambda: "Test App")
    monkeypatch.setattr(
        insert, "_paste_text",
        lambda text, restore_clipboard=True: seen.append(restore_clipboard))

    insert.insert_text("x\ny", method="paste")
    assert seen == [True]


def test_should_restore_pasteboard_cas_match():
    assert insert.should_restore_pasteboard(42, 42) is True


def test_should_restore_pasteboard_cas_mismatch_skips():
    """User copy after Golos paste advances changeCount — never clobber."""
    assert insert.should_restore_pasteboard(43, 42) is False
    assert insert.should_restore_pasteboard(0, 5) is False


def test_paste_schedules_async_restore_and_does_not_block(monkeypatch):
    """restore_clipboard=true: schedule restore; no long sleep on the caller."""
    sleeps = []
    scheduled = []

    class FakePB:
        def __init__(self):
            self._count = 10
            self.cleared = 0
            self.writes = []

        def changeCount(self):
            return self._count

        def clearContents(self):
            self.cleared += 1
            self._count += 1

        def setString_forType_(self, text, ptype):
            self.writes.append((ptype, text))
            self._count += 1

        def pasteboardItems(self):
            return []

        def stringForType_(self, ptype):
            return "prior-user-copy"

    fake_pb = FakePB()
    events = []

    monkeypatch.setattr(insert.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        insert, "_schedule_restore",
        lambda delay, fn: scheduled.append((delay, fn)))
    monkeypatch.setattr(insert, "_snapshot_pasteboard", lambda pb: [{"T": b"x"}])
    monkeypatch.setattr(
        insert, "_restore_pasteboard_snapshot",
        lambda pb, snap: events.append(("restore", list(snap))))

    import sys
    import types

    appkit = types.ModuleType("AppKit")
    appkit.NSPasteboard = types.SimpleNamespace(
        generalPasteboard=lambda: fake_pb)
    appkit.NSPasteboardTypeString = "public.utf8-plain-text"
    quartz = types.ModuleType("Quartz")
    quartz.CGEventCreateKeyboardEvent = lambda *a: object()
    quartz.CGEventPost = lambda *a: events.append("post")
    quartz.CGEventSetFlags = lambda *a: None
    quartz.kCGHIDEventTap = 0
    quartz.kCGEventFlagMaskCommand = 1
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    insert._paste_text("secret-transcript\nline2", restore_clipboard=True)

    # Caller only settles briefly — never the 1.5s restore delay.
    assert insert.PASTE_RESTORE_DELAY not in sleeps
    assert sleeps == [insert.PASTE_SETTLE_DELAY]
    assert len(scheduled) == 1
    assert scheduled[0][0] == insert.PASTE_RESTORE_DELAY
    assert fake_pb.writes  # temporary write happened
    # Never log or assert on transcript content in production code paths;
    # test may inspect mock writes only.
    assert fake_pb.writes[0][1] == "secret-transcript\nline2"

    # CAS match → restore runs.
    before_count = fake_pb.changeCount()
    assert insert.should_restore_pasteboard(before_count, before_count)
    scheduled[0][1]()
    assert ("restore", [{"T": b"x"}]) in events


def test_paste_restore_skipped_when_change_count_advances(monkeypatch):
    """After user copies, deferred restore must not overwrite their pasteboard."""
    sleeps = []
    scheduled = []
    restored = []

    class FakePB:
        def __init__(self):
            self._count = 1

        def changeCount(self):
            return self._count

        def clearContents(self):
            self._count += 1

        def setString_forType_(self, text, ptype):
            self._count += 1

        def pasteboardItems(self):
            return []

        def stringForType_(self, ptype):
            return None

    fake_pb = FakePB()

    monkeypatch.setattr(insert.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        insert, "_schedule_restore",
        lambda delay, fn: scheduled.append(fn))
    monkeypatch.setattr(insert, "_snapshot_pasteboard", lambda pb: [{"old": b"1"}])
    monkeypatch.setattr(
        insert, "_restore_pasteboard_snapshot",
        lambda pb, snap: restored.append(snap))

    import sys
    import types

    appkit = types.ModuleType("AppKit")
    appkit.NSPasteboard = types.SimpleNamespace(
        generalPasteboard=lambda: fake_pb)
    appkit.NSPasteboardTypeString = "public.utf8-plain-text"
    quartz = types.ModuleType("Quartz")
    quartz.CGEventCreateKeyboardEvent = lambda *a: object()
    quartz.CGEventPost = lambda *a: None
    quartz.CGEventSetFlags = lambda *a: None
    quartz.kCGHIDEventTap = 0
    quartz.kCGEventFlagMaskCommand = 1
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    insert._paste_text("dictated", restore_clipboard=True)
    our_count = fake_pb.changeCount()
    # Simulate user Cmd+C after Golos posted paste.
    fake_pb._count = our_count + 1
    scheduled[0]()
    assert restored == []


def test_paste_leave_clipboard_escape_hatch_schedules_nothing(monkeypatch):
    scheduled = []
    sleeps = []

    class FakePB:
        def __init__(self):
            self._count = 0

        def changeCount(self):
            return self._count

        def clearContents(self):
            self._count += 1

        def setString_forType_(self, text, ptype):
            self._count += 1

        def pasteboardItems(self):
            return []

        def stringForType_(self, ptype):
            return None

    fake_pb = FakePB()
    monkeypatch.setattr(insert.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        insert, "_schedule_restore",
        lambda delay, fn: scheduled.append((delay, fn)))

    import sys
    import types

    appkit = types.ModuleType("AppKit")
    appkit.NSPasteboard = types.SimpleNamespace(
        generalPasteboard=lambda: fake_pb)
    appkit.NSPasteboardTypeString = "public.utf8-plain-text"
    quartz = types.ModuleType("Quartz")
    quartz.CGEventCreateKeyboardEvent = lambda *a: object()
    quartz.CGEventPost = lambda *a: None
    quartz.CGEventSetFlags = lambda *a: None
    quartz.kCGHIDEventTap = 0
    quartz.kCGEventFlagMaskCommand = 1
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    insert._paste_text("leave-me", restore_clipboard=False)
    assert scheduled == []
    assert insert.PASTE_RESTORE_DELAY not in sleeps


def test_type_text_splits_newlines_without_pasteboard(monkeypatch):
    """Clipboard-free multi-line: Unicode chunks + Return, never pasteboard."""
    posts = []  # ("unicode", s) | "return"

    def fake_create(source, keycode, keydown):
        return {"keycode": keycode, "down": keydown, "unicode": None}

    def fake_set_unicode(event, length, string):
        event["unicode"] = string

    def fake_post(tap, event):
        if event.get("unicode") is not None:
            if event["down"]:
                posts.append(("unicode", event["unicode"]))
        elif event.get("keycode") == 0x24 and event["down"]:
            posts.append("return")

    monkeypatch.setattr(insert.time, "sleep", lambda s: None)

    import sys
    import types

    quartz = types.ModuleType("Quartz")
    quartz.CGEventCreateKeyboardEvent = fake_create
    quartz.CGEventKeyboardSetUnicodeString = fake_set_unicode
    quartz.CGEventPost = fake_post
    quartz.kCGHIDEventTap = 0
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    insert._type_text("alpha\nbeta")
    assert posts == [
        ("unicode", "alpha"),
        "return",
        ("unicode", "beta"),
    ]


def test_new_binary_reopens_onboarding_for_missing_permission():
    cfg = {"app": {"onboarded": True}}
    status = {
        "accessibility": False,
        "input_monitoring": True,
        "microphone": "authorized",
    }
    assert _needs_onboarding(cfg, status) is True


def test_fully_granted_existing_user_stays_uninterrupted():
    cfg = {"app": {"onboarded": True}}
    status = {
        "accessibility": True,
        "input_monitoring": True,
        "microphone": "authorized",
    }
    assert _needs_onboarding(cfg, status) is False
