"""Shared fixtures for headless golos tests.

Guardrails: no live network, no mic, no clipboard mutation, no synthetic
keys, no writes to the real ~/.golos directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Drop API keys so accidental network paths cannot authenticate."""
    for var in (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Ensure no test accidentally points cwd-relative paths at the real home.
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
    (tmp_path / "fake_home").mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def tmp_data_dir(tmp_path) -> Path:
    d = tmp_path / "golos_data"
    d.mkdir()
    return d


class FakeBubble:
    """Minimal bubble stand-in for AppController tests."""

    def __init__(self):
        self.states: list[str] = []
        self.notices: list[tuple] = []
        self.cues: list[tuple] = []
        self.suggestions_ready: list[tuple] = []
        self.sensitivity: float | None = None

    def set_state(self, state):
        self.states.append(state)

    def notice(self, text, kind="success", seconds=1.5):
        self.notices.append((text, kind, seconds))

    def cue(self, wrong, right, seconds, on_accept):
        self.cues.append((wrong, right, seconds))

    def suggestion_ready(self, wrong, right, seconds, on_accept):
        self.suggestions_ready.append((wrong, right, seconds))

    def set_sensitivity(self, value):
        self.sensitivity = value


class FakeRecorder:
    """In-memory recorder; no PortAudio / mic."""

    def __init__(self, audio=None):
        import numpy as np
        self._audio = audio if audio is not None else np.zeros(8000, dtype="float32")
        self.started = 0
        self.stopped = 0
        self.aborted = 0
        self.active = False

    def start(self):
        self.started += 1
        self.active = True

    def stop(self):
        self.stopped += 1
        self.active = False
        return self._audio

    def abort(self):
        self.aborted += 1
        self.active = False


class FakeSTT:
    def __init__(self, text="hello world"):
        self.text = text
        self.calls: list[tuple] = []

    def transcribe(self, audio, prompt=""):
        self.calls.append((len(audio), prompt))
        return self.text


class FakeFormatter:
    def __init__(self, enabled=True, result=None, fail=False):
        self.enabled = enabled
        self.result = result
        self.fail = fail
        self.calls: list = []
        self.dictionary_terms: list = []
        self.corrections: list = []

    def configure(self, cfg, dictionary_terms, corrections):
        self.dictionary_terms = dictionary_terms
        self.corrections = corrections

    def set_vocabulary(self, dictionary_terms, corrections):
        self.dictionary_terms = dictionary_terms
        self.corrections = corrections

    def format(self, raw_text, context=None, audio_wav=None):
        self.calls.append((raw_text, context, audio_wav is not None))
        if self.fail:
            raise RuntimeError("formatter boom")
        if self.result is not None:
            return self.result
        return raw_text
