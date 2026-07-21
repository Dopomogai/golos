---
@purpose: "Ordered checklist of remaining steps from ready code/docs to a public golos release."
@why: "Prevents shipping without signing, notarization, site mapping, demo, or other open launch work."
@role: reference
@stability: evolving
@tags: [golos, release, checklist, notarization, launch]
related_docs: [docs/PRODUCT_PAGE.md, site/README.md, docs/VISION.md, README.md]
---
# golos — release checklist

Source is public at <https://github.com/Dopomogai/golos>. v0.3.0 and v0.3.1
are public; **v0.3.2** is the accessibility-preflight / diagnostics /
visual-panel hardening beta. This is the repeatable patch-release path;
**signing and notarization remain founder-gated** — do not run codesign,
notarytool, or staple unless the founder explicitly owns that step.

## 1. Repository and release branch

The repository and initial public push are complete. For v0.3.2, work on a
feature branch until both architecture builds and tests pass. Never commit
`~/.golos`, a populated API key, build output, or personal JSONL/WAV data.

```sh
cd ~/dictate
git switch -c release/v0.3.2
git status --short
rg -n 'sk-or-v1-|api_key = "[^" ]+' --glob '!dist/**' --glob '!build/**' .
./.venv/bin/pytest -q
# Site + help-center link/content guards (after version bump):
./.venv/bin/pytest -q tests/test_site.py tests/test_help_center.py
```

## 2. Build and verify both editions

Apple Silicon includes OpenRouter plus optional MLX download (~1.5 GB weights
only after the user clicks **Download local**). Intel is cloud-only
(OpenRouter; no local MLX). Beta remains **unsigned / not notarized**.

```sh
# Apple Silicon: cloud + optional local
./build_app.sh
./make_dmg.sh 0.3.2-apple-silicon
file dist/golos.app/Contents/MacOS/golos
# expect: dist/golos-0.3.2-apple-silicon.dmg

# Intel: cloud-only (requires an x86_64 Python and Rosetta on the build Mac)
./build_intel_app.sh
./make_dmg.sh 0.3.2-intel
file dist/golos.app/Contents/MacOS/golos
# expect: dist/golos-0.3.2-intel.dmg
```

`make_dmg.sh` builds a Finder drag-to-install window (dark Golos background,
golos.app → Applications). Spot-check the mounted DMG visually before publish.

Before release, preserve both DMGs, restore the Apple Silicon app as
`dist/golos.app`, and verify on clean user profiles:

- no Hugging Face/model download during OpenRouter onboarding or first cloud dictation;
- `Contents/Resources/config.toml` exists and seeds `~/.golos/config.toml`;
- Apple Silicon Settings shows an explicit local download button;
- Intel Settings disables local MLX with a clear reason;
- hold/release, immediate repeat, fn+Space lock, Esc cancel, processing/success
  animations, insertion, and correction approval all work;
- **Accessibility preflight**: with Accessibility denied, insert aborts before
  posting, History keeps the result, and the bubble warns (no false green success);
- **Export Diagnostics…**: menu creates a local redacted zip under a user-chosen
  path; bundle stays local until the user shares it; no keys/audio/transcript/
  prompt/context text; rotating logs under `~/.golos/logs/`;
- **visual-panel self-healing**: rapid repeat and success→recording do not leave
  the strip permanently missing (do not claim every UI glitch is gone);
- replaced unsigned app may need the three permissions regranted; after granting
  **Input Monitoring**, relaunch golos so the event tap can install.

## 3. Publish v0.3.2

```sh
git add -A
git status --short
git commit -m "golos 0.3.2 — accessibility preflight, diagnostics, visual harden"
git push -u origin release/v0.3.2
# Merge after review, then tag/release from main.
gh release create v0.3.2 \
  dist/golos-0.3.2-apple-silicon.dmg \
  dist/golos-0.3.2-intel.dmg \
  --repo Dopomogai/golos --title "golos 0.3.2" --generate-notes
```

The release notes must say: macOS 13+; Intel is cloud-only; Apple Silicon can
optionally download local STT; beta DMGs are **unsigned and not notarized**
and use right-click → Open; Accessibility insertion preflight; local rotating
diagnostics + privacy-sanitized **Export Diagnostics…**. **Do not invent
checksum values** — the track lead publishes verified SHA-256 hashes after
both architecture builds are final.

## 4. Website product page

Source copy: `docs/PRODUCT_PAGE.md`. Mapping to site blocks:

| Site block | PRODUCT_PAGE.md section |
|---|---|
| Hero (tagline + 3 subheads) | "Hero" + the 6s wings loop |
| Feature grid (6 cards) | "Feature grid" |
| Before/after toggle | "Raw vs. formatted — a real example" (interactive split view) |
| Privacy section | "Privacy" |
| Requirements strip | "Requirements" |
| FAQ accordion | "FAQ" (5 questions) |
| Download CTA | "Download" (latest release page with architecture choice) |

The implementation is in `Dopomogai/dopomogai-web#26`. Grant
`dopomogai-agent` repository **Write** access (not Admin) to update/merge it,
then verify `/golos` on desktop/mobile and every download/source link live.

## 5. Apple Developer ID signing + notarization (founder-gated)

**Do not run this section unless the founder explicitly owns signing.**
Public v0.3.2 ships unsigned (right-click → Open). With a paid Apple Developer
account and founder approval:

```sh
# sign the app (hardened runtime + entitlements for mic/events if prompted)
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Andrii Solovei (TEAMID)" dist/golos.app
codesign --verify --deep --strict --verbose=2 dist/golos.app

# package + notarize each architecture build
./make_dmg.sh 0.3.2-apple-silicon
codesign --sign "Developer ID Application: Andrii Solovei (TEAMID)" \
  dist/golos-0.3.2-apple-silicon.dmg
xcrun notarytool submit dist/golos-0.3.2-apple-silicon.dmg \
  --apple-id "APPLE_ID_EMAIL" --team-id "TEAMID" --password "APP_SPECIFIC_PW" \
  --wait
xcrun stapler staple dist/golos-0.3.2-apple-silicon.dmg
```

Verify a fresh machine: `spctl -a -t exec -vv dist/golos.app` → "accepted".

## 6. Update channel and launch at login

v0.3 uses GitHub Releases as the canonical update channel. The in-app update
action opens the latest release; installation is manual while builds are
unsigned. A signed Sparkle feed with automatic replacement is a post-signing
step—it should not be added to an unsigned build.

Launch at login remains open:

One checkbox in Settings → General ("Launch golos at login") via
`SMAppService.loginItem` (pyobjc-framework-ServiceManagement, register the
bundle). The single-instance flock already makes double-launches safe.
Everything else on the old must-have list is done: py2app bundle, onboarding
wizard, this checklist.

## 7. Founder video recording (long master → edited launch set)

The production source of truth is [`docs/VIDEO_PRODUCTION.md`](docs/VIDEO_PRODUCTION.md).
Record one natural 20–30 minute master, then hand it to the editing agent for:

- one approximately twelve-minute 16:9 founder story and product walkthrough;
- four distinct 45–60 second 9:16 cuts;
- captions, thumbnails, and a timestamped transcript.

The old 90-second flow below remains a compact practice pass and a fallback
shot list. It is not the primary launch format.

Pre-recording setup:
- Fresh `~/.golos/history.jsonl` (or curate out anything personal), clear
  Suggestions you don't want on camera, tidy the menu bar.
- Settings pre-check: backend openrouter + nova-3, formatting on,
  `[bubble] sensitivity ~1.3` so the waveform reads on video.
- One terminal window + one Notes window, large font.

Flow:
1. (5 s) Menu-bar chakra icon → the app is just there.
2. (15 s) Hold fn in Notes: wings ripple from the notch; release → blue
   processing shimmer → green "✓ inserted" hill.
3. (15 s) Dictate a numbered list ("first … second … third …") — it lands
   as a real list (formatting pass).
4. (15 s) Comment on visible text: "about the second point, that's wrong"
   → `> quote` citation appears.
5. (10 s) Fix one word by hand → edit-cue pill `wrong → right ✓?` → click
   to keep → green "✓ learned".
6. (15 s) Settings tour: General (backend, hold key, sensitivity), Prompt
   (toggles + template), Dictionary tables, History + Suggestions.
7. (10 s) Onboarding wizard (Welcome / Setup…) — sidebar, radio cards,
   test pad lighting on key hold.
8. (5 s) `./dictate.sh quit` from a terminal; done.
