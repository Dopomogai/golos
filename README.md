---
@purpose: "Project entry point for golos: what it is, how it works, setup, permissions, and links into deeper docs."
@why: "Gives a single starting place so install, permissions, and doc discovery are not scattered or guessed."
@role: reference
@stability: accepted
@tags: [golos, readme, setup, permissions, dictation]
related_docs: [docs/PRODUCT.md, docs/GUIDE.md, docs/TECH.md, docs/VISION.md, docs/TESTING.md, RELEASE_CHECKLIST.md]
---
# golos

A minimal macOS push-to-talk dictation app, in Python + PyObjC
(renamed from "dictate" — the python packages are still `dictate`/`dictate_core`).

> Docs: [docs/PRODUCT.md](docs/PRODUCT.md) (user guide) ·
> [docs/TECH.md](docs/TECH.md) (architecture) · [docs/VISION.md](docs/VISION.md) ·
> [docs/TESTING.md](docs/TESTING.md) (tests & coverage)

**Tests:** `.venv/bin/pip install -r requirements-dev.txt` then
`.venv/bin/python -m pytest -q` — see [docs/TESTING.md](docs/TESTING.md).

- **Hold `fn` to talk**, release to transcribe and insert at the cursor.
- **`fn` + Space** toggles a hands-free "locked" recording mode (press again to stop).
- Notch-style floating bubble (Dynamic Island look: hugs the camera notch, expands
  with a live waveform while recording) or a draggable corner pill.
- Menu-bar icon with Settings (General / Prompt / Learning / Dictionary / History) — no dock icon.
- Local on-device STT by default; optional OpenRouter cloud STT and LLM formatting pass.

## How it works

1. **fn down** → audio capture starts (16 kHz mono) and the bubble turns red.
   The frontmost app's name / bundle id / window title is captured as context.
2. **fn up** → the audio goes to STT (local mlx-whisper by default), with your
   `dictionary.txt` terms passed as an `initial_prompt` for vocabulary biasing.
3. The raw transcript goes through a **formatting LLM pass** (OpenRouter by
   default): fillers and false starts removed, punctuation fixed, corrections
   from `corrections.tsv` applied, spoken filenames turned into real ones using
   the app/window context. Skipped gracefully if no API key is configured.
4. The final text is **inserted at the cursor** of the frontmost app:
   single-line text is *typed* as synthetic keystrokes; multi-line text goes
   via the clipboard + synthetic Cmd+V — and the clipboard then simply keeps
   the transcript (restoring the old clipboard raced slow apps into pasting
   the OLD content; `[insert] restore_clipboard = true` opts back in).
5. Every dictation is appended to `history.jsonl`
   (`ts`, `app`, `bundle_id`, `raw`, `final`).

`dictionary.txt` and `corrections.tsv` edits saved from the Settings window
reload into the running pipeline immediately — no restart needed.

## Requirements

- macOS on Apple Silicon (mlx-whisper requires it)
- Python ≥ 3.11 (uses stdlib `tomllib`)

## Setup

```sh
git clone https://github.com/andriisolovei/golos.git
cd golos
python3.11 -m venv .venv        # or any python ≥ 3.11
.venv/bin/pip install -r requirements.txt
```

## macOS permissions (required, one-time)

macOS gates everything this app does. Grant **Terminal** (or iTerm, or whatever app
launches `./dictate.sh`) the following in **System Settings → Privacy & Security**:

1. **Microphone** — for audio capture.
2. **Input Monitoring** — for the global `fn` hotkey monitor.
3. **Accessibility** — for the synthetic Cmd+V paste and reading the focused window title.

Also: **System Settings → Keyboard → "Press 🌐/fn key to" → Do Nothing** —
otherwise pressing fn triggers macOS's own action (emoji picker / dictation)
and the app can't use it reliably.

After granting permissions, restart the terminal.

**First run opens an onboarding wizard** that walks all of this with live ✓/✗
checks (reopen anytime: menu-bar icon → "Welcome / Setup…").

**Note for the bundled app:** `dist/golos.app` is a *separate* macOS
identity from your terminal — you must grant the same three permissions to
**golos.app** itself (the wizard appears on its first run too).
(`dist/dictate.app` from earlier builds is superseded — delete it.)

## Data files

All mutable state lives in **`~/.golos/`**: `config.toml` (chmod 600 — it
holds the API key), `dictionary.txt`, `corrections.tsv`, `history.jsonl`,
`suggestions.jsonl`, `dismissed.jsonl`, `recordings/`, and `dictate.lock`.
On first launch after the rename, the dictate-era **`~/.dictate/`** set is
**copied** over (originals kept; only `samples/` stays in the project for
the bench harness).

## Build the .app + installer

```sh
./build_app.sh        # py2app -> dist/golos.app
./make_dmg.sh         # -> dist/golos-0.2.0.dmg (app + /Applications symlink)
```

Requires `py2app` and `setuptools<80` (in requirements.txt). The bundle is
unsigned — to run it: **right-click → Open** (Gatekeeper), then re-grant the
three permissions (Microphone, Input Monitoring, Accessibility) to
**golos.app** — it's a separate TCC identity from your terminal. The
onboarding wizard appears on first run and walks you through it. Signing +
notarization are the remaining steps for real distribution (docs/VISION.md).

## Install (from the DMG)

1. Open `dist/golos-0.2.0.dmg`, drag **golos** onto **Applications**.
2. First launch: right-click → **Open** (unsigned build).
3. Grant the three permissions to golos.app when the wizard asks.


## Run

```sh
cd ~/dictate
./dictate.sh            # start
./dictate.sh quit       # stop the running instance (pid verified via the lock)
./dictate.sh restart    # quit + start
```

Hold `fn`, speak, release. Text appears at the cursor of whatever app is frontmost.
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
pip install -e .          # from the project root; extras: [mlx] [mic] [app]
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

Click the mic icon in the menu bar → **Settings…**. The menu also has:

- **Test insertion** — pastes `✅ dictate insertion test` at the current cursor;
  a one-click end-to-end check of the Accessibility permission + paste path.
- **Permissions ▸** — live ✓/✗ for Accessibility, Input Monitoring and
  Microphone (refreshed each time the menu opens); clicking a ✗ item opens the
  matching System Settings pane. The same three checks run at startup and log
  loud ⚠ warnings with deep links for anything missing.

Four tabs (General, Prompt, Dictionary, History):

- **General** — STT backend (`mlx` on-device, or `openrouter`), STT model,
  **Languages** (comma-separated, e.g. `en, uk`; empty = auto-detect),
  formatter model, OpenRouter API key, bubble style (`notch` / `corner`),
  **Input sensitivity** slider (0.5–2.5 — display gain for the recording
  waveform; 1.0 default), the **Format with LLM** checkbox (uncheck for
  the fastest raw-insert mode — no formatting pass, no context leaves the
  machine), and **Fast mode** (skip LLM cleanup for short dictations —
  short inserts become instant, `corrections.tsv` still applies locally).
- **Prompt** — context-sharing toggles (what the formatter may see),
  the **Answer obvious questions from context** toggle, **Also send the
  audio to the formatter** (recover from bad transcription; costs a little
  more, needs an audio-capable model), and the system prompt template editor
  (`~/.golos/prompt.md`).
  **Fetch models** pulls the current OpenRouter model list (audio-capable
  models for STT, all text models for the formatter); it works without a key
  for listing, and the combo boxes keep your current values if the fetch fails.
  **Save** writes `config.toml` and rebuilds the STT/formatter pipeline live.
  Bubble style applies after restart.
- **Dictionary** — edit terms and corrections as tables (+/− to add/remove
  rows, double-click to edit inline); Save applies them to the running
  pipeline immediately. File comments (`#` lines) are preserved on save.
- **History** — newest-first table of past dictations (resizable columns,
  Raw → Final takes the spare width); click a row for the full text plus the
  context the formatter received.

## OpenRouter

The cloud features (STT backend `openrouter`, formatter provider `openrouter`)
use one key: set `[openrouter] api_key` in Settings, or export
`OPENROUTER_API_KEY` (the env var takes precedence). With no key at all the app
still works fully offline: local mlx STT, and stage-2 formatting is skipped
gracefully (raw transcript is inserted).

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
  over ~1.2 s. The panel is
  fully click-through: it never blocks your menus. Idle = no bubble at all.
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
the visible overlap instead of the whole insertion.

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
receives up to 500 chars of **text before the cursor** (to continue your
sentence naturally) and up to 1500 chars of **visible text** — when your
dictation comments on something you're reading, the formatter begins the
output with a short verbatim `> quote` of the referenced part, then your
comment. It never quotes text that isn't verbatim on screen.

Privacy note: nearby typed text (`text_before_cursor`), the visible text,
and page/workspace context leave the machine **only** when LLM formatting is
enabled — set `[formatting] enabled = false` (or uncheck "Format with LLM"
in Settings → General) for fully-local raw insertion; `[context] enabled =
false` turns the providers/AX reads off independently.

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

`config.toml` — see the shipped file for the annotated version. Highlights:

- `[hotkey]` — `hold_key = "fn"` or `"right_option"`;
  `toggle_combo = "fn+space"` or `"double_fn"` (double-tap the hold key within
  350 ms to lock recording; a hold over 400 ms is never a tap). fn+Space
  always toggles regardless of mode.
- `[stt]` — `backend = "mlx" | "openrouter" | "openai_compatible" | "deepgram"`.
- `[openrouter]` — `api_key` (env `OPENROUTER_API_KEY` wins).
- `[formatting]` — `provider = "openrouter" | "openai_compatible"`, `model`,
  and `debug = false`. Set `debug = true` to log the **complete system prompt
  and user message** (the full context the model receives: app, window title,
  page URL, workspace files, …) at INFO before every formatting call.
- `[bubble]` — `style = "notch" | "corner"`.
- `[insert]` — `method = "auto" | "type" | "paste"`. Auto types single-line
  text as synthetic keystrokes (no clipboard race) and uses clipboard paste
  only for multi-line text; the pasteboard keeps the transcript afterwards
  (`restore_clipboard = true` opts back into restoring it after 1.5 s).
- `[audio]` — `device = 0` uses the default input.

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
  settings.py     menu-bar status item (Permissions submenu, Test insertion) + Settings window
  onboarding.py   5-page first-run wizard (permissions, fn key, API key)
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
