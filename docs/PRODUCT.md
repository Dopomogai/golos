---
@purpose: "Product-facing overview of golos features, install path, permissions, and first-run usage."
@why: "Separates the product story from architecture detail and marketing launch copy."
@role: reference
@stability: accepted
@tags: [golos, product, features, install]
related_docs: [docs/GUIDE.md, docs/VISION.md, docs/PRODUCT_PAGE.md, README.md]
---
# golos — push-to-talk dictation for macOS

**golos** is a small macOS menu-bar app that turns your voice into text
anywhere a cursor can blink. Hold a key, talk, release — the text appears in
whatever app you're in. It's a personal, open-source take on Wispr Flow:
local-first, hackable Python, no account, no subscription.

## Key features

- **Hold-to-talk** — hold your key (`fn` by default — also Right ⌥, Right
  ⌘, or F5), speak, release. `key`+Space locks recording hands-free; a
  single press stops it. `Esc` cancels mid-recording.
- **Notch wings** — while you speak, a fluid red→orange waveform ripples
  outward from both edges of the camera notch, drawn over the menu bar. It
  never blocks your menus (the panel is click-through). On non-notched
  machines a draggable corner pill shows the same. Idle = no bubble at all.
- **Two-stage pipeline** — (1) speech-to-text with vocabulary biasing from
  your personal dictionary, (2) an optional LLM pass that removes fillers,
  fixes punctuation, breaks paragraphs at topic shifts, turns enumerations
  into real lists, applies your corrections, and adapts tone to the app
  you're in.
- **App context** — the formatter can see what you see: current browser tab
  (Safari/Chrome/Brave/Edge/Arc), VS Code workspace files, Finder selection,
  text before the cursor, and the visible text on screen — so spoken
  filenames become real paths and comments on what you're reading become
  proper citations.
- **Self-improving dictionary** — fix an inserted text by hand and golos
  notices the edit, proposes the correction, and lets you promote it into
  your dictionary or corrections list with a single confirmation. A live edit watcher
  can even offer it within seconds as a click-to-keep pill. Nothing is
  learned without your approval.
- **Model choice** — local on-device Whisper (mlx) by default, or 9 curated
  cloud transcription models via OpenRouter. A built-in benchmark harness
  (`python -m dictate.bench`) measures WER and latency on *your* voice.
- **History** — every dictation is logged locally (raw + final + context) in
  `history.jsonl`, browsable in Settings. The raw audio of each dictation is
  archived too (`~/.golos/recordings/`, off switch included).

## Install

Requirements: Apple Silicon Mac, macOS 13+, Python ≥ 3.11.

```sh
cd ~/dictate
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Permissions (one-time)

macOS gates everything a dictation app does. Grant your terminal (or the
bundled app, later) in **System Settings → Privacy & Security**:

1. **Microphone** — audio capture.
2. **Input Monitoring** — the global `fn` hotkey and the event tap that
   swallows `fn`+Space.
3. **Accessibility** — pasting into other apps, reading window titles,
   cursor/visible-text context, and the learning loop.

Also set **System Settings → Keyboard → "Press 🌐/fn key to" → Do Nothing**,
or macOS steals the fn key for its own action. Restart the terminal after
granting. The app checks all three at startup and tells you exactly what's
missing (menu-bar icon → Permissions shows live ✓/✗).

## First run

```sh
cd ~/dictate
./dictate.sh            # start   (also: quit | restart)
```

1. Hold `fn`, say "hello this is a test", release — text lands at the cursor.
2. Without any API key everything works offline (local Whisper, raw insert).
3. Add an OpenRouter key in Settings → General for cloud STT and the LLM
   formatting pass. A green "✓ inserted" flash confirms each paste.

## Speed knobs

Beyond the two modes below: **Fast mode** skips the LLM for short dictations
(instant), **answer mode** lets the formatter answer obvious questions from
context, and **send_audio** lets the formatter listen to the original
recording to recover garbled transcription. Separately, the optional
**learning reviewer** (Settings → Learning, off by default) can listen
to a retained recording when proposing STT fixes after you edit — still
human-gated, never auto-applied.

## Two modes

| | **Raw mode** | **Formatted mode** (default) |
|---|---|---|
| Stage 2 | off | LLM cleanup + structure + context |
| Speed | fastest | +1–3 s |
| Privacy | nothing leaves the machine | transcript + context go to the formatter API |

Toggle with the **Format with LLM** checkbox in Settings → General
(`[formatting] enabled`). You can also keep formatting on but disable
context providers with `[context] enabled = false`.

## Troubleshooting

- **Nothing is pasted** — Accessibility permission missing. Menu-bar icon →
  Permissions shows what's red; "Test insertion" pastes a probe string.
- **fn does nothing** — Input Monitoring missing, or "Press fn key to" isn't
  set to Do Nothing. Check the startup log.
- **"golos is already running (pid N)"** — a previous instance is alive
  (maybe suspended with Ctrl+Z). `./dictate.sh quit` or `./dictate.sh restart`.
- **No bubble** — that's idle by design. It appears only while recording /
  processing / confirming.
- **Weird suggestions in Settings → History** — dismiss them; the learning
  gates only propose near-miss corrections, but dismissal is permanent.
  If the optional learning reviewer is on, turn off
  `[learning] reviewer_enabled` or lower send-audio for stricter local-only
  diffs.
- **Logs** — the app logs verbosely to stdout; `[formatting] debug = true`
  logs the complete prompt sent to the formatter.
