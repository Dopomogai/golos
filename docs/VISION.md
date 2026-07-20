---
@purpose: "Why golos exists, design principles, and status-aligned direction after the public v0.3.1 Mac beta."
@why: "Anchors product decisions so processing choices stay explicit, human-gated, and legible."
@role: reference
@stability: evolving
@tags: [golos, vision, principles, roadmap]
related_docs: [docs/PRODUCT.md, docs/TECH.md, docs/ROADMAP.md, RELEASE_CHECKLIST.md, README.md]
---
# golos — vision

## Why this exists

Wispr Flow proved that push-to-talk dictation, done well, is faster than
typing for a huge class of daily writing. But it's closed, subscription,
cloud-only, and its corrections model learns in ways you can't inspect.
golos is the same core interaction rebuilt as a small, readable,
inspectable Python app you can actually own: every transcription, every
correction, every byte that leaves your machine is visible in a log file or
a prompt you can print.

## Design principles

- **Cloud-first, local by choice.** OpenRouter is the quickest setup and needs
  no large model download. Apple Silicon users can explicitly download
  on-device Whisper. Formatting and audio forwarding remain separate controls.
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

## Status (public v0.3.1 beta)

golos is a **public Mac beta**. Apple Silicon and Intel DMGs ship today;
OpenRouter is the default path; optional local MLX is available on Apple
Silicon after an explicit download. Onboarding, History/recovery, context
separation, and human-approved learning are in the product.

What is **not** true of this beta: Developer ID signing, notarization, or
automatic updates. First launch still uses **right-click → Open**. Treat
signing, notarization, launch-at-login, and a trustworthy update path as
**near-term hardening**, not as pre-release gates that block the public repo.

For the honest public list (shipped / near term / next / pipeline), see
[`docs/ROADMAP.md`](ROADMAP.md). Summary:

### Near term

Stability and compatibility hardening, Developer ID signing and
notarization, launch at login, a trustworthy update path, smoother
diagnostics and recovery.

### Next

- **Command mode** — "computer, search for X" / "send that": intents, not
  just text. The guarded answer mode (`[formatting] answer_questions`) that
  ships today is the first step down this path.
- **Screenshot context** — a frame around the cursor as formatter context
  for apps where AX sees nothing (Electron, games, remote desktops).
- **Meeting / diarization mode** — long-form capture with speaker labels
  and a summary pass; different UX (recording window, not a bubble).
- **Opt-in encrypted cross-device sync** — dictionary, corrections, and
  dismissed suggestions across a user's machines; history stays local.

### Pipeline

**Mac is supported today.** Windows desktop and mobile are in the pipeline;
they need separate native work and have no announced date. One-stage
multimodal audio and emotion/style annotations remain deferred product
research — not platform-availability statements.
