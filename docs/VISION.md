---
@purpose: "Why golos exists, design principles, and the roadmap through public release and later phases."
@why: "Anchors product decisions so features stay local-first, human-gated, and legible."
@role: reference
@stability: evolving
@tags: [golos, vision, principles, roadmap]
related_docs: [docs/PRODUCT.md, docs/TECH.md, RELEASE_CHECKLIST.md, README.md]
---
# golos — vision

## Why this exists

Wispr Flow proved that push-to-talk dictation, done well, is faster than
typing for a huge class of daily writing. But it's closed, subscription,
cloud-only, and its corrections model learns in ways you can't inspect.
golos is the same core interaction rebuilt as a small, readable,
local-first Python app you can actually own: every transcription, every
correction, every byte that leaves your machine is visible in a log file or
a prompt you can print.

## Design principles

- **Local-first.** The app is fully useful with zero API keys: on-device
  Whisper, raw insertion, local history. Cloud is an upgrade, never a
  requirement — and every cloud feature has an off switch that means off.
- **Human-gated learning.** The app may *notice* that you fixed
  "wisper flow" to "Wispr Flow", but it never silently rewrites your
  dictionary. Suggestions are proposed; you promote or dismiss. Your
  vocabulary is yours, in two plain text files.
- **Context is the moat.** Transcription is a commodity; knowing *where*
  the text goes is the product. Frontmost app, window title, browser tab,
  workspace files, text around the cursor, text on screen — that's what
  turns "attach the file main dot pi" into `main.py` and a muttered comment
  into a proper citation. Every stage of the pipeline invests here.
- **Small and legible.** One process, ~15 modules, no framework. If a
  feature can't be explained in the README, it doesn't ship.

## Roadmap

### Must-haves before public release

- **py2app bundle** — a signed `.app` so permissions attach to the app,
  not the terminal; no Python install required.
- **Notarization** — Gatekeeper-clean distribution for non-technical users.
- **Onboarding wizard** — first-run flow that walks the three permission
  grants with live ✓/✗ detection (the checks already exist) and a test
  dictation.
- **Launch at login** — one checkbox; the single-instance flock already
  makes double-launches safe.

### Phase 2

- **Command mode** — "computer, search for X" / "send that": intents, not
  just text. The guarded answer mode (`[formatting] answer_questions`) that
  ships today is the first step down this path.
- **Cross-device sync with accounts** — dictionary, corrections, and
  dismissed suggestions synced across a user's machines; opt-in, end-to-end
  encrypted, history stays local.
- **Screenshot context** — a frame around the cursor as formatter context
  for apps where AX sees nothing (Electron, games, remote desktops).
- **Meeting / diarization mode** — long-form capture with speaker labels
  and a summary pass; different UX (recording window, not a bubble).

### Explicitly parked

- **Windows/Linux ports** — the entire value proposition hangs off macOS
  APIs (AX, CGEvent, NSPanel); a port is a rewrite, not a port.
- **One-stage multimodal audio** (LLM straight from audio) — kills the
  local-first option and vocabulary biasing today; revisit when local
  audio-LLMs mature.
- **Emotion/style annotations** — tone inference from voice is creepy by
  default and high-effort; punctuation + context already covers the 95%
  case.
