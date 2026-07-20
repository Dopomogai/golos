"""STT benchmark harness — compare models on your own audio.

Usage:
  python -m dictate.bench record NAME        record mic until Enter -> samples/NAME.wav
                                             (+ draft samples/NAME.txt to edit)
  python -m dictate.bench run [--models a,b,c] [--samples x,y]
                              [--json out.json] [--verbose]

samples/ holds NAME.wav (16 kHz mono) + NAME.txt (reference transcript).
Dependency-free: uses the app's existing venv and backend classes.
"""

import argparse
import difflib
import json
import logging
import string
import sys
import time
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
COST_NOTE = ("note: each cloud transcription costs a fraction of a cent — "
             "a full run over the 9 curated models is on the order of cents.")


# ---------------------------------------------------------------------------
# WER


def _norm_words(text: str) -> list[str]:
    """Lowercase + strip punctuation for WER tokenization."""
    table = str.maketrans("", "", string.punctuation + "…“”‘’—–")
    return text.lower().translate(table).split()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate, difflib-based: (S+D+I)/N on normalized word lists."""
    ref = _norm_words(reference)
    hyp = _norm_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    s = d = i = 0
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            s += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            d += i2 - i1
        elif tag == "insert":
            i += j2 - j1
    return (s + d + i) / len(ref)


# ---------------------------------------------------------------------------
# audio helpers


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getframerate() != SAMPLE_RATE:
            raise ValueError(f"{path.name}: need 16 kHz mono wav "
                             f"(got {wf.getframerate()} Hz x {wf.getnchannels()}ch)")
        return (np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
                .astype(np.float32) / 32768.0)


def find_samples(only: list[str] | None) -> list[tuple[str, Path, Path]]:
    pairs = []
    for wav in sorted(SAMPLES_DIR.glob("*.wav")):
        txt = wav.with_suffix(".txt")
        if only and wav.stem not in only:
            continue
        if not txt.exists():
            log.warning("Skipping %s: no %s.txt reference", wav.name, wav.stem)
            continue
        pairs.append((wav.stem, wav, txt))
    return pairs


# ---------------------------------------------------------------------------
# record


def cmd_record(name: str) -> int:
    from dictate.stt import write_wav

    SAMPLES_DIR.mkdir(exist_ok=True)
    chunks = []

    import sounddevice as sd

    def callback(indata, frames, time_info, status):
        chunks.append(indata[:, 0].copy())

    print(f"Recording samples/{name}.wav — speak, then press Enter to stop.")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        callback=callback):
        input()
    if not chunks:
        print("Nothing recorded.")
        return 1
    audio = np.concatenate(chunks).astype(np.float32)
    wav_path = SAMPLES_DIR / f"{name}.wav"
    write_wav(str(wav_path), audio)
    print(f"Wrote {wav_path} ({len(audio) / SAMPLE_RATE:.1f}s)")

    # Draft transcript with the default OpenRouter model, if a key exists.
    draft = ""
    try:
        from dictate.config import load_config
        from dictate.openrouter import DEFAULT_STT_MODEL, get_api_key
        from dictate.stt import OpenRouterSTTBackend
        cfg = load_config()
        key = get_api_key(cfg)
        if key:
            model = cfg.get("stt", {}).get("openrouter", {}) \
                .get("model", DEFAULT_STT_MODEL)
            print(f"Drafting transcript with {model}…")
            draft = OpenRouterSTTBackend(
                "https://openrouter.ai/api/v1", key, model).transcribe(audio)
        else:
            print("No OpenRouter key — leaving the reference file empty.")
    except Exception as e:
        print(f"Draft transcription failed ({e}); edit the file yourself.")

    txt_path = SAMPLES_DIR / f"{name}.txt"
    if not txt_path.exists():
        txt_path.write_text(draft + "\n", encoding="utf-8")
    print(f"Reference transcript -> {txt_path}")
    print(f"Draft: {draft!r}")
    print("Edit the .txt to match what you actually said, then: "
          "python -m dictate.bench run")
    return 0


# ---------------------------------------------------------------------------
# run


def _build_backends(model_ids: list[str], cfg: dict) -> dict:
    """One backend instance per model id; 'mlx' maps to the local backend."""
    from dictate.openrouter import get_api_key
    from dictate.stt import MlxWhisperBackend, OpenRouterSTTBackend

    backends = {}
    key = get_api_key(cfg)
    for mid in model_ids:
        if mid == "mlx":
            backends[mid] = MlxWhisperBackend(
                cfg.get("stt", {}).get(
                    "mlx_model", "mlx-community/whisper-large-v3-turbo"))
        else:
            if not key:
                backends[mid] = RuntimeError("no OpenRouter API key")
            else:
                backends[mid] = OpenRouterSTTBackend(
                    "https://openrouter.ai/api/v1", key, mid)
    return backends


def cmd_run(args) -> int:
    from dictate.config import load_config
    from dictate.openrouter import TRANSCRIPTION_MODELS

    cfg = load_config()
    model_ids = args.models.split(",") if args.models \
        else ["mlx"] + list(TRANSCRIPTION_MODELS)
    samples = find_samples(args.samples.split(",") if args.samples else None)
    if not samples:
        print(f"No samples found in {SAMPLES_DIR} "
              "(NAME.wav + NAME.txt). Record one: python -m dictate.bench record NAME")
        return 1

    print(COST_NOTE)
    print(f"{len(samples)} sample(s) x {len(model_ids)} model(s)\n")
    backends = _build_backends(model_ids, cfg)
    audio_cache = {name: load_wav(wav) for name, wav, _ in samples}
    refs = {name: txt.read_text(encoding="utf-8") for name, _, txt in samples}

    results = []  # (model, avg_wer, avg_latency, per_sample, error)
    for mid in model_ids:
        backend = backends[mid]
        if isinstance(backend, Exception):
            results.append((mid, None, None, {}, f"ERROR: {backend}"))
            continue
        per_sample, wers, latencies = {}, [], []
        for name, _, _ in samples:
            t0 = time.time()
            try:
                text = backend.transcribe(audio_cache[name])
            except Exception as e:
                results.append((mid, None, None, {}, f"ERROR: {e}"))
                break
            dt = time.time() - t0
            w = wer(refs[name], text)
            per_sample[name] = w
            wers.append(w)
            latencies.append(dt)
            if args.verbose:
                print(f"  [{mid} / {name}] {dt:.1f}s wer={w:.2f}\n"
                      f"    ref: {refs[name].strip()}\n"
                      f"    hyp: {text}")
        else:
            results.append((mid, sum(wers) / len(wers),
                            sum(latencies) / len(latencies), per_sample, None))

    # table, sorted by WER then latency; errors last
    ok = [r for r in results if r[4] is None]
    bad = [r for r in results if r[4] is not None]
    ok.sort(key=lambda r: (r[1], r[2]))
    sample_names = [s[0] for s in samples]
    header = f"{'model':42} {'avg WER':>8} {'avg lat':>8} " + \
        " ".join(f"{n[:10]:>10}" for n in sample_names)
    print("\n" + header)
    print("-" * len(header))
    for mid, avg_w, avg_l, per, err in ok + bad:
        if err:
            print(f"{mid:42} {err}")
        else:
            cols = " ".join(f"{per.get(n, float('nan')):>10.2f}"
                            for n in sample_names)
            print(f"{mid:42} {avg_w:>8.2f} {avg_l:>7.1f}s {cols}")

    if args.json:
        payload = [{"model": mid, "avg_wer": w, "avg_latency": l,
                    "per_sample": per, "error": err}
                   for mid, w, l, per, err in results]
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dictate.bench",
                                     description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_rec = sub.add_parser("record", help="record a sample from the mic")
    p_rec.add_argument("name")
    p_run = sub.add_parser("run", help="benchmark models over samples/")
    p_run.add_argument("--models", help="comma-separated ids (default: mlx + 9 curated)")
    p_run.add_argument("--samples", help="comma-separated sample names")
    p_run.add_argument("--json", help="write results to this path")
    p_run.add_argument("--verbose", action="store_true",
                       help="print every transcript")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    if args.cmd == "record":
        return cmd_record(args.name)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
