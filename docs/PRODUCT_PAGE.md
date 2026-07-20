---
@purpose: "Source marketing copy for the golos product page: hero, features, privacy, FAQ, download, and roadmap blocks."
@why: "Keeps launch-site wording in one place mapped by the release checklist and site README."
@role: reference
@stability: evolving
@tags: [golos, product-page, marketing, copy, launch]
related_docs: [site/README.md, RELEASE_CHECKLIST.md, docs/PRODUCT.md, docs/ROADMAP.md]
---
# golos — product page copy

## Hero

# Talk to your Mac. It types.
**golos** (Ukrainian "voice") — push-to-talk dictation for macOS.
Hold **fn**, say what you mean, let go. golos transcribes, cleans up, and
types it into whatever app you're in — email, terminal, chat, IDE.

**Subheads:**

- **Faster than the keyboard you think you need.** Speak naturally; optional
  formatting handles punctuation, fillers, paragraphs, and lists.
- **Cloud-first, local when you want it.** Start with OpenRouter—no model
  download. Apple Silicon users can explicitly download on-device Whisper.
- **It knows where you're typing.** dictate sees the app, the window, even
  the file you're editing — so "attach main dot pi" becomes `main.py`.

**Hero CTAs:** direct architecture downloads (not the generic releases index):

- Apple Silicon DMG:
  `https://github.com/Dopomogai/golos/releases/download/v0.3.1/golos-0.3.1-apple-silicon.dmg`
- Intel DMG (cloud-only):
  `https://github.com/Dopomogai/golos/releases/download/v0.3.1/golos-0.3.1-intel.dmg`

Nav **Download** anchors to `#download`. Note: Intel is cloud-only; beta is
unsigned — first launch uses right-click → Open. Keep the GitHub release page
as a small details/fallback link only.

## Feature grid

| 🎙 Hold-to-talk | 🌊 Live waveform wings | 🧠 Two-stage AI |
|---|---|---|
| Hold fn, speak, release. fn+Space for hands-free lock mode. | Your voice ripples from the camera notch while you speak. Hidden when idle. | Cloud or optional local STT, then an optional LLM pass: fillers out, paragraphs and real lists in. |

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

- **OpenRouter first**: the default speech-to-text sends the recorded audio to
  the cloud model you select. It starts without a large model download.
- **Local is an explicit option**: Apple Silicon users can download the
  on-device MLX model once (~1.5 GB). In that mode, transcription audio stays
  on the Mac. Intel builds are cloud-only for STT.
- **What's shared, and when**: cloud STT sends audio for transcription. If
  formatting is enabled, the transcript plus permitted app context goes to
  the formatter; audio goes to the formatter only when its separate audio
  assistance toggle is enabled.
- **Fully local** means local MLX STT **and** formatting off **and** learning
  reviewer off — not “Format with LLM” off alone while cloud STT is still on.
- **Your data stays put**: history, dictionary, and learned corrections are
  plain JSONL/text files in `~/.golos`. Delete them whenever you like.
  Per-dictation WAV retention is a config-only switch (`keep_recordings`).

## Requirements

- macOS 13+
- Apple Silicon: OpenRouter plus optional on-device MLX
- Intel: cloud-only OpenRouter edition; no local MLX
- Optional ~1.5 GB disk only when the local model is explicitly downloaded
- Microphone, Input Monitoring, Accessibility permissions (guided setup)
- Optional: an OpenRouter API key for cloud models + LLM formatting

## Roadmap

Mirror [`docs/ROADMAP.md`](ROADMAP.md) as a `#roadmap` section (no dates):

- **Shipped now** — v0.3.1 Mac beta; Apple Silicon + Intel; cloud-first
  OpenRouter; optional local MLX on Apple Silicon; context separation;
  History/recovery; human-approved corrections.
- **Near term** — stability/compatibility hardening; Developer ID
  signing/notarization; launch at login; trustworthy update path; smoother
  diagnostics/recovery.
- **Next** — command mode; screenshot context; meeting/diarization; opt-in
  encrypted cross-device sync.
- **Pipeline** — Windows desktop and mobile. Mac is supported today;
  Windows/mobile need separate native work and have no announced date.

## FAQ

**Is my audio stored?**
By default, each dictation is retained locally as a WAV under
`~/.golos/recordings/` for benchmarking and troubleshooting. Turn off
`[audio] keep_recordings` in `~/.golos/config.toml` (config-only; no Settings
toggle) to stop archiving. Text history (raw + final, with the app it went
to) stays in a local JSONL file you own.

**What does it cost?**
golos is free and open-source. Local STT costs nothing forever. Cloud
transcription on OpenRouter is fractions of a cent per minute — benchmark
all 9 supported models on your own voice with the built-in
`python -m dictate.bench` harness.

**Why the permissions?**
Microphone to hear you, Input Monitoring to see the fn key globally,
Accessibility to paste into other apps and read context. No Accessibility =
dictation still transcribes, it just can't paste for you.

**Which platforms are available?**
macOS is supported today (Apple Silicon and Intel). Windows desktop and
mobile are in the pipeline; they require separate native work and have no
announced date.

**How does the dictionary learn?**
When you hand-edit something dictate inserted, it notices the diff and
suggests the correction (near-miss pairs only — no junk). Promote it to
your dictionary or corrections list with a single confirmation, or dismiss it forever.
Nothing is learned without your approval.

## Download

**golos for macOS** — choose architecture; each CTA is a **direct DMG**:

| Architecture | Asset |
|---|---|
| Apple Silicon | `…/releases/download/v0.3.1/golos-0.3.1-apple-silicon.dmg` |
| Intel (cloud-only) | `…/releases/download/v0.3.1/golos-0.3.1-intel.dmg` |

Free and open-source under MIT. The current beta is **unsigned**, so first
launch uses **right-click → Open**; do not describe it as signed, notarized,
or auto-updating. The generic GitHub release page is a **details/fallback**
link only (notes, checksums), not the primary download path. Nav Download
points at `#download`.

---
*Copy notes: hero animates the notch wings in a 6s loop; the raw/formatted
toggle is an interactive split-view; FAQ stays accordion. Before/after
examples are real history entries (anonymized). Roadmap section matches
docs/ROADMAP.md.*
