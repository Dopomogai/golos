# golos — product page copy

## Hero

# Talk to your Mac. It types.
**golos** (Ukrainian "voice") — push-to-talk dictation for macOS.
Hold **fn**, say what you mean, let go. golos transcribes, cleans up, and
types it into whatever app you're in — email, terminal, chat, IDE.

**Subheads:**

- **Faster than the keyboard you think you need.** 2–3× speaking speed, zero
  typos, punctuation handled.
- **Private by default.** On-device Whisper on Apple Silicon. No account, no
  audio stored, no cloud required.
- **It knows where you're typing.** dictate sees the app, the window, even
  the file you're editing — so "attach main dot pi" becomes `main.py`.

## Feature grid

| 🎙 Hold-to-talk | 🌊 Live waveform wings | 🧠 Two-stage AI |
|---|---|---|
| Hold fn, speak, release. fn+Space for hands-free lock mode. | Your voice ripples from the camera notch while you speak. Hidden when idle. | Local STT first, then an LLM pass: fillers out, paragraphs and real lists in. |

| 📚 Learns your words | 📎 Real citations | ⚡ Two speeds |
|---|---|---|
| Fix a transcription once — dictate proposes the correction, you approve. | Commenting on what's on screen? It quotes the exact line, then your take. | Raw insert for speed, formatted mode for polish. One checkbox. |

## Raw vs. formatted — a real example

You say (raw transcript):
> "Hey hey hey, checking how you work."

**Raw mode inserts exactly that.**

**Formatted mode inserts:**
> "Checking how you work."

And when you ramble a request:
> "Can you please study a bit more on how the widget works that talks like the concierge widget? Because I believe there is…"

Formatted mode delivers one clean sentence:
> "Please study how the widget works that talks like the concierge widget, as I believe there is a lot to learn there."

Same voice. Your choice per machine, per moment.

## Privacy

- **Local-first**: the default speech-to-text runs entirely on your Mac
  (mlx-whisper on Apple Silicon). No key, no cloud, no problem.
- **What's shared, and when**: only if you enable the OpenRouter formatting
  pass does the transcript plus app context (window title, current tab,
  text near your cursor) go to the API you chose. One checkbox turns it all
  off. Audio itself leaves only if you pick a cloud STT backend.
- **Your data stays put**: history, dictionary, and learned corrections are
  plain JSONL/text files in `~/.golos`. Delete them whenever you like.

## Requirements

- macOS 13+ on Apple Silicon
- ~1.5 GB disk for the local Whisper model (downloaded once)
- Microphone, Input Monitoring, Accessibility permissions (guided setup)
- Optional: an OpenRouter API key for cloud models + LLM formatting

## FAQ

**Is my audio stored?**
No. Audio is transcribed in memory and discarded. The text history
(raw + final, with the app it went to) stays in a local JSONL file you own.

**What does it cost?**
golos is free and open-source. Local STT costs nothing forever. Cloud
transcription on OpenRouter is fractions of a cent per minute — benchmark
all 9 supported models on your own voice with the built-in
`python -m dictate.bench` harness.

**Why the permissions?**
Microphone to hear you, Input Monitoring to see the fn key globally,
Accessibility to paste into other apps and read context. No Accessibility =
dictation still transcribes, it just can't paste for you.

**Windows?**
Not planned — golos is built on macOS-native APIs (Accessibility,
CGEvent, the notch). It's a Mac app through and through.

**How does the dictionary learn?**
When you hand-edit something dictate inserted, it notices the diff and
suggests the correction (near-miss pairs only — no junk). Promote it to
your dictionary or corrections list with one click, or dismiss it forever.
Nothing is learned without your approval.

## Download

**golos for macOS** — DMG, signed & notarized.
Free for personal use. Source available.

---
*Copy notes: hero animates the notch wings in a 6s loop; the raw/formatted
toggle is an interactive split-view; FAQ stays accordion. Before/after
examples are real history entries (anonymized).*
