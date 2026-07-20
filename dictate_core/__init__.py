"""dictate_core — the UI-free brain of dictate, embeddable in other apps.

Quickstart:

    from dictate_core import VoicePipeline
    vp = VoicePipeline()                      # key: arg > env > ~/.dictate/config.toml
    text = vp.process(open("clip.wav", "rb").read(), app_name="Slack")

No AppKit/Quartz imports anywhere in this package (enforced by tests).
"""

import io
import logging
import os
import sys
import wave
from pathlib import Path

log = logging.getLogger(__name__)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from .learning import (  # noqa: F401
    extract_replacement_pairs, norm_text, pair_is_plausible, suggest_pairs,
)
from .stt import MlxWhisperBackend, OpenRouterSTTBackend  # noqa: F401
from .formatter import Formatter  # noqa: F401
from .openrouter import (  # noqa: F401
    BASE_URL, DEFAULT_CHAT_MODEL, DEFAULT_STT_MODEL, TRANSCRIPTION_MODELS,
)

_DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-turbo"


def _key_from_config() -> str | None:
    """Read the OpenRouter key from ~/.dictate/config.toml (read-only — no
    migration, no writes)."""
    try:
        with open(Path.home() / ".dictate" / "config.toml", "rb") as f:
            cfg = tomllib.load(f)
    except OSError:
        return None
    key = (cfg.get("openrouter") or {}).get("api_key") or None
    if isinstance(key, list):  # legacy char-array corruption guard
        key = "".join(str(c) for c in key)
    return key or None


def _decode_wav(data: bytes):
    """16-bit PCM mono wav bytes -> float32 numpy array."""
    import numpy as np
    with wave.open(io.BytesIO(data), "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
            raise ValueError("need 16-bit PCM mono wav")
        rate = wf.getframerate()
        audio = (np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                 .astype(np.float32) / 32768.0)
    if rate != 16000:
        raise ValueError(f"need 16 kHz wav (got {rate} Hz)")
    return audio


class VoicePipeline:
    """Reusable two-stage voice pipeline: STT (+biasing) -> LLM formatting.

    Key resolution for OpenRouter: explicit `openrouter_key` arg >
    OPENROUTER_API_KEY env var > ~/.dictate/config.toml (read-only).
    """

    def __init__(self, stt_backend="openrouter", openrouter_key=None,
                 stt_model=None, formatter_model=None, formatter_enabled=True,
                 dictionary=None, corrections=None, language=""):
        self._key = (openrouter_key or os.environ.get("OPENROUTER_API_KEY")
                     or _key_from_config())
        self._terms = list(dictionary or [])
        if stt_backend == "openrouter":
            if not self._key:
                raise ValueError("OpenRouter STT needs an API key "
                                 "(arg, OPENROUTER_API_KEY, or ~/.dictate/config.toml)")
            self._stt = OpenRouterSTTBackend(
                BASE_URL, self._key, stt_model or DEFAULT_STT_MODEL)
        elif stt_backend == "mlx":
            self._stt = MlxWhisperBackend(stt_model or _DEFAULT_MLX_MODEL,
                                          language=language)
        else:
            raise ValueError(f"unknown stt_backend: {stt_backend!r}")
        fmt_cfg = {
            "formatting": {
                "enabled": formatter_enabled,
                "provider": "openrouter",
                "model": formatter_model or DEFAULT_CHAT_MODEL,
            },
            "openrouter": {"api_key": self._key},
        }
        self._formatter = Formatter(fmt_cfg, self._terms,
                                    list(corrections or []))

    def transcribe(self, wav: bytes) -> str:
        """16 kHz mono wav bytes -> raw transcript (dictionary-biased)."""
        audio = _decode_wav(wav)
        return self._stt.transcribe(audio, prompt=", ".join(self._terms))

    def format(self, text: str, *, app_name="", bundle_id="", window_title="",
               visible_text="", text_before_cursor="") -> str:
        """Stage-2 LLM formatting; passthrough when disabled or keyless."""
        ctx = {"app_name": app_name, "bundle_id": bundle_id,
               "window_title": window_title}
        if visible_text:
            ctx["visible_text"] = visible_text
        if text_before_cursor:
            ctx["text_before_cursor"] = text_before_cursor
        return self._formatter.format(text, ctx)

    def process(self, wav: bytes, **fmt_ctx) -> str:
        """transcribe + format in one call."""
        return self.format(self.transcribe(wav), **fmt_ctx)

    def suggest_corrections(self, inserted: str, edited: str) -> list[tuple[str, str]]:
        """Learning diff: what did the user change about the inserted text?"""
        return suggest_pairs(edited, inserted)


__all__ = [
    "VoicePipeline",
    "MlxWhisperBackend", "OpenRouterSTTBackend", "Formatter",
    "BASE_URL", "DEFAULT_CHAT_MODEL", "DEFAULT_STT_MODEL", "TRANSCRIPTION_MODELS",
    "extract_replacement_pairs", "norm_text", "pair_is_plausible", "suggest_pairs",
]
