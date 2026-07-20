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
| `hotkeys.py` | 4 hold keys (fn/right_option/right_command via flagsChanged; f5 via key events), CGEventTap swallowing Space + F5, double-tap detection, live rebind |
| `bubble.py` | notch strip (recording wings / processing shimmer / success hill / notice / cue) + corner pill (NSPanel status-level UI) |
| `context.py` | frontmost app/window/pid, text-before-cursor, normalized visible text (AX) |
| `providers.py` | per-app context: browser tab, VS Code workspace, Finder selection |
| `learning.py` | edit capture (AX) → suggestion pairs, promote/dismiss, async wrapper |
| `editwatcher.py` | live edit cues: 2.5 s polling for 3 min, debounce, cue firing (workers for AX reads) |
| `settings.py` | menu-bar status item (12-petal chakra glyph, 11 pt), Permissions submenu, 4-tab Settings window |
| `onboarding.py` | 7-page branded wizard (sidebar, radio cards, hotkey test pad, try-it field) |
| `permissions.py` | Accessibility/Input Monitoring/Microphone preflight + deep links |
| `insert.py` | single-line: synthetic keystrokes; multi-line: clipboard + Cmd+V (pasteboard keeps the transcript) |
| `history.py` | JSONL append (ts, app, bundle, raw, final, context, audio, fast) |
| `config.py` | tomllib read, toml write (`update_config`), char-array healing, `~/.golos` migration |
| `bench.py` | STT benchmark harness (`record` / `run`) |

## State machine

`idle → recording (fn held) → processing → idle`
`idle → locked (fn+Space or double-tap) → processing → idle` (single fn
press ends `locked`)

The lock is held on `AppController._lock`; the pipeline runs on a daemon
thread; state transitions are logged.

## Hotkeys: event tap vs monitor

Global `NSEvent` monitors are observe-only — the Space in fn+Space would
also type into the target app. So a `CGEventTap` (session-level, keyDown)
sits in front: if `should_consume(keycode, fn_held, flags)` — Space plus fn
held, or fn in the event's own flags — the callback returns `None`
(swallowing it) and fires the toggle; otherwise the event passes through.
The tap re-enables itself on `kCGEventTapDisabledByTimeout/UserInput`. If
creation fails (no Input Monitoring permission), the old observe-only
monitor remains as fallback and the startup log says which path is active.
Two flag domains are easy to confuse: CGEvent fn = `0x200000`,
NSEventModifierFlagFunction = `0x800000` — each path uses its own.

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
   Success flashes the bubble; the insertion is remembered for learning.
5. **History**: JSONL with the full context dict (`workspace_files`
   truncated to 50 lines).

## Learning gates (why suggestions aren't junk)

- **Anchor gate (v2, scroll-tolerant)**: matching-block coverage ≥ 50% of
  the visible overlap (field length when the input box scrolled the older
  part away, else insertion length) with the longest block ≥ 12 chars
  (≥ 8 chars requires ≥ 60%), else skip with an INFO log. The field text is
  normalized like visible_text first; the anchor is shrunk to word
  boundaries and only head/tail regions are diffed — never the whole field.
  A live **edit watcher** (`[learning] live_cues`) polls the field every
  2.5 s for 3 min after each insertion; a pair that survives two consecutive
  polls (user paused) becomes a clickable cue (`wrong → right ✓?` pill) —
  accepting promotes to corrections + dismisses it.
- **Similarity gate**: keep a pair only if `SequenceMatcher.ratio() ≥ 0.5`
  or one side contains the other; drop if either side > 6 tokens.
- Triggers: next recording, app switch (AX read of the old app's pid),
  45 s fallback timer, manual "Check for edits". Window: 600 s
  (`[learning] edit_window_seconds`).

## Security & privacy model

- **Local by default**: mlx STT on-device; with no API key nothing leaves
  the machine. `mlx-community/whisper-large-v3-turbo` is cached in
  ~/.cache/huggingface.
- **State** lives in `~/.golos/` (migrated from `~/.dictate` on first run
  after the rename, copy-once; config is chmod 600). The single-instance
  lock is `~/.golos/dictate.lock` (flock, released on process death). Raw
  audio archives to `~/.golos/recordings/YYYY-MM-DD/` unless
  `[audio] keep_recordings = false`.
- **What can leave**: the transcript and the formatter context (app, window
  title, tab URL, workspace file list, ≤500 chars before the cursor,
  ≤4000 chars of normalized visible text) — only when `[formatting] enabled = true`
  and a key is configured. Cloud STT sends the audio to OpenRouter when
  `backend = "openrouter"`.
- Off switches: `[formatting] enabled = false` (raw mode), `[context]
  enabled = false` (no providers/AX reads), `[learning] enabled = false`.
- The API key lives in `config.toml` (plain text, user-only) or
  `OPENROUTER_API_KEY` (env wins). History/suggestions are local JSONL.
- Permissions are preflighted at startup; the app never requests them
  programmatically — the user grants in System Settings.

## Config reference (`config.toml`)

| Key | Default | Notes |
|---|---|---|
| `[hotkey] hold_key` | `"fn"` | `fn` / `right_option` / `right_command` / `f5` (live rebind) |
| `[hotkey] toggle_combo` | `"fn+space"` | or `"double_fn"`; key+Space always works |
| `[stt] backend` | `"mlx"` | `mlx` / `openrouter` / `openai_compatible` / `deepgram` |
| `[stt] languages` | `[]` | e.g. `["en", "uk"]`; empty = auto-detect |
| `[stt] mlx_model` | `mlx-community/whisper-large-v3-turbo` | local model |
| `[stt.openrouter] model` | `deepgram/nova-3` | curated list in `openrouter.py` |
| `[openrouter] api_key` | `""` | env `OPENROUTER_API_KEY` wins |
| `[formatting] enabled` | `true` | the raw/formatted toggle |
| `[formatting] provider` | `"openrouter"` | or `"openai_compatible"` |
| `[formatting] model` | `google/gemini-2.5-flash` | any chat model |
| `[formatting] answer_questions` | `false` | guarded answer mode |
| `[formatting] send_audio` | `false` | attach original audio to the format call |
| `[formatting] fast_mode` / `fast_mode_max_words` | `false` / `10` | skip LLM for short dictations |
| `[formatting] debug` | `false` | logs the complete prompt |
| `[formatting] prompt_file` | `"prompt.md"` | custom system-prompt template in `~/.golos` |
| `[bubble] style` / `sensitivity` | `"notch"` / `1.0` | corner fallback / display gain 0.5–2.5 |
| `[learning] enabled` / `edit_window_seconds` | `true` / `600` | suggestion loop |
| `[learning] live_cues` / `live_cue_seconds` | `true` / `8` | click-to-keep edit cues |
| `[context] enabled` | `true` | providers + AX text reads |
| `[insert] method` / `restore_clipboard` | `"auto"` / `false` | type/paste override; clipboard restore escape hatch |
| `[audio] device` / `keep_recordings` | `0` / `true` | sounddevice index; wav archive |
| `[app] onboarded` | — | set by the wizard |
| `[paths] *` | `~/.golos/` | dictionary / corrections / history / suggestions / dismissed |

Config writes go through `update_config` (tomllib read → `toml` dump).
Gotcha that once bit us: `toml`'s encoder dispatches on exact `type(v)`, so
bridged `NSString`s (`objc.pyobjc_unicode`, a str subclass returned by
AppKit controls like `stringValue()`) were serialized as arrays of single
characters — the `pyobjc_unicode`/toml bug class. `update_config` now
sanitizes str-subclasses to plain `str`, and `load_config` heals legacy
char-arrays back into strings.
