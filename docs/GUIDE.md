---
@purpose: "Complete operator guide for driving golos: controls, pipeline, models, dictionary, and settings."
@why: "One verified how-to source so day-to-day use is not inferred from partial README or product blurbs."
@role: reference
@stability: accepted
@tags: [golos, guide, user-guide, controls, pipeline]
related_docs: [docs/PRODUCT.md, docs/TECH.md, README.md]
---
# golos — the complete guide

Everything the app does, and how to drive it. Verified against the current code.

## What it is

golos is a menu-bar dictation app: hold a key, speak, release — cleaned-up
text appears at the cursor of whatever app you're in. Local-first (on-device
Whisper by default), with optional cloud STT and an LLM formatting pass.
It runs as an accessory app (no Dock icon) with a status-bar chakra icon.

## Controls

| Input | Action |
|---|---|
| Hold `fn` | Push-to-talk. Release to transcribe + insert. |
| `fn`+Space | Lock recording hands-free. |
| `fn` (single press, while locked) | Stop locked recording, transcribe + insert. |
| `fn`+Space (while locked) | Same — also stops. |
| Double-tap `fn` (if `toggle_combo = "double_fn"`) | Toggle locked mode (fn+Space always works too). |
| `Esc` (while recording/locked) | **Cancel**: discard the audio, no transcription. |
| `Esc` (while processing) | Discard the result before it inserts (if insertion already started, it's too late). |

`hold_key` is user-selectable: `fn` (default), `right_option`,
`right_command`, or `f5` — changeable in Settings and rebound live (no
restart). F5 is fully swallowed by the event tap while it's the hold key.
The Space in the combo is swallowed by the same tap (observe-only fallback
otherwise).

## The notch strip (status UI)

On notched MacBooks, everything happens on a click-through strip spanning
the camera notch in the menu-bar row (content centered on the 32 pt menu
row, bars capped at 34 pt so nothing leaves the screen top):

- **Recording / locked**: red→orange waveform wings emanating from both
  notch edges, newest audio at the notch, dissolving outward.
- **Processing**: wings collapse inward (~0.2 s), then the strip returns in
  blue — a traveling shimmer plus an animated `processing… 4s` label in the
  notch gap (elapsed seconds after 3 s).
- **Success**: a green `✓ inserted` hill — tallest at the notch, tapering
  outward across nearly the full strip — that ebbs away over ~1.2 s.
- **Idle**: nothing. No bubble at all. Silence while recording shows a
  perfectly even dotted line.

On machines without a notch (`[bubble] style = "corner"`), a small
draggable pill at the bottom-right shows the same states.

## The two-stage pipeline

1. **STT** — 16 kHz mono audio → transcript. Your `dictionary.txt` terms
   bias recognition (`initial_prompt` for mlx, `prompt` for OpenRouter), so
   your vocabulary is spelled right from the start.
2. **Formatting LLM** — removes fillers and false starts, fixes punctuation,
   splits paragraphs at topic shifts, turns enumerations into real
   numbered/bulleted lists, applies `corrections.tsv` exactly, resolves
   spoken filenames via context, adapts tone to the target app, and can
   cite the visible text (see below). Skipped gracefully when disabled or
   keyless — the raw transcript is inserted.

Every dictation is saved (`~/.golos/recordings/YYYY-MM-DD/HHMMSS_mmm.wav`,
disable with `[audio] keep_recordings = false`) — these are ready-made
samples for the benchmark harness; copy or symlink them into `samples/`.

## Models

- **Local (default)**: `mlx-community/whisper-large-v3-turbo` on-device via
  mlx-whisper. Free, private, ~1.5 GB one-time download.
- **Cloud via OpenRouter**: 9 curated transcription ids (in
  `dictate/openrouter.py`, verified against the live API) — default
  `deepgram/nova-3`; also qwen3-asr, chirp-3, parakeet, voxtral-mini-transcribe,
  mai-transcribe, whisper-1, gpt-4o(-mini)-transcribe.
- **Benchmark on your voice**: `python -m dictate.bench record NAME` (mic
  until Enter → `samples/NAME.wav` + draft `.txt`), then
  `python -m dictate.bench run [--models a,b] [--verbose]` — table of
  WER vs latency per model.

## Dictionary, corrections, and learning

- `dictionary.txt`: one term per line — fed to STT biasing and the formatter.
- `corrections.tsv`: `wrong<TAB>right` per line — applied verbatim by the formatter.
- Edit both in Settings → Dictionary (tables with +/−, Save applies live).
- **Learning loop**: when you fix an insertion by hand, dictate notices.
  Capture triggers: your next recording, switching away from the app, a 45 s
  fallback timer, and the "Check for edits" button. Two gates keep junk out:
  the insertion must be verifiably present (scroll-tolerant anchor — ≥ 50 %
  coverage of the visible overlap, longest common block ≥ 12 chars, or ≥ 8
  with stricter coverage; short whole-field near-misses when the field is
  essentially the recent short insertion) and each pair must look like a
  near-miss (similarity ≥ 0.5 or containment, ≤ 6 tokens).
  A live **edit watcher** also polls the field for 3 min after each insertion:
  pause after a manual fix and a clickable cue pill (`wrong → right ✓?`)
  appears — click to keep the correction instantly (`[learning] live_cues`).
  Pairs aggregate in Settings → History → Suggestions: **Add to corrections**,
  **Add to dictionary**, or **Dismiss**. Menu item "Add selection to
  dictionary" teaches a selected word instantly.
- **Optional learning reviewer** (Settings → Learning, off by default): when
  enabled, an independent OpenRouter model can re-check a stable edit using
  the raw transcript, inserted text, your edit, and optionally the original
  WAV (`reviewer_send_audio` — **audio leaves the Mac** when on and a
  recording was kept). Suggestions still require your click; nothing is
  auto-learned. If the reviewer is off, errors, or finds nothing, the
  deterministic text-diff path still runs.

## App context & citation mode

When `[context] enabled = true`, the formatter receives, per app:

- **Browsers** (Safari/Chrome/Brave/Edge/Arc): current tab title + URL.
- **VS Code**: workspace folder (from the window title, located under ~,
  ~/Documents, ~/Documents/GitHub, ~/Projects) + up to 200 files.
- **Finder**: front window + selection paths.
- **Everywhere**: app name, bundle id, window title, up to 500 chars of
  **text before the cursor** (to continue your sentence), and up to 4000
  chars of normalized **visible text** (box-drawing glyphs stripped, space
  runs collapsed). When your dictation comments on the visible text, the
  formatter starts the output with a short verbatim `> quote`, then your
  comment; it never quotes text that isn't on screen.

**Privacy**: context and transcripts leave the machine only when LLM
formatting is enabled. `[formatting] enabled = false` (or the Settings
checkbox) = fully local raw mode. `[context] enabled = false` disables the
providers and text reads independently.

## Insertion

- **Single-line text** is *typed* as synthetic keystrokes (40-char chunks) —
  no pasteboard, no races.
- **Multi-line text** is pasted via the clipboard + synthetic Cmd+V. The
  pasteboard **keeps the transcript** afterwards (like mainstream dictation
  apps): restoring the old clipboard raced slow apps into pasting that old
  content. Escape hatch: `[insert] restore_clipboard = true` (restores after
  1.5 s, with a warning logged).
- `[insert] method = "auto" | "type" | "paste"` overrides the per-text choice.

## Settings (menu-bar chakra icon)

The status item shows the golos chakra glyph (a template image that adapts
to light/dark menu bars; SF Symbol fallback if the file is missing).

- **General**: STT backend (mlx / openrouter), STT + formatter models
  (combo, "Fetch models" refreshes from OpenRouter), **Languages** (comma-
  separated, e.g. `en, uk`), API key field, bubble style, **Hold-to-talk
  key** popup (fn / Right Option / Right Command / F5), **Input sensitivity**
  slider (0.5–2.5, display gain for the recording waveform), **Format with
  LLM** checkbox (raw mode when off), **Fast mode** checkbox (short
  dictations skip the LLM), Save applies live.
- **Dictionary**: terms table + corrections table (+/−, inline edit, Save).
- **History**: every dictation (newest first, resizable columns) with the
  full raw/final/context detail; Suggestions table with promote/dismiss;
  Check-for-edits and Refresh buttons.
- **Prompt**: context-sharing checkboxes (what may reach the formatter) and
  the system-prompt template editor (placeholders
  {{dictionary}} {{corrections}} {{context_block}} {{context_rules}}).
- Menu: Settings…, Welcome / Setup…, Test insertion, Add selection to
  dictionary, Permissions ▸ (live ✓/✗ + deep links), Quit.
- **Onboarding**: 7-page branded wizard (dark sidebar with page dots:
  welcome → permissions with live checks → hold-key select with a live test
  pad → API key → formatting radio cards → try-it practice field → done) on
  first run; reopen from the menu.

## Permissions (all three required)

Microphone, Input Monitoring, Accessibility — granted in System Settings →
Privacy & Security to the terminal **or** to dictate.app (separate
identities; the bundled app needs its own grants). Also set System
Settings → Keyboard → "Press 🌐/fn key to" → **Do Nothing**. The app checks
at startup and in the Permissions submenu.

## Installing (until notarization)

```sh
./build_app.sh                      # py2app -> dist/golos.app (~280 MB)
./make_dmg.sh                       # -> dist/golos-0.2.0.dmg (~126 MB)
```

**Install from the DMG**: open it, drag **golos** onto **Applications**,
first launch **right-click → Open** (unsigned build), then grant Microphone /
Input Monitoring / Accessibility to **golos.app** (separate TCC identity from
your terminal — the onboarding wizard walks you through it).
`./dictate.sh quit` only manages the terminal-started instance; quit the .app
from its menu-bar icon.
Build notes: requires `setuptools<80`; `build_app.sh` temporarily hides
`pyproject.toml` during the build (py2app rejects its dependency list).

## Process control

```sh
./dictate.sh            # start (flock-guarded, one instance)
./dictate.sh quit       # stop the running instance (stale locks are cleaned)
./dictate.sh restart
```

- Ctrl+C / SIGTERM shut the app down cleanly (~0.5 s, logged).
- **Ctrl+Z is not quit** — a suspended process still holds the lock. If you
  see `golos is already running (pid N)`, run `./dictate.sh quit` (or
  `restart`); stale pid files are removed automatically.
- State lives in `~/.golos/` (config 600, dictionary, corrections,
  history, suggestions, recordings, lock). The project dir only ships
  defaults + `samples/`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Old clipboard pasted instead of transcript | pasteboard restore raced the app | Fixed: clipboard now keeps the transcript (update) |
| Nothing inserted at all | Accessibility missing | Permissions submenu → grant, restart app |
| fn+Space types a space | event tap inactive (no Input Monitoring) | Grant Input Monitoring; startup log shows the path |
| "animation just disappears" after stopping | old pill-in-menu-bar design | Fixed: strip now shows blue processing shimmer (update) |
| `golos is already running (pid N)` | Ctrl+Z-suspended instance | `./dictate.sh restart` (stale locks auto-cleaned) |
| No bubble ever | idle is hidden by design | It appears only while recording/processing/success |
| No bubble in fullscreen apps | — | Fixed: panels carry FullScreenAuxiliary (update) |
| Junk in Suggestions | mis-anchored edit diffs | Fixed by anchor+similarity gates (update); Dismiss the rest |
| Bubble visible but no transcription | check logs: STT backend error? | `dictate.sh` logs to stdout; verify API key / model id |

## Config reference (`~/.golos/config.toml`)

| Key | Default | Meaning |
|---|---|---|
| `[hotkey] hold_key` | `"fn"` | or `"right_option"` |
| `[hotkey] toggle_combo` | `"fn+space"` | or `"double_fn"` |
| `[stt] backend` | `"mlx"` | `mlx` / `openrouter` / `openai_compatible` / `deepgram` |
| `[stt] languages` | `[]` | e.g. `["en", "uk"]`; empty = auto-detect |
| `[stt] mlx_model` | `whisper-large-v3-turbo` | local model repo |
| `[stt] language` | `""` | empty = auto |
| `[stt.openrouter] model` | `deepgram/nova-3` | curated list in openrouter.py |
| `[openrouter] api_key` | `""` | env `OPENROUTER_API_KEY` wins |
| `[formatting] enabled` | `true` | off = raw mode |
| `[formatting] provider` | `"openrouter"` | or `"openai_compatible"` |
| `[formatting] model` | `google/gemini-2.5-flash` | formatter model |
| `[formatting] send_audio` | `false` | attach the original audio to the format call |
| `[formatting] answer_questions` | `false` | answer obvious questions from context |
| `[formatting] fast_mode` / `fast_mode_max_words` | `false` / `10` | skip LLM for short dictations |
| `[formatting] debug` | `false` | true = log the complete prompt |
| `[bubble] style` | `"notch"` | or `"corner"` (restart to apply) |
| `[bubble] sensitivity` | `1.0` | waveform display gain, 0.5–2.5 |
| `[learning] enabled` / `edit_window_seconds` | `true` / `600` | suggestion loop |
| `[learning] live_cues` / `live_cue_seconds` | `true` / `8` | click-to-keep edit cues |
| `[learning] reviewer_enabled` | `false` | optional post-edit OpenRouter review |
| `[learning] reviewer_model` / `reviewer_send_audio` | audio-capable default / `true` | independent model; audio leaves Mac when on |
| `[learning] reviewer_prompt_file` / `reviewer_min_confidence` | `learning_prompt.md` / `0.55` | editable prompt + confidence floor |
| `[context] enabled` | `true` | providers + AX text reads |
| `[insert] method` | `"auto"` | `auto` / `type` / `paste` |
| `[insert] restore_clipboard` | `false` | true = restore old clipboard after 1.5 s |
| `[audio] device` | `0` | sounddevice input index |
| `[audio] keep_recordings` | `true` | save wav per dictation |
| `[app] onboarded` | — | set by the wizard |
| `[paths] *` | `~/.golos/` | dictionary / corrections / history / suggestions / dismissed |

## Embedding: dictate_core

The UI-free pipeline is a sibling package (`dictate_core`, zero AppKit):

```python
from dictate_core import VoicePipeline

vp = VoicePipeline()          # key: arg > OPENROUTER_API_KEY > ~/.golos/config.toml
text = vp.process(open("clip.wav", "rb").read(), app_name="Slack")
pairs = vp.suggest_corrections("wisper flow", "Wispr Flow")
```

`pip install -e .` (extras `[mlx]`, `[mic]`, `[app]`). See README →
"Use dictate as a library".
