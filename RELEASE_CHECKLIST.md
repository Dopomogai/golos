# golos — release checklist

Ordered, from "today" to "public". Status: code and docs are ready; the
items below are what remain.

## 1. Git init + first push to GitHub

Repo is NOT initialized yet (deliberate — do this together). The tree is
scan-clean: no secrets (`config.toml` ships with an empty `api_key`), no
personal JSONL, `.gitignore` covers `.venv/`, `build/`, `dist/`,
`.dictate.lock`, `__pycache__/`, `*.egg-info/`.

```sh
cd ~/dictate
git init -b main
git add -A
git status            # eyeball: no .venv, no dist, no config with a key
git commit -m "golos 0.2.0 — initial import"
gh repo create golos --public --source=. --push
```

## 2. Website product page

Source copy: `docs/PRODUCT_PAGE.md`. Mapping to site blocks:

| Site block | PRODUCT_PAGE.md section |
|---|---|
| Hero (tagline + 3 subheads) | "Hero" + the 6s wings loop |
| Feature grid (6 cards) | "Feature grid" |
| Before/after toggle | "Raw vs. formatted — a real example" (interactive split view) |
| Privacy section | "Privacy" |
| Requirements strip | "Requirements" |
| FAQ accordion | "FAQ" (5 questions) |
| Download CTA | "Download" (DMG link once notarized) |

## 3. Apple Developer ID signing + notarization

Unsigned builds today (right-click → Open works, but it's a friction point).
With a paid Apple Developer account:

```sh
# sign the app (hardened runtime + entitlements for mic/events if prompted)
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Andrii Solovei (TEAMID)" dist/golos.app
codesign --verify --deep --strict --verbose=2 dist/golos.app

# package + notarize
./make_dmg.sh 0.2.0
codesign --sign "Developer ID Application: Andrii Solovei (TEAMID)" \
  dist/golos-0.2.0.dmg
xcrun notarytool submit dist/golos-0.2.0.dmg \
  --apple-id "APPLE_ID_EMAIL" --team-id "TEAMID" --password "APP_SPECIFIC_PW" \
  --wait
xcrun stapler staple dist/golos-0.2.0.dmg
```

Verify a fresh machine: `spctl -a -t exec -vv dist/golos.app` → "accepted".

## 4. Launch at login (remaining in-app must-have — NOT built)

One checkbox in Settings → General ("Launch golos at login") via
`SMAppService.loginItem` (pyobjc-framework-ServiceManagement, register the
bundle). The single-instance flock already makes double-launches safe.
Everything else on the old must-have list is done: py2app bundle, onboarding
wizard, this checklist.

## 5. Demo recording (90 s)

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
