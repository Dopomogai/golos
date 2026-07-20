"""Focused tests for live edit capture and focus-loss preservation."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from dictate.editwatcher import EditWatcher


class _Bubble:
    def __init__(self):
        self.cues: list[tuple[str, str, float]] = []

    def cue(self, wrong, right, seconds, on_accept):
        self.cues.append((wrong, right, seconds))


def _controller(tmp_path):
    suggestions = tmp_path / "suggestions.jsonl"
    return SimpleNamespace(
        cfg={
            "learning": {"live_cues": True, "live_cue_seconds": 8},
            "paths": {"suggestions": str(suggestions)},
        },
        last_insertion={
            "ts": time.time(),
            "raw": "testing the formatted alarm",
            "final": "testing the formatted alarm",
            "app_name": "Notes",
            "bundle_id": "com.apple.Notes",
        },
        bubble=_Bubble(),
        accept_cue=lambda wrong, right: None,
    )


def test_unstable_poll_caches_pair_then_focus_loss_flushes_once(tmp_path):
    """The screenshot case: edit once, then switch before a stable poll."""
    controller = _controller(tmp_path)
    watcher = EditWatcher(controller)
    watcher._insertion = controller.last_insertion
    watcher._gen = 4

    watcher._handle_poll_result(
        4,
        "testing the formatter LLM",
        None,
        {"pending_pairs": [("formatted alarm", "formatter LLM")]},
    )

    assert watcher.flush_pending("app switch") is True
    assert watcher.flush_pending("app switch") is False
    assert controller.bubble.cues == [
        ("formatted alarm", "formatter LLM", 8),
    ]

    rows = [
        json.loads(line)
        for line in (tmp_path / "suggestions.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["wrong"] == "formatted alarm"
    assert rows[0]["right"] == "formatter LLM"
    assert rows[0]["provenance"] == "deterministic-focus-loss"
    assert ("formatted alarm", "formatter LLM") in watcher.seen


def test_stable_result_supersedes_and_clears_pending_pair(tmp_path):
    controller = _controller(tmp_path)
    watcher = EditWatcher(controller)
    watcher._insertion = controller.last_insertion
    watcher._gen = 2
    watcher._pending_pairs = [("formatted alarm", "formatter LLM")]

    watcher._handle_poll_result(
        2,
        "testing the formatter LLM",
        [("formatted alarm", "formatter LLM")],
        {"provenance": "deterministic", "from_reviewer": False},
    )

    assert watcher._pending_pairs == []
    assert watcher.flush_pending("app switch") is False
    assert len(controller.bubble.cues) == 1


def test_stale_generation_cannot_cache_or_flush(tmp_path):
    controller = _controller(tmp_path)
    watcher = EditWatcher(controller)
    watcher._insertion = controller.last_insertion
    watcher._gen = 8

    watcher._handle_poll_result(
        7,
        "testing the formatter LLM",
        None,
        {"pending_pairs": [("formatted alarm", "formatter LLM")]},
    )

    assert watcher._pending_pairs == []
    assert watcher.flush_pending("app switch") is False


def test_stop_discards_pending_after_caller_has_had_chance_to_flush(tmp_path):
    controller = _controller(tmp_path)
    watcher = EditWatcher(controller)
    watcher._insertion = controller.last_insertion
    watcher._pending_pairs = [("formatted alarm", "formatter LLM")]

    watcher.stop("manual")

    assert watcher._insertion is None
    assert watcher._pending_pairs == []
    assert watcher.flush_pending("late") is False
