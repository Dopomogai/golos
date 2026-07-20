---
@purpose: "Technical architecture of golos: module map, state machine, hotkeys, bubble UI, and pipeline boundaries."
@why: "Prevents architecture guesswork when changing dictate/dictate_core or debugging OS integration."
@role: reference
@stability: accepted
@tags: [golos, architecture, tech, pyobjc, dictate]
related_docs: [docs/GUIDE.md, docs/VISION.md, README.md]
---
# golos — technical architecture

A single Python process (PyObjC) runs an NSApplication run loop. Worker
threads handle record → STT → format → paste; all UI work is marshalled to
the main thread with `PyObjCTools.AppHelper.callAfter/callLater`.

## Module map (`dictate/`)

The UI-free brain lives in **`dictate_core/`** (`stt.py`, `formatter.py`,
`openrouter.py`, `dictionary.py`, `recorder.py`, `learning.py` pure helpers,
plus the `VoicePipeline` facade) — zero AppKit, pip-installable
(`pip install -e .`, extras `[mlx]`/`[mic]`/`[app]`). The `dictate/` package
keeps the shims + everything with UI or OS integration:

| Module | Role |
|---|---|
| `__main__.py` | entry: logging, load config, `run_app` |
| `app.py` | NSApplication setup, `AppController` state machine, instance lock, app-switch observer, threading boundaries |
| `hotkeys.py` | 4 hold keys (fn/right_option/right_command via CGEventTap flagsChanged when active, NSEvent fallback; f5 via key events), CGEventTap swallowing Space + F5, double-tap detection, live rebind |
| `bubble.py` | notch strip (recording wings / processing shimmer / success hill / notice / cue) + corner pill (NSPanel status-level UI) |
| `context.py` | frontmost app/window/pid; focused-field text, text-before-cursor, surrounding visible text (AX; roles kept separate) |
| `providers.py` | per-app context: browser tab, VS Code workspace, Finder selection |
| `learning.py` | edit capture (AX) → suggestion pairs, promote/dismiss, async wrapper |
| `learning_reviewer.py` (core) | optional OpenRouter multimodal review after stable edits |
| `editwatcher.py` | live edit cues: 2.5 s polling for 3 min, debounce, cue firing (workers for AX reads) |
| `settings.py` | menu-bar status item (chakra template glyph, 14 pt; `mic.fill` fallback), Permissions submenu, 5-tab Settings (History first/default); **Fetch models** lives on General |
| `onboarding.py` | 7-page branded wizard (welcome → permissions → hold key → OpenRouter/local → formatting → try it → done) |
| `permissions.py` | Accessibility/Input Monitoring/Microphone preflight + deep links |
| `insert.py` | single-line: synthetic keystrokes; multi-line: clipboard + Cmd+V (pasteboard keeps the transcript); returns True after events are **posted**, not after target-app delivery |
| `history.py` | JSONL append + durable recovery (ts, app, bundle, raw, final, context, audio, fast, schema_version/run_id/stage/status/error/attempts); load/normalize/copy_ready/retry helpers |
| `config.py` | tomllib read, toml write (`update_config`), char-array healing, `~/.golos` migration |
| `bench.py` | STT benchmark harness (`record` / `run`) |

## State machine

`idle → recording (fn held) → processing → idle`
`idle → locked (fn+Space or double-tap) → processing → idle` (single fn
press ends `locked`)

The lock is held on `AppController._lock`; the pipeline runs on a daemon
thread; state transitions are logged. **`_lock` is never held across network
I/O** (STT/format) — only short critical sections at hotkey boundaries.

### Pipeline ownership (live vs History retry)

Live dictation and History retries share the same STT + formatter instances.
`AppController` coordinates them with a second short lock
(`_pipeline_coord` / `_pipeline_owner`):

| Owner | Acquired by | Released |
|---|---|---|
| `live` | `_pipeline` before STT/format | `finally` after the worker body |
| `history_retry` | `retry_failed_stage` before work | `finally` after the retry body |

Acquisition is a flag set under a short critical section — **never** held
across STT/format network I/O. History retry also refuses while state is
`recording` / `locked` / `processing`. Desired UX:

- Retry while live owns the pipeline (or is mid-recording/processing) →
  `busy=True`, **no** history attempt line written.
- Hotkey while a History retry owns the pipeline → do not start recording;
  idle-safe notice `History retry is still running`.
- Immediate re-press after a successful insertion is unchanged (success →
  recording).

### History home grouping

Settings History home loads via `load_history_home` /
`group_history_for_home`: **one derived latest row per `run_id`** using the
same merge semantics as `latest_view_for_run` / `merge_attempt_views`.
Legacy lines without `run_id` stay individual. On-disk JSONL is append-only
— grouping is display-only. When `attempts_count > 1`, the detail pane
shows the attempt count.

### Partial success feedback

When the formatter falls back to raw but insert succeeds (`status=partial`),
the bubble success state uses label **`✓ inserted raw`** (green hill / fade
lifecycle unchanged). With `[bubble] show_text = false` the animation still
runs; the text is suppressed as usual. Full format success still shows
`✓ inserted`.

## Hotkeys: event tap vs monitor

Global `NSEvent` monitors are observe-only — the Space in fn+Space would
also type into the target app. So a `CGEventTap` (session-level,
keyDown/keyUp/**flagsChanged**) sits in front:

- **Modifier hold keys** (`fn` keycode 63, `right_option` 61,
  `right_command` 54): delivered on the tap's `flagsChanged` path, filtered
  by that keycode + the matching CGEvent flag mask. Events pass through
  (not swallowed). While the tap is active the NSEvent `flagsChanged`
  handler no-ops so press/release never double-fire.
- **Space combo**: if `should_consume(keycode, fn_held, flags)` — Space plus
  hold key held, or SecondaryFn in the event's own flags — the callback
  returns `None` (swallowing down *and* up) and fires toggle on keyDown only.
- **F5** as hold key: both keyDown and keyUp are swallowed.

Fn flag mask is `kCGEventFlagMaskSecondaryFn == 0x800000` (same numeric
value as `NSEventModifierFlagFunction`). The old `0x200000` literal was
wrong and broke the event-local Space fallback.

On `kCGEventTapDisabledByTimeout/UserInput` the tap re-enables itself and,
if `_fn_held` is still true, forces a single release so a missed modifier-up
cannot leave recording stuck or make the next press a permanent no-op. If
tap creation fails (no Input Monitoring permission), the observe-only
NSEvent monitors remain as fallback and the startup log says which path is
active.

`toggle_combo = "double_fn"`: taps are classified by the pure function
`double_tap_decision` (tap ≤ 400 ms, gap ≤ 350 ms). While locked, hold-key
down routes straight to `on_press` with no tap bookkeeping, so stop-on-press
works in both modes. The hold key is configurable
(`fn`/`right_option`/`right_command` flagsChanged, `f5` key events — F5 is
consumed by the tap while configured) and rebinding is live via
`HotkeyMonitor.reconfigure`.

## Bubble UI

- Panels are borderless, non-activating `NSPanel`s at `NSStatusWindowLevel`
  (above the menu bar) with `CanJoinAllSpaces | Stationary |
  FullScreenAuxiliary` (= 256 on this SDK, resolved by name with numeric
  fallback) so they render over fullscreen apps, and
  `setHidesOnDeactivate_(False)` so they survive focus in other apps.
- **Strip** (notch style): a click-through panel (`ignoresMouseEvents`)
  spanning the notch ± 184 pt, 48 pt tall over the menu row, content centered
  on the 32 pt menu row. 26 bars/side, most-recent EMA-smoothed RMS
  (`0.5·old + 0.5·new`) at the notch, red→orange gradient with edge dissolve,
  identical round dots while silent, display gain via `[bubble] sensitivity`.
  One surface for all states: recording = red waveform; processing = blue
  traveling shimmer with distance-decaying crests, breathing amplitude, and
  an animated `processing… Ns` label in the notch gap; success = a green hill
  (`cos^0.9` envelope × time ebb over ~1.2 s); notices/cues = faint bars +
  text (the cue uses the clickable pill instead). On stop, bars collapse
  outside-in over 0.2 s before the strip returns in blue. Idle = hidden.
- **Pill**: 150×24 inside the 32 pt menu row, centered under the notch —
  corner style's whole UI, and the notch style's interactive surface for
  edit cues (`wrong → right ✓?`, click to accept). Its style mask includes
  `NSWindowStyleMaskNonactivatingPanel` so clicks don't steal focus.
- ObjC classes are defined once per process (class names are global) and
  always use `objc.super` — both were learned the hard way.

## Pipeline detail

1. **Recording starts instantly** (start is the tolerated main-thread fast
   path); a worker captures the formatter context (frontmost app, window
   title, pid, provider results, AX reads — skipped when formatting is
   disabled) and the pipeline waits on it (Event, 3 s timeout, then proceeds
   empty). Stream stop happens only on worker threads — stopping CoreAudio
   on the main thread once deadlocked the app (HALB mutex vs IO thread), so
   stop/abort are lock-guarded and idempotent. The same rule covers AX reads
   (edit capture, edit watcher polls): workers do the reads, results bounce
   to main.
2. **STT**: dictionary terms bias recognition — `initial_prompt` for
   mlx-whisper, `prompt` for OpenRouter's `/audio/transcriptions` (JSON body
   `{model, input_audio:{data: base64 wav, format}, prompt}` — verified
   against the live API; multipart is *not* accepted there).
3. **Formatting** (`{base}/chat/completions`): system prompt from a
   template (`{{mode_rules}}` framing by `[formatting] answer_questions` —
   hardened transcribe-only vs guarded answer mode — plus
   `{{dictionary}}/{{corrections}}/{{context_block}}/{{context_rules}}`;
   `~/.golos/prompt.md` overrides, prepend/append keeps the mode toggle
   working). `[formatting] send_audio` attaches the original wav as an
   `input_audio` content part for garbled-transcript recovery. Short
   single-line dictations skip the LLM entirely in `[formatting] fast_mode`
   (literal local corrections instead). No key or any failure → raw
   transcript, logged. STT languages are narrowed via `[stt] languages`
   (deepgram `multi`, whisper code/prompt-hint, mlx single-language).
4. **Insert**: single-line text is typed as synthetic keystrokes
   (CGEventKeyboardSetUnicodeString, ~40 chars/event — no pasteboard race).
   Multi-line text: pasteboard set → 60 ms settle → synthetic Cmd+V → done;
   the pasteboard keeps the transcript (restoring raced slow target apps
   into pasting the OLD clipboard — Universal Clipboard stalls;
   `restore_clipboard = true` restores after 1500 ms as an escape hatch).
   Success flashes the bubble after events are posted (not app-confirmed
   delivery); the insertion is remembered for learning.
5. **History / recovery**: append-only JSONL (`~/.golos/history.jsonl`) with
   the full context dict (`workspace_files` truncated to 50 lines). Schema
   v2 adds recovery fields while remaining backward compatible with legacy
   success lines (no `schema_version`):

   | Field | Notes |
   |---|---|
   | `schema_version` | `2` for new writes; missing → treated as legacy success |
   | `run_id` / `attempt` / `kind` | stable run id; `attempt` 0 = original, retries append `kind=attempt` |
   | `stage` | `stt` \| `format` \| `insert` \| `complete` |
   | `status` | `success` \| `failed` \| `cancelled` \| `partial` |
   | `error` | failure message when `status=failed` |
   | `audio` / `audio_retained` | retained WAV path only when `[audio] keep_recordings`; never secret retention |
   | `format_fallback` | true when formatter raised and raw was used |

   Failures at STT / insert (including a non-trivial capture that returns an
   empty transcript) are written immediately so a dictation does not
   disappear. Success history is written **after** insert confirms (not when
   insert is merely scheduled). Formatter soft-failures return raw, insert it,
   and write `status=partial` + `format_fallback=true`.
   **Processing-stage Esc** (cancel after STT/formatting, before insert)
   appends one schema-v2 line with the same `run_id`, `status=cancelled`,
   `stage=insert`, and honest `raw` / `final` / context / audio / `fast` /
   `format_fallback` — never inserts, returns to idle. **Recording-stage Esc**
   remains a pure abort/discard with no history line.
   Retries (`AppController.retry_failed_stage`)
   append new attempt lines and **never** rewrite the original failure.
   Default retry does **not** re-insert into the frontmost app — copy-ready
   text is returned for an explicit UI action (`insert=True` is the only
   paste path, documented as current-focus only).
   Settings runs retries on a worker, then refreshes History; its UI exposes
   Copy text and Show audio but never automatic re-insertion.

## Learning gates (why suggestions aren't junk)

- **Anchor gate (v2, scroll-tolerant)**: matching-block coverage ≥ 50% of
  the visible overlap (field length when the input box scrolled the older
  part away, else insertion length) with the longest block ≥ 12 chars
  (≥ 8 chars requires ≥ 60%). When the longest exact block is under 8 chars,
  a short whole-field path still accepts near-misses if the field *is* the
  recent short insertion (both ≤ 64 chars, length ratio ≤ 2, overall
  similarity ≥ 0.5); embedded short text in large fields still needs the
  8/12-char anchor. Otherwise skip with an INFO log. The field text is
  normalized like visible_text first; the anchor is shrunk to word
  boundaries and only head/tail regions are diffed — never the whole field
  (except the short whole-field path above). The 8/12 floor is an **anchor
  location** threshold only — replacement **tokens** only need ≥ 2 chars, so
  a 5-character proper name (Mercy→Mercey) in a long paragraph is valid.
  When the field has trailing chrome after a short edit, unbalanced replace
  blocks fall back to per-token near-miss alignment so signature/UI text is
  not swallowed into the pair.
  A live **edit watcher** (`[learning] live_cues`) polls the field every
  1.0 s for 3 min after each insertion; a pair that survives two consecutive
  polls (user paused) becomes a clickable cue (`wrong → right ✓?` pill) —
  accepting promotes to corrections + dismisses it.
- **Similarity gate**: keep a pair only if `SequenceMatcher.ratio() ≥ 0.5`
  or one side contains the other; drop if either side > 6 tokens.
- **Optional learning reviewer** (`[learning] reviewer_enabled`, default
  **false**): after a stable manual edit, an independent OpenRouter chat
  model may propose structured `{wrong, right, confidence}` candidates
  from raw + inserted + edited text and, when
  `[learning] reviewer_send_audio` and a retained WAV path exist, the
  original audio (`input_audio`). Validation requires wrong ∈ raw/inserted,
  right ∈ edited, length bounds, and min confidence; audio may accept
  low string-similarity pairs (e.g. alarm→LLM). **Never auto-promotes.**
  At most one reviewer attempt per insertion; independent of formatter /
  fast mode. On disable, missing key, missing WAV with text-only, API
  error, malformed JSON, or empty candidates → deterministic
  `suggest_pairs` fallback. Credible reviewer hits play a violet/amber
  “suggestion ready” animation before the interactive cue.
- Triggers: next recording, app switch (AX read of the old app's pid),
  45 s fallback timer, manual "Check for edits". Window: 600 s
  (`[learning] edit_window_seconds`).

## Security & privacy model

- **Cloud-first, explicit local option**: OpenRouter is the shipped STT
  backend. On Apple Silicon, the user can explicitly download the optional
  MLX weights into `~/.cache/huggingface`; Intel/cloud-only builds omit MLX.
- **State** lives in `~/.golos/` (migrated from `~/.dictate` on first run
  after the rename, copy-once; config is chmod 600). The single-instance
  lock is `~/.golos/dictate.lock` (flock, released on process death). Raw
  audio archives to `~/.golos/recordings/YYYY-MM-DD/` unless
  `[audio] keep_recordings = false`.
- **What can leave**: the transcript and the formatter context (app, window
  title, tab URL, workspace file list, ≤500 chars before the cursor,
  ≤4000 chars of focused field text, ≤4000 chars of surrounding visible
  text — never PID) — only when `[formatting] enabled = true` and a key is
  configured. Cloud STT sends the audio to OpenRouter when
  `backend = "openrouter"`. The optional learning reviewer may send a
  bounded edit excerpt (and a retained WAV when `reviewer_send_audio`)
  only if `[learning] reviewer_enabled = true`.
- Off switches: `[formatting] enabled = false` (raw mode), `[context]
  enabled = false` (no providers/AX reads), per-field `[context]` toggles
  (`focused_field_text`, `visible_text`, `text_before_cursor`, …),
  `[learning] enabled = false`, `[learning] reviewer_enabled = false`
  (default).
- The API key lives in `config.toml` (plain text, user-only) or
  `OPENROUTER_API_KEY` (env wins). History/suggestions are local JSONL.
- Permissions are preflighted at startup; the app never requests them
  programmatically — the user grants in System Settings.

## Config reference (`config.toml`)

Public end-user UI maps are in the Help Center
([Settings](https://golos.dopomogai.com/docs/settings/)); this table is the
code/config contract. **config-only** = no Settings control in v0.3.1.

| Key | Default | Notes |
|---|---|---|
| `[hotkey] hold_key` | `"fn"` | UI: General; `fn` / `right_option` / `right_command` / `f5` (live rebind) |
| `[hotkey] toggle_combo` | `"fn+space"` | **config-only**; or `"double_fn"`; hold+Space always works |
| `[stt] backend` | `"openrouter"` | `openrouter` / `mlx` (Apple Silicon) / advanced `openai_compatible` / `deepgram` |
| `[stt] languages` | `[]` | e.g. `["en", "uk"]`; empty = auto-detect |
| `[stt] mlx_model` | `mlx-community/whisper-large-v3-turbo` | local model; Intel builds omit MLX |
| `[stt.openrouter] model` | `deepgram/nova-3` | curated list in `openrouter.py` |
| `[openrouter] api_key` | `""` | env `OPENROUTER_API_KEY` wins |
| `[formatting] enabled` | `true` | the raw/formatted toggle (UI) |
| `[formatting] provider` | `"openrouter"` | or `"openai_compatible"` |
| `[formatting] model` | `google/gemini-2.5-flash` | code default; any chat model |
| `[formatting] answer_questions` | `false` | guarded answer mode |
| `[formatting] send_audio` | `false` | attach original audio to the format call |
| `[formatting] fast_mode` | `false` | UI checkbox |
| `[formatting] fast_mode_max_words` | `10` | **config-only** short-dictation cutoff |
| `[formatting] debug` | `false` | **config-only**; logs the complete prompt |
| `[formatting] prompt_file` | `"prompt.md"` | custom system-prompt template in `~/.golos` |
| `[bubble] style` / `sensitivity` / `show_text` | `"notch"` / `1.0` / `true` | corner fallback / display gain 0.5–2.5 / animation-only option |
| `[learning] enabled` / `edit_window_seconds` | `true` / `600` | **config-only** suggestion loop master + window |
| `[learning] live_cues` / `live_cue_seconds` | `true` / `8` | **config-only** click-to-keep edit cues |
| `[learning] reviewer_enabled` | `false` | UI: Learning; optional OpenRouter post-edit review |
| `[learning] reviewer_model` | `google/gemini-3.1-flash-lite-preview` | independent of formatter model |
| `[learning] reviewer_send_audio` | `true` | attach retained WAV when reviewing (audio leaves Mac) |
| `[learning] reviewer_prompt_file` | `learning_prompt.md` | under `~/.golos/` |
| `[learning] reviewer_min_confidence` | `0.55` | drop lower-confidence candidates |
| `[context] enabled` | `true` | providers + AX text reads |
| `[context] focused_field_text` | `true` | full focused-input draft (≤4000) |
| `[context] visible_text` | `true` | surrounding on-screen text only (≤4000) |
| `[context] text_before_cursor` | `true` | pre-caret slice (≤500) |
| `[insert] method` / `restore_clipboard` | `"auto"` / `false` | **config-only** type/paste override; clipboard restore escape hatch |
| `[audio] device` / `keep_recordings` | `0` / `true` | **config-only** sounddevice index; wav archive |
| `[app] onboarded` | — | set by the wizard |
| `[paths] *` | `~/.golos/` | dictionary / corrections / history / suggestions / dismissed |

**Fully local** product meaning (not a single toggle): Apple Silicon MLX STT
with local weights downloaded, `[formatting] enabled = false`, and
`[learning] reviewer_enabled = false`.

Config writes go through `update_config` (tomllib read → `toml` dump).
Gotcha that once bit us: `toml`'s encoder dispatches on exact `type(v)`, so
bridged `NSString`s (`objc.pyobjc_unicode`, a str subclass returned by
AppKit controls like `stringValue()`) were serialized as arrays of single
characters — the `pyobjc_unicode`/toml bug class. `update_config` now
sanitizes str-subclasses to plain `str`, and `load_config` heals legacy
char-arrays back into strings.
