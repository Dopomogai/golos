"""Speech-to-text backends: local mlx-whisper, OpenAI-compatible, Deepgram.

Privacy boundary: mlx keeps audio on-device. openrouter / openai_compatible /
deepgram upload the 16 kHz wav (or base64 equivalent) to the remote API —
that is when mic data leaves the Mac for transcription. The optional
formatter send_audio path (stage 2) is separate and lives in formatter.py.
"""

import io
import logging
import os
import tempfile
import wave

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

LANG_NAMES = {
    "en": "English", "uk": "Ukrainian", "ru": "Russian", "de": "German",
    "es": "Spanish", "fr": "French", "it": "Italian", "pt": "Portuguese",
    "pl": "Polish", "nl": "Dutch", "ja": "Japanese", "zh": "Chinese",
    "ko": "Korean",
}


def validate_languages(langs) -> list[str]:
    """Normalize a languages list: lowercase, strip, keep /^[a-z]{2,3}$/,
    drop the rest with a warning."""
    import re
    out = []
    for lang in langs or []:
        code = str(lang).strip().lower()
        if re.fullmatch(r"[a-z]{2,3}", code):
            out.append(code)
        elif code:
            log.warning("Ignoring invalid language code %r (want like 'en', 'uk').",
                        lang)
    return out


def language_hint(langs: list[str]) -> str:
    """Biasing-prompt hint for the chosen languages, e.g.
    'Languages: English, Ukrainian.' Empty when unset."""
    if not langs:
        return ""
    names = ", ".join(LANG_NAMES.get(c, c) for c in langs)
    return f"Languages: {names}."


def write_wav(path: str, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write float32 audio to a 16-bit PCM WAV file."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """In-memory 16-bit PCM WAV (same encoding as write_wav)."""
    buf = io.BytesIO()
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class MlxWhisperBackend:
    """Local on-device STT via mlx-whisper. Audio never leaves the machine."""

    def __init__(self, model: str, language: str = "",
                 languages: list[str] | None = None):
        self.model = model
        self.languages = languages or []
        if len(self.languages) > 1:
            log.info("mlx takes one language only; list %s ignored, using auto-detect.",
                     self.languages)
        self.language = (self.languages[0] if len(self.languages) == 1
                         else (language or None))

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        import mlx_whisper  # deferred: importing pulls in mlx

        hint = language_hint(self.languages)
        if hint:
            prompt = f"{prompt} {hint}".strip()
        kwargs = {"path_or_hf_repo": self.model, "verbose": False}
        if prompt:
            kwargs["initial_prompt"] = prompt
        if self.language:
            kwargs["language"] = self.language
        result = mlx_whisper.transcribe(audio, **kwargs)
        return result.get("text", "").strip()


class OpenAICompatibleBackend:
    """POST multipart to {base_url}/audio/transcriptions (OpenAI/Groq-style).

    Remote: wav bytes leave the Mac on every call.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        import httpx

        data = {"model": self.model}
        if prompt:
            data["prompt"] = prompt
        files = {"file": ("audio.wav", wav_bytes(audio), "audio/wav")}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{self.base_url}/audio/transcriptions",
                data=data, files=files, headers=headers,
            )
            resp.raise_for_status()
            return resp.json().get("text", "").strip()


class OpenRouterSTTBackend:
    """OpenRouter /audio/transcriptions: JSON body with base64 wav (NOT multipart).

    Remote: base64 wav leaves the Mac on every call.

    Verified against the live API 2026-07-18:
      POST {BASE_URL}/audio/transcriptions
      {"model": id, "input_audio": {"data": <base64 wav>, "format": "wav"},
       "prompt": "<optional biasing text>"}  ->  200 {"text": ...}
    The prompt field biases recognition (dictionary terms).
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 languages: list[str] | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.languages = languages or []

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        import base64
        import httpx

        hint = language_hint(self.languages)
        if hint:
            prompt = f"{prompt} {hint}".strip()

        body = {
            "model": self.model,
            "input_audio": {
                "data": base64.b64encode(wav_bytes(audio)).decode("ascii"),
                "format": "wav",
            },
        }
        # Language mapping per model family: deepgram takes a code or "multi"
        # (nova-3 code-switching); openai whisper/gpt-4o-transcribe takes one
        # code only (multi-language stays hinted via the prompt instead).
        if len(self.languages) == 1:
            body["language"] = self.languages[0]
        elif len(self.languages) > 1 and self.model.startswith("deepgram/"):
            body["language"] = "multi"
        if prompt:
            body["prompt"] = prompt
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=60) as client:
            resp = client.post(f"{self.base_url}/audio/transcriptions",
                               json=body, headers=headers)
        if resp.status_code != 200:
            # OpenRouter returns {"error": {"message": ...}} on failures.
            msg = resp.text[:300]
            try:
                msg = resp.json().get("error", {}).get("message", msg)
            except Exception:
                pass
            log.error("OpenRouter transcription failed (%s): %s",
                      resp.status_code, msg)
            raise RuntimeError(f"OpenRouter STT {resp.status_code}: {msg}")
        return resp.json().get("text", "").strip()


class DeepgramBackend:
    """POST wav bytes to Deepgram's /v1/listen endpoint. Remote: audio leaves Mac."""

    def __init__(self, api_key: str, model: str = "nova-3"):
        self.api_key = api_key
        self.model = model

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        import httpx

        params = [("model", self.model), ("smart_format", "true")]
        # Dictionary terms are passed as keyterms for vocabulary biasing.
        for term in prompt.split(", "):
            term = term.strip()
            if term:
                params.append(("keyterm", term))
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/wav",
        }
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                "https://api.deepgram.com/v1/listen",
                params=params, content=wav_bytes(audio), headers=headers,
            )
            resp.raise_for_status()
            payload = resp.json()
        try:
            return payload["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except (KeyError, IndexError):
            log.warning("Unexpected Deepgram response: %s", payload)
            return ""


def make_backend(cfg: dict, env_key) -> object | None:
    """Factory: build the STT backend selected in config. env_key(section) -> api key."""
    stt = cfg.get("stt", {})
    backend = stt.get("backend", "mlx")
    languages = validate_languages(stt.get("languages", []))
    if backend == "mlx":
        return MlxWhisperBackend(
            model=stt.get("mlx_model", "mlx-community/whisper-large-v3-turbo"),
            language=stt.get("language", ""),
            languages=languages,
        )
    if backend == "openrouter":
        from .openrouter import BASE_URL, DEFAULT_STT_MODEL, get_api_key
        key = get_api_key(cfg)
        if not key:
            log.error("OpenRouter STT selected but no API key "
                      "(OPENROUTER_API_KEY or [openrouter] api_key); "
                      "transcription will fail.")
            return None
        model = stt.get("openrouter", {}).get("model", DEFAULT_STT_MODEL)
        if isinstance(model, list):  # defensive: char-array corruption guard
            model = "".join(str(c) for c in model)
        return OpenRouterSTTBackend(base_url=BASE_URL, api_key=key, model=model,
                                    languages=languages)
    if backend == "openai_compatible":
        section = stt.get("cloud", {})
        key = env_key(section)
        if not key:
            log.error("Cloud STT selected but %s is not set; transcription will fail.",
                      section.get("api_key_env"))
            return None
        return OpenAICompatibleBackend(
            base_url=section.get("base_url", "https://api.openai.com/v1"),
            api_key=key,
            model=section.get("model", "whisper-1"),
        )
    if backend == "deepgram":
        section = stt.get("deepgram", {})
        key = env_key(section)
        if not key:
            log.error("Deepgram STT selected but %s is not set; transcription will fail.",
                      section.get("api_key_env"))
            return None
        return DeepgramBackend(api_key=key, model=section.get("model", "nova-3"))
    raise ValueError(f"Unknown stt.backend: {backend!r}")
