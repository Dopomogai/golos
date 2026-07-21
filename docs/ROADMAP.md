---
@purpose: "Honest public roadmap for golos: shipped status, near-term hardening, next product layers, and platform pipeline."
@why: "Keeps marketing and docs aligned on what exists today without dates, promises, or false parked language."
@role: reference
@stability: evolving
@tags: [golos, roadmap, platforms, beta, public]
related_docs: [docs/VISION.md, docs/PRODUCT_PAGE.md, RELEASE_CHECKLIST.md, README.md, site/index.html]
---
# golos — public roadmap

Direction only. No ship dates, no promises.

## Shipped now

Public **v0.3.2 Mac beta** (macOS 13+):

- Separate **Apple Silicon** (cloud + optional local MLX) and **Intel**
  (cloud-only OpenRouter; no MLX) DMGs
- **Cloud-first OpenRouter** transcription by default
- **Optional local MLX** speech-to-text on Apple Silicon only (explicit download)
- **Context separation** (app / window / field / visible text roles)
- **History and recovery** (retry, copy, retained audio when kept)
- **Human-approved corrections** (suggestions and live cues never auto-promote)

The beta is **unsigned**. First launch uses **right-click → Open**. Builds are
not signed or notarized yet, and there is no automatic update install path.

## Near term

Product and distribution hardening on the Mac path already shipping:

- Stability and compatibility hardening
- Developer ID signing and notarization
- Launch at login
- A trustworthy update path (beyond opening the release page by hand)
- Smoother diagnostics and recovery

## Next

Deeper product layers after the beta is trustworthy day-to-day:

- **Command mode** — intents beyond plain text insert
- **Screenshot context** — formatter context when Accessibility sees little
- **Meeting / diarization** — long-form capture with speaker labels and summary
- **Opt-in encrypted cross-device sync** — dictionary and corrections; history stays local

## Pipeline

**Mac is supported today.**

**Windows desktop** and **mobile** are in the pipeline. They require separate
native work (not a thin recompile of the macOS app) and have **no announced
date**.
