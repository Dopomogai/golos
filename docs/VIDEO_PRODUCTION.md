---
@purpose: "Recording and editing blueprint for a founder-led golos launch video: long master, ~12 min medium cut, and vertical shorts."
@why: "One practical production kit so demo, story, claims, and assets stay consistent with product truth and release status."
@role: reference
@stability: evolving
@tags: [golos, video, production, founder, demo, launch]
related_docs: [docs/PRODUCT.md, docs/PRODUCT_PAGE.md, docs/GUIDE.md, docs/VISION.md, RELEASE_CHECKLIST.md, README.md]
---

# golos — founder video production kit

Practical blueprint for one natural master recording that edits into a polished
~12 minute story and several ~1 minute vertical/short cuts. Tone: founder-
authentic, energetic, transparent, technically credible — not overproduced.
Only the hook, reusable introduction, important truth disclosures, and outro
are written lines. Everything else is a speaking bullet: use your own words.

**Product name:** golos (Ukrainian for "voice").
**Inspiration (credit, don't brand):** Wispr Flow — nominative, neutral.
**Not an attack video.** Compare principles and personal needs only.

---

## 1. Story spine (speaking bullets)

- Voice input was already useful, but the tools felt closed and hard to shape
  around one person's workflow.
- Later in the story, credit Wispr Flow as the specific product that inspired
  the interaction; do not make brand recognition a prerequisite for the hook.
- Wanted transparency, ownership, flexibility, a local option, visible
  settings, and learning that asks before changing vocabulary.
- First usable golos build worked about 1.5 hours after starting.
- Two days of using it for real work produced the polished version.
- The app was used to help build itself: speak, notice friction, fix, repeat.
- Moved status feedback to the top/notch area and made hold key, language,
  models, formatting, audio assistance, dictionary, and privacy adjustable.
- It is not universally “better”; it works better for this workflow and is
  now being shared so other people can inspect and adapt it.

---

## 2. Hook options (first 10–20 seconds)

### Hook A — recommended: useful tool → owned workflow

> “Two days ago, I was using a voice-input tool I liked—but I could not see
> or control the whole system. About ninety minutes after I started building
> my own, the first version worked. Two days later, I was using it to build
> itself. This is golos.”

**On screen:** cold open on hold-to-talk + notch wings, then cut to face or
name plate. Energy high, no long logo hold.

### Hook B — alternative: AI building something immediately useful

> “People talk about what AI might build one day. I want to show you something
> AI helped me build in ninety minutes, polish in two days, and use every day:
> a voice-input app that I can inspect, change, and own.”

Mention Wispr Flow later in the problem/background chapter, not in the hook.

**On screen:** face-to-camera or screen + voiceover; brief credit, then
immediately into product motion (wings / insert).

**Pick one** for the long master cold-open; use the other for a short cut.

---

## 3. Reusable “who I am” block (20–30 s)

> “I’m Andrii, and I’m building Dopomogai. We help companies and nonprofits
> become AI-powered by delivering the products and services that make AI
> practical. In these videos, I share what AI can already do—not in theory,
> but in real workflows that make work and life easier. Because every AI
> transformation eventually comes down to one person using a better tool.”

Keep this block modular and consistent across future videos. A shorter cut is:

> “I’m Andrii, and I’m building Dopomogai. We make AI practical for companies,
> nonprofits, and the people doing the work. Here I share what we can already
> build with AI to make work and life easier.”

---

## 4. Long-form raw recording rundown (target 20–30 min)

**Goal:** one continuous, natural session — spoken prompts and beats, not a
stiff monologue. Leave silence and clean cut points. Prefer talking while
demoing over describing then demoing.

| Ch | Time (approx.) | On screen | Founder says / does | Clean edit point |
|---|---|---|---|---|
| **0. Room tone** | 0:00–0:30 | Desktop idle, mic levels | 10 s silence; clap once for sync | After clap |
| **1. Cold open / hooks** | 0:30–2:00 | Face or screen | Deliver **Hook A**, pause, deliver **Hook B**. Don't explain which is "the" hook | After each hook |
| **2. Who I am** | 2:00–3:00 | Face (or PiP later) | Reusable bio block §3 | End of bio |
| **3. Problem / why** | 3:00–6:00 | Face → optional Wispr Flow mention only as spoken credit (no competitor UI screenshots required) | Credit the category; name what you wanted: transparency, ownership, flexibility, local-first, inspectable learning. Explicit: not tearing anyone down | After principle list |
| **4. Build story** | 6:00–10:00 | Optional terminal / editor B-roll later; can be face-only in master | 1.5-hour usable v1 → two days of real use → polish. Dogfood loop: dictating while coding. Visual feedback moved to top/notch; settings became real knobs | After "two days" beat |
| **5. Product walkthrough** | 10:00–22:00 | Full product (see §5) | Demo each beat with real text; restate only when it clarifies | After each demo beat (see §5) |
| **6. Open source / files** | 22:00–24:00 | Finder/`~/.golos` or repo tree | History, dictionary, corrections as plain files; "you own this" | After file tour |
| **7. Honesty / status** | 24:00–26:00 | Face or dual | **Pre- or post-launch lines** (§10). What works today; what still must ship for public download | After status |
| **8. Invitation + outro** | 26:00–28:00 | Face | Trial/feedback ask; like/share; more build videos (§8) | After CTA |
| **9. Safety takes** | 28:00–30:00 | As needed | Second takes of hooks, failed dictations, alternate CTAs, one full hold-to-talk clean take | End |

**Master tips**

- Keep talking through mistakes; re-do the sentence once and move on.
- After each major beat, pause 1–2 s looking at camera or desktop (edit air).
- Prefer **Notes** (large font) + one browser/IDE window for context demos.
- Record **longer** than needed on the walkthrough; shorts will steal clips.

---

## 5. Product walkthrough beats (demo order)

Do these live in the master. Each row is a discrete edit island.

| # | Beat | What to show | What to say / do | Cut after |
|---|---|---|---|---|
| 5.1 | **Hold-to-talk** | Notes focused; hold configured key (default `fn`) | Hold, speak a short sentence, release → text at cursor. Point at top of screen as wings appear | Green success fades |
| 5.2 | **Immediate repeat** | Same field | As soon as green "✓ inserted" shows, hold again and dictate a second line. Proves success state doesn't trap you | Second insert |
| 5.3 | **fn+Space lock** | Notes or empty field | First confirm the startup log says `combo path: event tap (blocking)` and all permissions are ✓ for the binary on camera. `fn`+Space → hands-free lock; talk without holding; single `fn` press (or combo again) to stop and insert. If Space enters Notes, stop, fix Input Monitoring, restart, and retake | After insert |
| 5.4 | **Esc cancel** | Start a recording | Hold, say something disposable, hit **Esc** — nothing inserts. "Cancel when it's junk" | After cancel |
| 5.5 | **Top feedback + processing / success** | Full menu-bar / notch | On a notched display, show the red→orange wings. Otherwise use the corner pill. On release: collapse → blue processing shimmer → green "✓ inserted" state. Note: idle = no bubble; never call it Apple Dynamic Island hardware | Success end |
| 5.6 | **Raw vs formatted** | Settings → General, then Notes | Turn **Format with LLM** off → dictate fillers ("hey hey hey…") → raw lands. Turn on → same idea cleaned (fillers out, punctuation). One checkbox, your choice | After both modes |
| 5.7 | **English / Ukrainian** | Settings → Languages (`en, uk` or as set) | Short English line; short Ukrainian line (or switch languages between takes). Don't claim universal language coverage — only what you configured | After second language |
| 5.8 | **Audio-assisted formatter** | Settings → Prompt → "Also send the audio to the formatter" | Explain carefully: optional; original recording can go to **golos's internal formatter** so it can recover garbled STT. **Never** claim audio is attached to the destination chat/email/app. Toggle on only if model supports audio; show one recovery-style dictation if it helps | After one clean explanation + optional demo |
| 5.9 | **Configurable hold key** | Settings → Hold-to-talk key | Switch e.g. `fn` → Right Option (or F5); live rebind; do one hold with the new key; switch back if you prefer default for rest of video | After successful rebind demo |
| 5.10 | **Optional: context-aware filenames / citations** | VS Code or Finder / Notes with visible text | Include only after a practice take produced the filename or `> quote` on this machine. Requires formatting, a working key/model, context enabled, and readable on-screen text. If the practice take fails, skip this island; never voice over a result that did not insert | After one clear win |
| 5.11 | **Correction learning + explicit approval** | Insert a known mis-hear and hand-fix it | Use the reliable camera path: open History → Suggestions, click **Check for edits**, then Add to corrections / dictionary or Dismiss. Treat the live `wrong → right ✓?` cue as optional B-roll if it appears. Stress: **nothing is learned without your approval** | After promote or dismiss |
| 5.12 | **Privacy / local-first** | Settings General + Prompt toggles | Raw mode means no formatting LLM and no context sent to a formatter. Fully local requires on-device STT **and** formatting off; cloud STT still uploads audio. With cloud formatting on, transcript and allowed context leave for the formatter API; audio also leaves if cloud STT or audio-assisted formatting is enabled. History, dictionary, corrections, and—by default—per-dictation WAVs under `~/.golos/recordings/` are local files you can inspect or delete; turn off keep-recordings if you do not want WAVs retained | After toggle story |
| 5.13 | **Onboarding / settings tour** | Menu → Welcome / Setup…; then Settings tabs | Quick pass: permissions live ✓/✗, hold-key test pad, formatting radio cards, try-it field. Settings: General, Prompt, Dictionary, History — don't narrate every control | Exit Settings |
| 5.14 | **Open-source files** | Repo root or `~/.golos` | "Readable Python app. Your dictionary, corrections, history — plain files." Optional: glance at `docs/` or package layout without a deep code review | After files |

**Practice lines (safe, non-personal)**

- Hold-to-talk: "This is a quick test of golos hold to talk."
- List / formatting: "First open the issue. Second write the fix. Third open the pull request."
- Citation (only with real on-screen text): "About the second point — that needs a clearer example."
- Ukrainian sample (if languages include `uk`): a short neutral phrase you are comfortable saying on camera.

---

## 6. Twelve-minute edited story structure

Target **~11:30–12:30**. Timecodes are edit targets, not master clock. The
existing 41:22 chronological footage is sufficient; this cut should preserve
the build-in-public documentary character while reaching product proof early.

| TC | Section | Content | Sources from master |
|---|---|---|---|
| **0:00–0:20** | **Hook / proof** | Open with a clean hold-to-talk result and notch motion; then the generic problem: voice input is useful, but closed tools limit control | §5.1 + §4 ch1 |
| **0:20–1:10** | **Who I am** | Short reusable Dopomogai introduction: building a company with AI; helping people and organizations improve real workflows | §2 |
| **1:10–2:10** | **Origin / problem** | Credit Wispr Flow as inspiration; personal needs: transparency, ownership, flexibility — not an attack | §4 ch3 |
| **2:10–3:10** | **Build story** | First useful version in ~1.5 h, then two days of dogfooding and polish; explain why open source matters | §4 ch4 |
| **3:10–5:50** | **Core product proof** | Hold/release, fn+Space lock, Esc, processing→success, raw versus formatted, and the two OpenRouter calls | §5.1–5.6 |
| **5:50–7:40** | **Context and control** | Focused-input versus surrounding-visible context, text before cursor, model choice, optional formatter audio, answer-from-context example | §5.7–5.10 |
| **7:40–8:45** | **Fast mode / onboarding** | One normal formatted run, one short fast-mode run, then the best setup screens—avoid repeated tests | §5.5 + onboarding |
| **8:45–10:00** | **Learning and honest failure** | Show correction learning intent; keep the Mercy/Mercey miss as build-in-public evidence and annotate the v0.3.1 hardening | §5.11–5.12 |
| **10:00–10:50** | **History / recovery / transparency** | History-first Settings: Copy, Retry, Show audio; plain files, privacy toggles, open repository | §5.13–5.14 |
| **10:50–11:35** | **Release result** | Public v0.3.1, Apple Silicon + Intel, optional local MLX, unsigned/not notarized first-launch disclosure | §9 release truth |
| **11:35–12:00** | **Invitation / outro** | Ask viewers to try it, leave feedback, and subscribe for more practical AI builds | §8 |

**Pacing notes**

- Keep competitor mention brief and about your needs, not product criticism.
- Keep the genuine learning/overlay discoveries; annotate their v0.3.1 status.
- Cut OBS setup, agent waiting, repeated tests, duplicated context explanations,
  Vercel authentication, and abandoned outro takes.
- Captions: product words as spoken (`golos`, `fn`, Wispr Flow).
- Music: light, low, under VO — optional; silence is fine.

**Pickup rule:** no foundational rerecord. Optional additions are one 10–15 s
History recovery capture and, only if the edit needs a resolved ending, one
15–20 s successful approved correction. Use overlays for v0.3.1, unsigned /
not-notarized status, formatter `send_audio` default-off, fixed prompt/fade
bugs, and the exact MLX model id. Capture the live `/golos` page only after its
deployment is verified; until then use GitHub Releases or the local PR preview.

---

## 7. Four short-video cut plans (45–60 s each)

### Short 1 — "1.5-hour prototype, two-day polish"

| | |
|---|---|
| **Hook (0–8 s)** | "I had a usable Mac dictation app in about ninety minutes." |
| **Master moments** | Hook A; build story; hold-to-talk + wings; green insert |
| **Captions / B-roll** | Big lower-third: "≈1.5 h → usable"; "2 days → daily driver". Screen: one clean dictation |
| **CTA** | "Building in public — follow for the full walkthrough." |

### Short 2 — "Open-source push-to-talk I can own"

| | |
|---|---|
| **Hook (0–8 s)** | "I wanted push-to-talk like the best of that category — with ownership." |
| **Master moments** | Hook B; problem principles; open-source files; privacy toggles |
| **Captions / B-roll** | "Inspired by the push-to-talk dictation category (credit: Wispr Flow)" / "Open source · cloud or local · your files". One credit; no competitor logo, affiliation, or "alternative to" lower-third |
| **CTA** | Pre-launch: "Source and download when we publish." Post-launch: live URL/repo |

### Short 3 — "Built by dictating into itself"

| | |
|---|---|
| **Hook (0–8 s)** | "I wrote this app by talking into the app." |
| **Master moments** | Dogfood line; hold-to-talk while Notes/editor visible; immediate repeat; optional context filename |
| **Captions / B-roll** | Split: code/editor + live insert. Caption: "Feedback loop = speak → build → speak" |
| **CTA** | "Want the full demo? Link / next video." |

### Short 4 — "Privacy, control, customization"

| | |
|---|---|
| **Hook (0–8 s)** | "Dictation that doesn't decide everything for you." |
| **Master moments** | Raw vs formatted; hold-key change; languages; learning approval; privacy section |
| **Captions / B-roll** | Checklist captions: "Raw or formatted", "Your hold key", "Approve corrections", "Cloud first, local optional" |
| **CTA** | "Settings you can see. Learning you approve." + trial/feedback |

**Shared pre-launch endcard for every short:** “Works on my machine; public
source and download when we ship — follow for the release.” Replace it with
the live URL only after publication.

---

## 8. Reusable outro

> “Try golos and tell me what you would improve. And if you want to see more
> practical things we can build with AI, subscribe. I’ll share the real build
> process—not only the finished product.”

**Swap-ins**

- **Pre-launch:** “The public repo and download are coming with the release.”
- **Post-launch:** “The download and source are linked below.”
- **Optional like ask:** “If this was useful, like the video so more people
  can find it—and subscribe for the next build.”

Avoid generic "smash that like button" energy; keep it peer-to-peer.

---

## 9. Recording checklist

### Pickup checklist for the master already recorded

Use this as the quick gap check before handing footage to editing agents. A
single clean take of each checked item is enough:

- [ ] Generic hook: useful voice input, but you wanted transparency and control.
- [ ] Reusable Andrii / Dopomogai introduction (§3).
- [ ] The build story: usable in ~1.5 hours; polished through two days of real use.
- [ ] One clean hold → speak → release → insert, with the full top animation visible.
- [ ] One immediate-repeat take started during the green success state.
- [ ] One hands-free lock take (`fn`+Space) and one Esc-cancel take.
- [ ] Raw versus LLM-formatted result; say that Fast mode skips the formatter.
- [ ] Audio-assisted formatter: optional audio goes to Golos's formatter, not
  to the destination app; use an audio-capable model.
- [ ] Context take: focused-field draft versus surrounding visible reading
  context, with a real successful continuation or citation on screen.
- [ ] Correction take: hand-fix a name, show the suggestion animation, then
  explicitly approve it; Golos never silently promotes a correction.
- [ ] Settings glance: languages, model choice, hold key, status words on/off,
  OpenRouter default, optional local model download.
- [ ] Open-source proof: public repo, readable files, `~/.golos` ownership.
- [ ] Compatibility truth: macOS 13+; Apple Silicon cloud/local; Intel cloud-only;
  current beta is unsigned, so Gatekeeper friction is disclosed.
- [ ] Website/download pickup after `/golos` is live, or use the GitHub v0.3
  release as the current public download.
- [ ] Clean subscribe outro (§8), plus 2–3 seconds of silence for the edit.

- [ ] **Clean desktop** — hide personal files, tidy Dock, neutral wallpaper, large UI font in Notes.
- [ ] **Notifications off** — Focus mode; mute Slack/email banners; calendar alerts off.
- [ ] **Fresh app restart** — `./dictate.sh restart` or quit/relaunch `golos.app`; one instance only.
- [ ] **Stable settings** — Fast mode **off** for formatting comparisons. Use a known-good STT/model for the language take (`nova-3`, Whisper, or Chirp for Ukrainian; not Qwen ASR). For the privacy/local take use on-device STT + formatting off, or clearly identify the cloud path. Note exact STT, formatter, languages, hold key, and retention setting for the edit log. Waveform sensitivity ~1.3 if wings look thin on camera.
- [ ] **Practice text** — Non-personal sample lines ready (§5).
- [ ] **Quiet audio** — Quiet room; consistent mic distance; test levels; disable keyboard click sounds if loud.
- [ ] **Screen / cursor** — Resolution stable (e.g. native or fixed scaled); cursor size slightly large if needed; hide unrelated menu-bar extras.
- [ ] **Permission state** — Microphone, Input Monitoring, Accessibility all ✓ for the binary you'll demo (Terminal **or** `golos.app`). Keyboard: **Press 🌐/fn key to → Do Nothing**.
- [ ] **Privacy scrub** — Fresh or curated `~/.golos/history.jsonl`; clear Suggestions you don't want on camera; no API keys visible in Settings.
- [ ] **Backup recording** — Second capture if possible (e.g. phone audio or secondary screen record); clap for sync.
- [ ] **Windows ready** — Notes (large font) + optional VS Code/browser with safe public content for context demos.
- [ ] **Freeze / sample recovery** — If the app freezes, hotkey dies, or insert fails mid-take: stop talking, note the timecode out loud ("reset at twelve minutes"), run `./dictate.sh restart` (or quit from menu-bar), confirm Permissions still green, re-open Notes, resume from the last clean beat. Prefer a full beat re-take over patching half a sentence. If STT is flaky, fall back to a known-good short sample line rather than improvising long monologues.

---

## 10. Editorial guardrails and claim-truth table

### Guardrails

- Credit inspiration; **never** imply affiliation, endorsement, or "official alternative."
- No attack framing, no unverifiable "better than X" benchmarks.
- No invented founder bio, user counts, revenue, security certifications, or compatibility matrices.
- The release target is **macOS 13+**: Apple Silicon supports cloud plus
  optional local MLX; Intel uses the separate cloud-only build. Say this only
  after both artifacts pass the release smoke test.
- **Audio-assisted formatting** only feeds **golos's internal formatter** — never say audio is attached to the destination chat, email, or app.
- "Wispr Flow" / category leaders: nominative use only; do not reuse their marks as golos branding.
- Demo only what happens on camera; if context/citation fails, cut or re-take — don't voice over a fantasy result.
- Prefer "on my machine," "in this build," "for my workflow" over universal claims.

### Claim-truth table

| Claim | Now (pre-publication) | Only after publication | Do not claim |
|---|---|---|---|
| Code works; app runs on founder machine | ✓ | ✓ | — |
| DMG / `.app` build exists (unsigned unless signed) | ✓ (honest about Gatekeeper / right-click Open if unsigned) | Signed & notarized when true | "Available on the Mac App Store" unless true |
| Public GitHub repo / clone URL | Use **swap-in**: "when the repo is public" | ✓ live URL | Fake star counts or "everyone is using this" |
| Public download link | Swap-in only | ✓ live DMG URL | "Download today" without a real link |
| Website / product page live | Swap-in only | ✓ when deployed | SEO or traffic claims |
| Open source, cloud-first default, optional local STT, human-gated learning | ✓ (as implemented) | ✓ | "Military-grade encryption," "zero data ever leaves" while cloud STT/formatting is on |
| Inspired by / comparable category to Wispr Flow | ✓ neutral credit | ✓ | "Replacement for," "clone of," affiliation |
| Multilingual (e.g. en + uk) | ✓ only if configured and shown | ✓ | "All languages," "perfect Ukrainian" without demo |
| Faster than typing / 2–3× | Soft personal experience only if you stand behind it | Same | Hard productivity studies you didn't run |
| Launch-at-login | — | Only when built | Claiming it ships today if still open on checklist |
| Signed + notarized Gatekeeper-clean install | — | ✓ after notarization | "Fully trusted by macOS" while unsigned |

### Swap-in lines

**Pre-launch (record these; keep in master even if you later cut):**

> "The app works on my machine—the code and public beta are already available.
> The current DMG is unsigned, so the signed and notarized release is still a
> separate step. I'm showing exactly what works today."

**Post-launch:**

> "golos is public — source and download in the description. Free for
> everyone under the MIT License; you own your data files under `~/.golos`."

---

## 11. Asset handoff list (for an editing agent)

Deliver one folder (e.g. `video/golos-launch-master/`) with:

| Asset | Spec / notes |
|---|---|
| **Master video** | Full 20–30 min recording, highest quality available (screen + camera if dual) |
| **Isolated mic** | WAV/AIFF if separate recorder; else best system/mic track labeled |
| **Screen capture** | Full display, cursor visible; same session as master if possible |
| **Product-page capture** | Static and short scroll capture of the real `/golos` route from the isolated website worktree before deployment, then from the live URL after deployment |
| **Repo / file shots** | Brief clips or stills: repo tree, `~/.golos` files (no secrets) |
| **DMG install shot** | Open DMG → drag to Applications (note unsigned vs notarized truth in slate) |
| **Timestamps** | Plain text log: master TC → beat name (align to §4–§5) |
| **Transcript** | Rough transcript of master (auto-OK); mark preferred hook A/B |
| **Brand assets** | App icon (`dictate.icns` / generated PNG), chakra menu-bar glyph, product name "golos", tagline options from `docs/PRODUCT_PAGE.md` |
| **Settings snapshot** | Text file: hold key, languages, formatting on/off, backend — for caption accuracy |

### Desired exports

| Export | Format |
|---|---|
| Main story | **16:9**, ~5 min, 1080p or better |
| Shorts | **9:16**, four cuts × 45–60 s (plus vertical safe margins for captions) |
| Captions | SRT/VTT per export; burned-in optional for shorts |
| Thumbnails | 16:9 + 9:16: notch wings or hold-to-talk freeze + short honest title (no fake metrics) |

### Editor brief (one paragraph)

Open on the chosen hook with real product motion. Credit the category once,
then prove golos with hold-to-talk, notch feedback, control and privacy, and
human-gated learning. Stay founder-authentic; cut anything that sounds like
an attack or an unverified benchmark. End with the status-honest invitation
and the reusable outro. Prefer truth over polish.

---

## Quick reference — spoken product truths

| Topic | Safe line |
|---|---|
| What it is | Menu-bar push-to-talk: hold key, speak, text at cursor |
| Inspiration | Liked the category Wispr Flow helped define; built for ownership |
| STT choice | OpenRouter is the default; Apple Silicon can download optional on-device STT |
| Formatting | Optional LLM pass; raw mode is one checkbox |
| Learning | Proposes corrections; you approve or dismiss |
| Audio to formatter | Optional assist **inside golos** — not sent to the chat you're typing in |
| Status | See claim-truth table; never invent launch completeness |

---

*Source alignment: `docs/PRODUCT.md`, `docs/GUIDE.md`, `docs/VISION.md`,
`docs/PRODUCT_PAGE.md`, `docs/TESTING.md`, `README.md`, `RELEASE_CHECKLIST.md`.
Update this kit when release status or product behavior changes.*
