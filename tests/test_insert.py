"""Insertion permission preflight tests (UI-free)."""

from dictate import insert
from dictate.app import _needs_onboarding


def test_missing_accessibility_stops_before_posting(monkeypatch):
    """Never report success when macOS would silently drop every event."""
    posted = []
    monkeypatch.setattr(insert, "_check_ax", lambda: False)
    monkeypatch.setattr(insert, "_type_text", lambda text: posted.append(text))

    assert insert.insert_text("hello", method="type") is False
    assert posted == []


def test_accessibility_preflight_allows_post(monkeypatch):
    posted = []
    monkeypatch.setattr(insert, "_check_ax", lambda: True)
    monkeypatch.setattr(insert, "_frontmost_name", lambda: "Test App")
    monkeypatch.setattr(insert, "_type_text", lambda text: posted.append(text))

    assert insert.insert_text("hello", method="type") is True
    assert posted == ["hello"]


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
