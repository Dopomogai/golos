"""Compatibility shim — the implementation moved to dictate_core.stt."""
from dictate_core.stt import *  # noqa: F401,F403
from dictate_core.stt import (  # noqa: F401
    DeepgramBackend, MlxWhisperBackend, OpenAICompatibleBackend,
    OpenRouterSTTBackend, SAMPLE_RATE, make_backend, wav_bytes, write_wav,
)
