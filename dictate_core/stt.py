"""Speech-to-text backends: local mlx-whisper, OpenAI-compatible, Deepgram.

Privacy boundary: mlx keeps audio on-device. openrouter / openai_compatible /
deepgram upload the 16 kHz wav (or base64 equivalent) to the remote API —
that is when mic data leaves the Mac for transcription. The optional
formatter send_audio path (stage 2) is separate and lives in formatter.py.

Cloud backends share a bounded retry for ordinary transient transport/HTTP
failures (idle DNS gaps, 429/5xx). Local MLX is never retried here. Valid
empty transcripts are returned immediately (not treated as failure).
"""

from __future__ import annotations

import io
import logging
import platform
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-turbo"

# Bounded cloud STT retry (live path). History/audio recovery remains the
# durable fallback when all attempts fail.
DEFAULT_STT_MAX_ATTEMPTS = 3
DEFAULT_STT_BACKOFF_BASE_S = 0.5  # sleeps: 0.5s then 1.0s between attempts
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

_T = TypeVar("_T")

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


def local_model_support() -> tuple[bool, str]:
    """Return whether this installation can run the optional MLX backend.

    The public Apple Silicon app bundles the MLX runtime but downloads model
    weights only on request. Cloud-only/Intel installs intentionally omit MLX.
    """
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "arm64e"):
        return False, "Local MLX transcription requires Apple Silicon."
    try:
        import importlib.util
        if importlib.util.find_spec("mlx_whisper") is None:
            return False, "MLX runtime is not installed in this cloud-only build."
    except (ImportError, ValueError):
        return False, "MLX runtime is not installed in this cloud-only build."
    return True, ""


def local_model_is_downloaded(model: str = DEFAULT_MLX_MODEL) -> bool:
    """Check local files/cache only; never contacts Hugging Face."""
    model_path = Path(model).expanduser()
    if model_path.is_dir():
        return ((model_path / "config.json").is_file()
                and ((model_path / "weights.safetensors").is_file()
                     or (model_path / "weights.npz").is_file()))
    try:
        from huggingface_hub import try_to_load_from_cache
        config = try_to_load_from_cache(model, "config.json")
        weights = (try_to_load_from_cache(model, "weights.safetensors")
                   or try_to_load_from_cache(model, "weights.npz"))
        return bool(config and weights)
    except (ImportError, OSError, ValueError):
        return False


def download_local_model(model: str = DEFAULT_MLX_MODEL) -> str:
    """Explicitly download optional MLX model weights; returns cache path."""
    supported, reason = local_model_support()
    if not supported:
        raise RuntimeError(reason)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError("Local-model downloader is not installed.") from e
    return str(snapshot_download(repo_id=model))


def write_wav(path: str, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write float32 audio to a 16-bit PCM WAV file."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def load_wav(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Read a mono 16-bit PCM WAV into float32 samples in [-1, 1].

    Used by recovery retry when a retained recording path exists. Raises
    ValueError if channels/rate do not match the capture contract.
    """
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getframerate() != sample_rate:
            raise ValueError(
                f"{path}: need {sample_rate} Hz mono wav "
                f"(got {wf.getframerate()} Hz x {wf.getnchannels()}ch)")
        return (np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                .astype(np.float32) / 32768.0)


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


# ---------------------------------------------------------------------------
# Bounded cloud STT retry (transport / transient HTTP only)
# ---------------------------------------------------------------------------


def is_transient_http_status(status_code: int) -> bool:
    """HTTP statuses safe to retry for cloud STT (not auth/other 4xx)."""
    try:
        return int(status_code) in TRANSIENT_HTTP_STATUSES
    except (TypeError, ValueError):
        return False


def is_transient_stt_transport_error(exc: BaseException) -> bool:
    """True for connect/DNS/reset and connect/read (and other) timeouts.

    Matches httpx TransportError / TimeoutException when available, plus
    common OSError/ConnectionError shapes (e.g. macOS DNS ``[Errno 8]``).
    Does not treat ordinary ValueError/RuntimeError as retryable.
    """
    try:
        import httpx
        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
    except ImportError:
        pass
    name = type(exc).__name__
    if name in {
        "TimeoutException", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
        "PoolTimeout", "ConnectError", "ReadError", "WriteError", "CloseError",
        "NetworkError", "TransportError", "RemoteProtocolError",
        "ProxyError",
    }:
        return True
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, ConnectionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 8:
        return True
    return False


def stt_retry_backoff_seconds(
    failed_attempt: int,
    base: float = DEFAULT_STT_BACKOFF_BASE_S,
) -> float:
    """Exponential backoff after a failed attempt (1-indexed).

    failed_attempt=1 → base; failed_attempt=2 → 2*base; …
    """
    if failed_attempt < 1:
        return base
    return float(base) * (2 ** (failed_attempt - 1))


def request_with_stt_retry(
    make_request: Callable[[], _T],
    *,
    provider: str,
    max_attempts: int = DEFAULT_STT_MAX_ATTEMPTS,
    sleep_fn: Callable[[float], None] | None = None,
    backoff_base: float = DEFAULT_STT_BACKOFF_BASE_S,
    response_status: Callable[[_T], int | None] | None = None,
) -> _T:
    """Run one cloud STT HTTP attempt with bounded transient retries.

    ``make_request`` performs a single HTTP exchange and returns a response
    object (or raises a transport/timeout error). When ``response_status``
    is set and returns a transient HTTP code (408/429/5xx listed in
    ``TRANSIENT_HTTP_STATUSES``), the call is retried. Non-transient 4xx and
    successful responses (including empty-transcript bodies) are returned
    immediately for the caller to parse or raise.

    Logs only provider, attempt, error class, and status — never audio,
    transcript, or API keys.

    **Read-timeout tradeoff:** a read timeout may mean the provider already
    accepted and billed the upload while the client never saw the body.
    Retrying can therefore duplicate cost (at most ``max_attempts - 1``
    extra uploads). We still retry within the bound so ordinary idle/DNS
    and gateway blips recover without a manual History retry; durable
    History + retained audio remains the fallback after exhaustion.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    sleep = time.sleep if sleep_fn is None else sleep_fn
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = make_request()
        except Exception as e:
            last_exc = e
            retryable = is_transient_stt_transport_error(e)
            if not retryable or attempt >= max_attempts:
                if retryable:
                    log.warning(
                        "STT provider=%s attempt=%d/%d error_class=%s (giving up)",
                        provider, attempt, max_attempts, type(e).__name__,
                    )
                raise
            delay = stt_retry_backoff_seconds(attempt, backoff_base)
            log.warning(
                "STT provider=%s attempt=%d/%d error_class=%s; retry in %.2fs",
                provider, attempt, max_attempts, type(e).__name__, delay,
            )
            sleep(delay)
            continue

        status: int | None = None
        if response_status is not None:
            try:
                status = response_status(result)
            except Exception:
                status = None
        if status is not None and is_transient_http_status(status):
            if attempt >= max_attempts:
                log.warning(
                    "STT provider=%s attempt=%d/%d status=%s (giving up)",
                    provider, attempt, max_attempts, status,
                )
                return result
            delay = stt_retry_backoff_seconds(attempt, backoff_base)
            log.warning(
                "STT provider=%s attempt=%d/%d status=%s; retry in %.2fs",
                provider, attempt, max_attempts, status, delay,
            )
            sleep(delay)
            continue

        return result

    # Unreachable when max_attempts >= 1 and make_request either returns or raises.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"STT provider={provider} retry loop exhausted without result")


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
        supported, reason = local_model_support()
        if not supported:
            raise RuntimeError(reason)
        if not local_model_is_downloaded(self.model):
            raise RuntimeError(
                "Local model is not downloaded. Open Settings → General and "
                "click ‘Download local (~1.5 GB)’ first.")
        import mlx_whisper  # deferred: cloud-only installs never import mlx

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

    Remote: wav bytes leave the Mac on every call (and on each retry attempt).
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 max_attempts: int = DEFAULT_STT_MAX_ATTEMPTS,
                 sleep_fn: Callable[[float], None] | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_attempts = max_attempts
        self._sleep_fn = sleep_fn

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        import httpx

        data = {"model": self.model}
        if prompt:
            data["prompt"] = prompt
        # Materialize once so retries re-send the same body (no re-encode drift).
        files = {"file": ("audio.wav", wav_bytes(audio), "audio/wav")}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/audio/transcriptions"

        def _once():
            # Fresh client per attempt so idle/DNS failures are not sticky.
            with httpx.Client(timeout=60) as client:
                return client.post(url, data=data, files=files, headers=headers)

        resp = request_with_stt_retry(
            _once,
            provider="openai_compatible",
            max_attempts=self.max_attempts,
            sleep_fn=self._sleep_fn,
            response_status=lambda r: r.status_code,
        )
        resp.raise_for_status()
        return resp.json().get("text", "").strip()


class OpenRouterSTTBackend:
    """OpenRouter /audio/transcriptions: JSON body with base64 wav (NOT multipart).

    Remote: base64 wav leaves the Mac on every call (and on each retry attempt).

    Verified against the live API 2026-07-18:
      POST {BASE_URL}/audio/transcriptions
      {"model": id, "input_audio": {"data": <base64 wav>, "format": "wav"},
       "prompt": "<optional biasing text>"}  ->  200 {"text": ...}
    The prompt field biases recognition (dictionary terms).
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 languages: list[str] | None = None,
                 max_attempts: int = DEFAULT_STT_MAX_ATTEMPTS,
                 sleep_fn: Callable[[float], None] | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.languages = languages or []
        self.max_attempts = max_attempts
        self._sleep_fn = sleep_fn

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
        url = f"{self.base_url}/audio/transcriptions"

        def _once():
            with httpx.Client(timeout=60) as client:
                return client.post(url, json=body, headers=headers)

        resp = request_with_stt_retry(
            _once,
            provider="openrouter",
            max_attempts=self.max_attempts,
            sleep_fn=self._sleep_fn,
            response_status=lambda r: r.status_code,
        )
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

    def __init__(self, api_key: str, model: str = "nova-3",
                 max_attempts: int = DEFAULT_STT_MAX_ATTEMPTS,
                 sleep_fn: Callable[[float], None] | None = None):
        self.api_key = api_key
        self.model = model
        self.max_attempts = max_attempts
        self._sleep_fn = sleep_fn

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
        content = wav_bytes(audio)

        def _once():
            with httpx.Client(timeout=60) as client:
                return client.post(
                    "https://api.deepgram.com/v1/listen",
                    params=params, content=content, headers=headers,
                )

        resp = request_with_stt_retry(
            _once,
            provider="deepgram",
            max_attempts=self.max_attempts,
            sleep_fn=self._sleep_fn,
            response_status=lambda r: r.status_code,
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
    backend = stt.get("backend", "openrouter")
    languages = validate_languages(stt.get("languages", []))
    if backend == "mlx":
        model = stt.get("mlx_model", DEFAULT_MLX_MODEL)
        supported, reason = local_model_support()
        if not supported:
            log.error("Local STT unavailable: %s", reason)
            return None
        if not local_model_is_downloaded(model):
            log.error("Local STT selected but model is not downloaded. Use "
                      "Settings → General → Download local (~1.5 GB).")
            return None
        return MlxWhisperBackend(
            model=model,
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
