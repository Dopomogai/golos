---
@purpose: "Ordered checklist of remaining steps from ready code/docs to a public golos release."
@why: "Prevents shipping without signing, notarization, site mapping, demo, or other open launch work."
@role: reference
@stability: evolving
@tags: [golos, release, checklist, notarization, launch]
related_docs: [docs/PRODUCT_PAGE.md, site/README.md, docs/VISION.md, README.md]
---
# golos — release checklist

Source is public at <https://github.com/Dopomogai/golos>. v0.3.0 is public;
v0.3.1 is the first polish update. This is the repeatable patch-release path;
signing/notarization remains a separate founder-owned gate.

## 1. Repository and release branch

The repository and initial public push are complete. For v0.3.1, work on a
feature branch until both architecture builds and tests pass. Never commit
`~/.golos`, a populated API key, build output, or personal JSONL/WAV data.

```sh
cd ~/dictate
git switch -c release/v0.3.1
git status --short
rg -n 'sk-or-v1-|api_key = "[^" ]+' --glob '!dist/**' --glob '!build/**' .
./.venv/bin/pytest -q
```

## 2. Build and verify both editions

Apple Silicon includes the MLX runtime but downloads the ~1.5 GB weights only
after the user clicks **Download local**. Intel intentionally excludes MLX and
uses OpenRouter only.

```sh
# Apple Silicon: cloud + optional local
./build_app.sh
./make_dmg.sh 0.3.1-apple-silicon
file dist/golos.app/Contents/MacOS/golos

# Intel: cloud-only (requires an x86_64 Python and Rosetta on the build Mac)
./build_intel_app.sh
./make_dmg.sh 0.3.1-intel
file dist/golos.app/Contents/MacOS/golos
```

Before release, preserve both DMGs, restore the Apple Silicon app as
`dist/golos.app`, and verify on clean user profiles:

- no Hugging Face/model download during OpenRouter onboarding or first cloud dictation;
- `Contents/Resources/config.toml` exists and seeds `~/.golos/config.toml`;
- Apple Silicon Settings shows an explicit local download button;
- Intel Settings disables local MLX with a clear reason;
- hold/release, immediate repeat, fn+Space lock, Esc cancel, processing/success
  animations, insertion, and correction approval all work.

## 3. Publish v0.3.1

```sh
git add -A
git status --short
git commit -m "golos 0.3.1 — context, learning, and visual polish"
git push -u origin release/v0.3.1
# Merge after review, then tag/release from main.
gh release create v0.3.1 \
  dist/golos-0.3.1-apple-silicon.dmg \
  dist/golos-0.3.1-intel.dmg \
  --repo Dopomogai/golos --title "golos 0.3.1" --generate-notes
```

The release notes must say: macOS 13+; Intel is cloud-only; Apple Silicon can
optionally download local STT; beta DMGs are unsigned and use right-click →
Open. Publish SHA-256 checksums with the assets.

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

## 5. Apple Developer ID signing + notarization

Unsigned builds today (right-click → Open works, but it's a friction point).
With a paid Apple Developer account:

```sh
# sign the app (hardened runtime + entitlements for mic/events if prompted)
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Andrii Solovei (TEAMID)" dist/golos.app
codesign --verify --deep --strict --verbose=2 dist/golos.app

# package + notarize each architecture build
./make_dmg.sh 0.3.1-apple-silicon
codesign --sign "Developer ID Application: Andrii Solovei (TEAMID)" \
  dist/golos-0.3.1-apple-silicon.dmg
xcrun notarytool submit dist/golos-0.3.1-apple-silicon.dmg \
  --apple-id "APPLE_ID_EMAIL" --team-id "TEAMID" --password "APP_SPECIFIC_PW" \
  --wait
xcrun stapler staple dist/golos-0.3.1-apple-silicon.dmg
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
