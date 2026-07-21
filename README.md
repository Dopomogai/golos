---
@purpose: "Project entry point for golos: what it is, how it works, setup, permissions, and links into deeper docs."
@why: "Gives a single starting place so install, permissions, and doc discovery are not scattered or guessed."
@role: reference
@stability: accepted
@tags: [golos, readme, setup, permissions, dictation]
related_docs: [docs/PRODUCT.md, docs/GUIDE.md, docs/TECH.md, docs/VISION.md, docs/ROADMAP.md, docs/PRODUCT_PAGE.md, docs/TESTING.md, RELEASE_CHECKLIST.md]
---
# golos

A minimal macOS push-to-talk dictation app, in Python + PyObjC
(renamed from "dictate" — the python packages are still `dictate`/`dictate_core`).

> Help center: [golos.dopomogai.com/docs/](https://golos.dopomogai.com/docs/)
> (getting started, settings, workflows, privacy, troubleshooting).
> Repo deep dives: [docs/PRODUCT.md](docs/PRODUCT.md) ·
> [docs/GUIDE.md](docs/GUIDE.md) · [docs/TECH.md](docs/TECH.md) ·
> [docs/VISION.md](docs/VISION.md) · [docs/ROADMAP.md](docs/ROADMAP.md) ·
> [docs/PRODUCT_PAGE.md](docs/PRODUCT_PAGE.md) · [docs/TESTING.md](docs/TESTING.md)

**Download (v0.3.2 beta DMGs — pick your architecture):**

- [Apple Silicon](https://github.com/Dopomogai/golos/releases/download/v0.3.2/golos-0.3.2-apple-silicon.dmg)
  — cloud + optional local MLX
- [Intel](https://github.com/Dopomogai/golos/releases/download/v0.3.2/golos-0.3.2-intel.dmg)
  — cloud-only OpenRouter

Unsigned beta: first launch is **right-click → Open**. Release notes and
checksums: [latest release](https://github.com/Dopomogai/golos/releases/latest).
Product page source: [`site/`](site/) (direct architecture chooser at
`#download`; roadmap at `#roadmap`).

**Tests:** `.venv/bin/pip install -r requirements-dev.txt` then
`.venv/bin/python -m pytest -q` — see [docs/TESTING.md](docs/TESTING.md).

- **Hold `fn` to talk**, release to transcribe and insert at the cursor.
- **`fn` + Space** toggles a hands-free "locked" recording mode (press again to stop).
- Notch-style floating bubble (Dynamic Island look: hugs the camera notch, expands
  with a live waveform while recording) or a draggable corner pill.
- Menu-bar icon with Settings (History first, then General / Prompt / Learning / Dictionary) — no dock icon.
- OpenRouter cloud STT works without downloading a local model; Apple Silicon
  users can optionally download the ~1.5 GB MLX model for on-device STT.

## How it works

1. **fn down** → audio capture starts (16 kHz mono) and the bubble turns red.
   The frontmost app's name / bundle id / window title is captured as context.
2. **fn up** → the audio goes to the selected STT backend (OpenRouter by
   default), with your `dictionary.txt` terms passed as a vocabulary hint.
3. The raw transcript goes through a **formatting LLM pass** (OpenRouter by
   default): fillers and false starts removed, punctuation fixed, corrections
   from `corrections.tsv` applied, spoken filenames turned into real ones using
   the app/window context. Skipped gracefully if no API key is configured.
4. The final text is **posted for insertion** at the cursor of the frontmost
   app: single-line text is *typed* as synthetic keystrokes; multi-line text
   goes via the clipboard + synthetic Cmd+V — and the clipboard then simply
   keeps the transcript (restoring the old clipboard raced slow apps into
   pasting the OLD content; `[insert] restore_clipboard = true` opts back in).
   Missing Accessibility now stops before posting and preserves the result as
   an insert failure in History. Green "✓ inserted" means the permission
   preflight passed and events were posted—not that the target app verified
   delivery; custom or incompatible fields can still reject synthetic input.
5. Every dictation is appended to `history.jsonl`
   (`ts`, `app`, `bundle_id`, `raw`, `final`).

`dictionary.txt` and `corrections.tsv` edits saved from the Settings window
reload into the running pipeline immediately — no restart needed.

## Requirements

- macOS 13+
- Apple Silicon for the full build and optional local MLX model
- Intel Macs use the cloud-only build (OpenRouter; local MLX is unavailable)
- Python ≥ 3.11 (uses stdlib `tomllib`)

## Setup

```sh
git clone https://github.com/Dopomogai/golos.git
cd golos
python3.11 -m venv .venv        # or any python ≥ 3.11
.venv/bin/pip install -r requirements.txt        # OpenRouter, no local model
# Apple Silicon only, when local STT is wanted:
.venv/bin/pip install -r requirements-local.txt
```

## macOS permissions (required)

macOS gates everything this app does. Grant **Terminal** (or iTerm, or whatever app
launches `./dictate.sh`) — or **golos.app** for the DMG build — the following in
**System Settings → Privacy & Security**:

1. **Microphone** — for audio capture.
2. **Input Monitoring** — for the global `fn` hotkey monitor and event tap.
3. **Accessibility** — for synthetic type/paste insert and reading focused context.
   Insert is **preflighted**: without Accessibility the result is saved in History
   and a warning is shown — not a false green success.

Also: **System Settings → Keyboard → "Press 🌐/fn key to" → Do Nothing** —
otherwise pressing fn triggers macOS's own action (emoji picker / dictation)
and the app can't use it reliably.

After granting permissions — especially **Input Monitoring** — restart the
terminal or relaunch **golos.app** so the event tap can install.

**First run opens an onboarding wizard** that walks all of this with live ✓/✗
checks (reopen anytime: menu-bar icon → "Welcome / Setup…").

**Note for the bundled app:** `dist/golos.app` is a *separate* macOS
identity from your terminal — you must grant the same three permissions to
**golos.app** itself (the wizard appears on its first run too).
Replacing an unsigned beta may require regranting permissions.
(`dist/dictate.app` from earlier builds is superseded — delete it.)

**Intermittent UI / insertion debugging:** do **not** restart first. Menu-bar
chakra → **Export Diagnostics…** creates a redacted local zip (rotating logs
under `~/.golos/logs/`; no keys, audio, or transcript/prompt/context content).
Nothing uploads until you share the file. This preserves evidence; it does not
claim every failure mode is fixed.

## Data files

All mutable state lives in **`~/.golos/`**: `config.toml` (chmod 600 — it
holds the API key), `dictionary.txt`, `corrections.tsv`, `history.jsonl`,
`suggestions.jsonl`, `dismissed.jsonl`, `recordings/`, `logs/` (rotating
diagnostics), and `dictate.lock`.
On first launch after the rename, the dictate-era **`~/.dictate/`** set is
**copied** over (originals kept; only `samples/` stays in the project for
the bench harness).

## Build the .app + installer

```sh
# Apple Silicon edition (install requirements-local.txt first):
./build_app.sh
./make_dmg.sh 0.3.2-apple-silicon
# Intel/cloud-only edition (requires an x86_64 Python 3.11+):
./build_intel_app.sh
./make_dmg.sh 0.3.2-intel
```

Requires `py2app` and `setuptools<80` (in the requirements files). The bundle is
unsigned — to run it: **right-click → Open** (Gatekeeper), then re-grant the
three permissions (Microphone, Input Monitoring, Accessibility) to
**golos.app** — it's a separate TCC identity from your terminal. The
onboarding wizard appears on first run and walks you through it. Signing,
notarization, and a trustworthy update path are near-term distribution work
(see [docs/ROADMAP.md](docs/ROADMAP.md)); do not claim the beta is signed or
auto-updating.

## Install (from the DMG)

1. Open the DMG for your architecture, then drag **golos** onto **Applications**.
2. First launch: right-click → **Open** (unsigned build).
3. Grant the three permissions to golos.app when the wizard asks.


## Run

```sh
cd ~/dictate
./dictate.sh            # start
./dictate.sh quit       # stop the running instance (pid verified via the lock)
./dictate.sh restart    # quit + start
```

Hold `fn`, speak, release. Text is posted at the cursor of the compatible
frontmost text field. Some apps or fields can reject simulated insertion;
History keeps the result available to copy or retry.
`fn`+Space locks recording on; **a single press of `fn`** (or `fn`+Space again)
stops and inserts. The Space in the combo is swallowed by a CGEventTap (needs
the Input Monitoring permission you already granted — if the tap can't be
created, an observe-only fallback is used and the Space also types into the
target app; the startup log says which path is active:
`combo path: event tap (blocking)` vs `monitor (observe-only)`).
Quit from the menu-bar icon. Only one instance can run at a time — a second
start exits with `dictate is already running (pid N). Quit it from its menu,
or run: kill N  (or ./dictate.sh restart)` (the lock is an `flock`, released
automatically when the process dies; a Ctrl+Z-suspended process still holds
it — that's what `./dictate.sh quit` is for).

## Use dictate as a library

The UI-free brain lives in the sibling package `dictate_core` (no AppKit —
embeddable in your own apps/widgets):

```sh
pip install -e ".[app]"       # cloud-first desktop app, no MLX
pip install -e ".[app,mlx]"   # optional local STT on Apple Silicon
```

```python
from dictate_core import VoicePipeline

vp = VoicePipeline()      # key: openrouter_key= > OPENROUTER_API_KEY > ~/.golos/config.toml
wav = open("clip.wav", "rb").read()          # 16 kHz mono wav

raw   = vp.transcribe(wav)                    # STT with dictionary biasing
final = vp.format(raw, app_name="Slack")      # stage-2 LLM (or passthrough)
final = vp.process(wav, app_name="Slack")     # both in one call
pairs = vp.suggest_corrections("wisper flow", "Wispr Flow")  # learning diff
```

Options: `stt_backend="openrouter" | "mlx"`, `stt_model`, `formatter_model`,
`formatter_enabled=False` (raw mode), `dictionary=[...]`, `corrections=[...]`,
`language=""`.

## Benchmarking STT models

Compare transcription models on your own voice:

```sh
python -m dictate.bench record meeting   # speak, Enter to stop -> samples/meeting.wav
# edit samples/meeting.txt so it matches what you said (pre-filled with a draft)
python -m dictate.bench run              # mlx + all 9 curated cloud models
python -m dictate.bench run --models deepgram/nova-3,qwen/qwen3-asr-flash-2026-02-10
```

`run` prints a table (model | avg WER | avg latency | per-sample WERs, sorted
by WER), `--verbose` shows every transcript, `--json out.json` saves results.
WER is word-level ((S+D+I)/N after lowercase + punctuation stripping). Each
cloud call costs a fraction of a cent; a full run is on the order of cents.

## Settings

Click the **chakra** status icon in the menu bar → **Settings…**
(template glyph at 14 pt; SF Symbol `mic.fill` only if the glyph asset is
missing). Day-to-day UI walkthrough:
[Help Center → Settings](https://golos.dopomogai.com/docs/settings/).
The menu also has:

- **Test insertion** — posts `✅ golos insertion test` at the current cursor
  (Accessibility + type/paste path). Missing Accessibility produces a warning;
  success means insertion *events were posted*, while the target app still
  does not confirm delivery.
- **Permissions ▸** — live ✓/✗ for Accessibility, Input Monitoring and
  Microphone (refreshed each time the menu opens); clicking a ✗ item opens the
  matching System Settings pane. The same three checks run at startup and log
  loud ⚠ warnings with deep links for anything missing.
- **Export Diagnostics…** — creates a redacted local zip for a bug report.
  Runtime logs rotate under `~/.golos/logs/`; export includes build,
  permission, visual-state, and run-status metadata but excludes API keys,
  prompts, transcript/context text, and audio. Nothing uploads automatically.

Five tabs (History is first and opens by default):

- **History** — home dashboard: newest-first table of past dictations
  (resizable columns, Raw → Final takes the spare width); select a row for
  raw/final/context/error detail. **Copy text** takes the best available
  final/raw result, **Retry** appends a new recovery attempt without silently
  inserting into the Settings window, and **Show audio** reveals a retained
  WAV in Finder. Suggestions still support promote/dismiss; Check for edits
  and Refresh remain in the header.
- **General** — STT backend (`openrouter` cloud-first, or `mlx` on-device),
  an explicit **Download local (~1.5 GB)** button on supported Apple Silicon Macs, STT model,
  **Languages** (comma-separated, e.g. `en, uk`; empty = auto-detect),
  formatter model, OpenRouter API key, bubble style (`notch` / `corner`),
  **Hold key** popup (`fn` / Right Option / Right Command / F5 — live rebind),
  **Input sensitivity** slider (0.5–2.5 — display gain for the recording
  waveform; 1.0 default), the **Format with LLM** checkbox (uncheck for
  the fastest raw-insert mode — no formatting pass, no context leaves the
  machine), and **Fast mode** (skip LLM cleanup for short dictations —
  short inserts become instant, `corrections.tsv` still applies locally).
  **Fetch models** (General footer) pulls the current OpenRouter model list
  (audio-capable models for STT, all text models for the formatter); listing
  works without a key, and the combo boxes keep your current values if the
  fetch fails. **Save** writes `config.toml` and rebuilds the STT/formatter
  pipeline live. Bubble style applies after restart.
- **Prompt** — context-sharing toggles (what the formatter may see),
  the **Answer obvious questions from context** toggle, **Also send the
  audio to the formatter** (recover from bad transcription; costs a little
  more, needs an audio-capable model), and the system prompt template editor
  (`~/.golos/prompt.md`).
- **Learning** — optional OpenRouter reviewer after you edit an insert
  (never auto-promotes; approve in History or the live cue). Live-cue
  enable/duration is **config-only** (`[learning] live_cues` /
  `live_cue_seconds`), not a Learning-tab control.
- **Dictionary** — edit terms and corrections as tables (+/− to add/remove
  rows, double-click to edit inline); Save applies them to the running
  pipeline immediately. File comments (`#` lines) are preserved on save.

## OpenRouter

The cloud features (STT backend `openrouter`, formatter provider `openrouter`)
use one key: set `[openrouter] api_key` in Settings, or export
`OPENROUTER_API_KEY` (the env var takes precedence). With no key at all the app
prompts you to connect OpenRouter or deliberately select/download the optional
local MLX backend on Apple Silicon; it never downloads model weights silently.

**OpenRouter STT** posts to `https://openrouter.ai/api/v1/audio/transcriptions`
with a JSON body — `{"model": id, "input_audio": {"data": <base64 wav>,
"format": "wav"}, "prompt": "<dictionary terms>"}` — and the `prompt` biases
recognition (your dictionary terms influence spelling/capitalization).
OpenRouter's public `/models` catalog does **not** list transcription models,
so the STT dropdown is a curated, verified list (see
`TRANSCRIPTION_MODELS` in `dictate/openrouter.py`, probed against the live API
2026-07-18): `deepgram/nova-3` (default — fast, cheap, strong multilingual),
`qwen/qwen3-asr-flash-2026-02-10`, `google/chirp-3`,
`nvidia/parakeet-tdt-0.6b-v3`, `mistralai/voxtral-mini-transcribe`,
`microsoft/mai-transcribe-1.5`, `openai/whisper-1`, `openai/gpt-4o-transcribe`,
`openai/gpt-4o-mini-transcribe`. The combo stays editable for trying new ids.
The formatter model dropdown still comes from the live `/models` fetch.

Defaults: STT `deepgram/nova-3`, formatter `google/gemini-2.5-flash`. Both are
configurable in Settings or `config.toml`.

## The bubble

**Idle means no bubble** — the app shows nothing until you dictate.

- **notch** (default, on notched MacBooks): the strip around the camera notch
  is the single status surface. While you speak, red→orange **wings** ripple
  live from both notch edges (silence shows a perfectly even dotted line).
  When you stop, they collapse inward (~0.2 s) and the strip returns in
  **blue processing mode** — a traveling shimmer on both sides plus an
  animated "processing… Ns" label in the notch gap — then a **green "✓
  inserted"** hill (tallest at the notch, tapering outward) that ebbs away
  over ~1.2 s (posted-events success, not app-confirmed delivery). The panel
  is fully click-through: it never blocks your menus. Idle = no bubble at all.
- **corner**: a 132×36 draggable pill at the bottom-right with a live waveform
  while recording; hidden when idle.

Both are non-activating (never steal focus), float at NSStatusWindowLevel
(above the menu bar), appear on all spaces, and carry
`NSWindowCollectionBehaviorFullScreenAuxiliary` so they stay visible over
fullscreen apps.

## Learning loop

dictate notices when you fix an insertion by hand and proposes the correction:

1. After each successful paste, the inserted text is remembered (with the app
   it went into).
2. The field is re-checked at four trigger points: the start of your **next**
   recording, when you **switch away** from that app, a **45 s fallback
   timer**, or the **Check for edits** button in Settings → History.
3. Two quality gates keep junk out of the list: the inserted text must be
   verifiably present (longest exact common substring ≥ 60% of it), and each
   candidate pair must look like a near-miss correction (similarity ≥ 0.5 or
   containment, ≤ 6 tokens). Skipped captures are explained in the log.
4. Replacement pairs (e.g. `wisper flow` → `Wispr Flow`) land in
   `suggestions.jsonl` and show up aggregated (with counts) in the
   **Suggestions** table in Settings → History.
5. From there: **Add to corrections**, **Add to dictionary**, or **Dismiss**.
   All promote actions live-reload the pipeline.

You can also teach the dictionary explicitly: select a word/name anywhere and
use the menu-bar item **Add selection to dictionary**. And after each
insertion, the **edit watcher** polls the field for a few minutes: if you
hand-edit a word and pause, a clickable cue pill appears
(`wrong → right ✓?`) — click it to add the correction to `corrections.tsv`
instantly (`[learning] live_cues = true`, `live_cue_seconds = 8`).
An optional **learning reviewer** (`[learning] reviewer_enabled`, default
off) can re-check a stable edit via OpenRouter (optional retained audio);
still human-gated — never auto-promotes.

Only edits made within `[learning] edit_window_seconds` (default 600 s) after
the paste are considered, and only while the same app is frontmost (the
app-switch trigger reads the old app's field via its pid as a best effort).
The anchor matching is scroll-tolerant: when the input field has scrolled
and only shows the tail of a long insertion, coverage is measured against
the visible overlap instead of the whole insertion. Short proper-name
fixes (e.g. Mercy→Mercey) in long fields are captured even when surrounding
UI/signature text would otherwise inflate the replace span.

## App context

When `[context] enabled = true`, the formatter prompt is enriched with live
context from the frontmost app:

- **Safari / Chrome / Brave / Edge / Arc** — title and URL of the current tab
  (`current_page_title`, `current_page_url`), via AppleScript.
- **VS Code** — workspace folder parsed from the window title, located under
  `~`, `~/Documents`, `~/Documents/GitHub`, `~/Projects` (depth ≤2); then up to
  200 workspace files (depth ≤3, no `.git`/`node_modules`) as
  `workspace_root` + `workspace_files` — so spoken filenames resolve to real
  paths.
- **Finder** — front window target and current selection as POSIX paths.

The formatter is instructed to output real paths/URLs/names **from the
context only**, formatted to fit the target app (markdown link in chat/notes,
plain path in editors/terminals), and to never invent references. It also
receives three separate text roles (each toggleable under Settings → Prompt):

- **text before the cursor** (≤500 chars) — precise continuation placement
- **focused field text** (≤4000 chars) — full accessible text of the input
  you are composing in (what you are producing)
- **visible text** (≤4000 chars) — surrounding/on-screen **reading** context
  only; never a silent reuse of the focused field. Empty when inaccessible.

When your dictation comments on something in the visible text, the formatter
begins the output with a short verbatim `> quote` of the referenced part,
then your comment. It never quotes text that isn't verbatim in that
surrounding context.

Privacy note: nearby typed text (`text_before_cursor`), focused field text,
visible text, and page/workspace context leave the machine **only** when LLM
formatting is enabled — uncheck **Format with LLM** (or
`[formatting] enabled = false`) to skip the formatter network call.
**Fully local** day-to-day dictation means all three: local **MLX** STT
(Apple Silicon only, after the explicit download), formatting off, and the
learning reviewer off (`[learning] reviewer_enabled = false`, default).
Cloud STT still sends audio when the backend is OpenRouter. Intel builds are
cloud-only for STT. `[context] enabled = false` turns providers/AX reads off
independently.

Note: the first use of a browser/Finder provider may pop a macOS **Automation
consent** dialog per app — that's expected; denying simply disables that
provider. Providers never launch apps (running check first), and every call
has a hard 1.5 s timeout — a stuck app can't stall dictation.

## Configuration

> **Prompt template**: the formatter's system prompt is hardened against the
> model slipping into assistant mode (answering your dictated questions
> instead of transcribing them). If you keep a custom `~/.golos/prompt.md`,
> it wins over the built-in default — consider adding the same lines to it:
> "You are a transcription cleaner, NOT an assistant…" at the top and
> "Remember: output only the cleaned dictation…" at the end. Regression
> check: `.venv/bin/python scripts/test_formatter_behavior.py`.
>
> **Languages**: `[stt] languages = ["en", "uk"]` narrows STT to the listed
> languages (empty list = auto-detect). deepgram models get `multi`
> (code-switching) for >1 language; whisper-style models get the single code
> or a prompt hint; mlx pins one language (a list >1 falls back to auto).
> Per-model support differs: `qwen/qwen3-asr-flash` has **no Ukrainian**
> (English only, useful for `en`), while `deepgram/nova-3`, `google/chirp-3`
> and `openai/whisper-1` handle Ukrainian — run `python -m dictate.bench` on
> your own recordings to compare.
>
> **Fast mode**: Settings → General → "Fast mode (skip LLM cleanup for short
> dictations)" (`[formatting] fast_mode`, default off; `fast_mode_max_words = 10`
> config-only). Short single-line dictations skip stage 2 entirely — insert
> becomes instant; `corrections.tsv` still applies locally (literal,
> case-insensitive, all occurrences). Trade-off: no list/paragraph
> structuring on short texts while it's on. History records carry
> `fast: true` so you can compare.
>
> **Send audio**: Settings → Prompt → "Also send the audio to the formatter"
> (`[formatting] send_audio`, default off). The original recording rides
> along with the transcript so the model can correct garbled transcription
> from what it hears. Costs a little more per dictation and needs an
> audio-capable formatter model (e.g. gemini-2.5-flash); startup logs a
> warning if the configured model can't hear audio.
>
> **Answer mode**: Settings → Prompt has an "Answer obvious questions from
> context" checkbox (`[formatting] answer_questions`, default **off**). When
> on, the formatter answers a dictation only if it's clearly a direct question
> AND the context visibly contains the answer (1–3 sentences); everything
> else — including questions it can't answer from context — is transcribed
> as usual. Trade-off: lite models are nondeterministic at the edges (in
> testing, gemini-3.1-flash-lite-preview occasionally meta-comments on the
> unanswerable case ~1 in 3 runs; gemini-2.5-flash was solid). Keep it off
> unless you want the behavior. Custom `prompt.md` templates keep working
> with the toggle: the mode framing is prepended and the mode closer appended
> when the template lacks the `{{mode_rules}}` placeholder.

`config.toml` — see the shipped `config.toml` for the annotated bootstrap copy
(runtime state is `~/.golos/config.toml`). Highlights:

- `[hotkey]` — `hold_key` is also a General popup (`fn` / `right_option` /
  `right_command` / `f5`). `toggle_combo = "fn+space"` or `"double_fn"` is
  **config-only** (double-tap the hold key within 350 ms to lock; a hold over
  400 ms is never a tap). Hold-key+Space always toggles regardless of mode.
- `[stt]` — `backend = "mlx" | "openrouter" | "openai_compatible" | "deepgram"`.
  UI focuses on OpenRouter + MLX; the other backends are advanced/config.
- `[openrouter]` — `api_key` (env `OPENROUTER_API_KEY` wins).
- `[formatting]` — `provider = "openrouter" | "openai_compatible"`, `model`,
  and `debug = false`. Set `debug = true` to log the **complete system prompt
  and user message** (the full context the model receives: app, window title,
  page URL, workspace files, …) at INFO before every formatting call.
  `fast_mode_max_words` is config-only (default 10).
- `[bubble]` — `style = "notch" | "corner"`, waveform `sensitivity`, and
  `show_text = true | false` (status words or animation-only).
- `[insert]` — `method` and `restore_clipboard` are **config-only**.
  `method = "auto" | "type" | "paste"` (auto types single-line, pastes
  multi-line). The pasteboard keeps the transcript afterwards;
  `restore_clipboard = true` opts back into restoring it after 1.5 s.
- `[audio]` — `device` and `keep_recordings` are **config-only**
  (`device = 0` = default input; `keep_recordings = true` archives WAVs under
  `~/.golos/recordings/`).
- `[learning]` — reviewer controls are on the Learning tab; `live_cues` /
  `live_cue_seconds` and several reviewer knobs are config-only.

Full config tables and config-only callouts:
[docs/GUIDE.md](docs/GUIDE.md) ·
[Help Center → Settings](https://golos.dopomogai.com/docs/settings/#config-only).

Note: saving from the Settings window rewrites `config.toml` with the `toml`
package — values and untouched sections are preserved, comments are not.

## Layout

```
dictate.sh        launcher (start|quit|restart; execs .venv/bin/python -m dictate)
build_app.sh      py2app build -> dist/golos.app
setup.py          py2app config (icon, LSUIElement, TCC strings)
dictate.icns      app icon (generated by assets/make_icon.sh)
config.toml       BOOTSTRAP copy — real state lives in ~/.golos/ (see "Data files")
dictate/          python package
  __main__.py     entry point
  app.py          NSApplication + AppController state machine, instance lock, signal handling
  bubble.py       floating status NSPanel (notch wings + corner styles, waveform)
  settings.py     menu-bar chakra status item (Permissions submenu, Test insertion) + Settings window
  diagnostics.py  private rotating logs + explicit redacted support-zip export
  onboarding.py   7-page first-run wizard (welcome → permissions → hold key → OpenRouter/local → formatting → try it → done)
  openrouter.py   OpenRouter key resolution, /models listing, defaults
  permissions.py  Accessibility / Input Monitoring / Microphone checks + deep links
  hotkeys.py      global fn monitor + CGEventTap space-swallowing
  recorder.py     16 kHz mono capture (sounddevice) + RMS level callback
  stt.py          mlx / openrouter / openai_compatible / deepgram backends
  formatter.py    LLM second pass (OpenRouter or OpenAI-compatible)
  insert.py       clipboard + synthetic Cmd+V
  context.py      frontmost app + window title + cursor/visible text (AX)
  config.py       config load + persistence (tomllib read, toml write), ~/.dictate migration
  dictionary.py   dictionary/corrections loading
  history.py      JSONL append
  learning.py     edit capture → suggestions.jsonl, promote/dismiss
  (core) learning_reviewer.py  optional audio-aware OpenRouter review
  providers.py    app context: browser tabs, VS Code workspace, Finder selection
  bench.py        STT model benchmark harness (record/run subcommands)
```

## Notes / limitations

**Threading rule (dev)**: the main thread is for UI and event routing only.
AX reads, network calls, audio stream stop/abort, and file scans run on
worker threads. `recorder.start()` is the single tolerated fast-path
exception on main; `recorder.stop()`/`abort()` on the main thread once
deadlocked CoreAudio and must never happen again (guarded, idempotent).

- The paste path does not restore the clipboard by default — the transcript
  stays on the pasteboard (restoring raced slow apps into pasting the OLD
  clipboard; opt back in with `[insert] restore_clipboard = true`).
- Saving config from Settings drops comments in `config.toml`.
- Bubble style changes need an app restart.
- Global monitors are observe-only; they don't swallow the fn key for other apps.
