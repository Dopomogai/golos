"""Audio recording: 16 kHz mono float32 via sounddevice.

THREADING RULES (learned from a CoreAudio deadlock in production):
- start() runs on the main thread — PortAudio start is fast and recording must
  begin immediately after the hotkey press; this is the tolerated exception.
- stop()/abort() must NEVER run on the main thread: stream shutdown blocks on
  CoreAudio's IO-context mutex while the IO thread can end up waiting on the
  app main thread — a classic two-lock deadlock. Only worker threads may call
  them. Both are idempotent and guarded by _stop_lock so two paths can't race
  the same stream.
"""

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class Recorder:
    """Start/stop microphone capture into a numpy buffer.

    on_level(rms: float), if given, is called from the audio thread for every
    captured block with its RMS level (drives the bubble waveform).
    """

    def __init__(self, device: int | None = None, on_level=None):
        self._device = device or None
        self._on_level = on_level
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stop_lock = threading.Lock()

    def start(self) -> None:
        """Open the PortAudio input stream and begin capturing.

        May run on the main thread (hotkey press path): stream start is fast.
        Idempotent under _stop_lock — a second start while active is ignored.
        """
        with self._stop_lock:
            if self._stream is not None:
                log.warning("Recorder.start() while already recording; ignoring.")
                return
            with self._lock:
                self._chunks = []
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self._device,
                callback=self._callback,
            )
            self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        # PortAudio IO thread: copy out of the shared buffer, then optional
        # level callback. Never raise — a UI exception must not kill capture.
        block = indata[:, 0]
        with self._lock:
            self._chunks.append(block.copy())
        if self._on_level is not None:
            try:
                self._on_level(float(np.sqrt(np.mean(block ** 2))))
            except Exception:
                pass  # never let UI break the audio stream

    def _drain(self) -> np.ndarray:
        """Take ownership of buffered chunks under _lock (caller holds _stop_lock)."""
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks).astype(np.float32)
            self._chunks = []
        return audio

    def stop(self) -> np.ndarray:
        """Stop recording and return the captured audio (float32, 16 kHz).

        WORKER THREADS ONLY — see module docstring. Idempotent: stopping a
        non-active stream just drains the buffer.
        """
        with self._stop_lock:
            if self._stream is None:
                log.info("Recorder.stop() with no active stream; draining only.")
                return self._drain()
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
        return self._drain()

    def abort(self) -> None:
        """Abort the stream without waiting for callback completion (discards
        buffered audio). Less deadlock surface than stop() — use for cancels.
        WORKER THREADS ONLY. Idempotent."""
        with self._stop_lock:
            if self._stream is None:
                return
            try:
                self._stream.abort()
            except Exception as e:
                log.info("Recorder.abort() failed (%s); closing anyway.", e)
            finally:
                self._stream.close()
                self._stream = None
            with self._lock:
                self._chunks = []
