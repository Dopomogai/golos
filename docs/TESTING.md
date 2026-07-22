---
@purpose: "Honest automated test and coverage foundation for golos: tiers, commands, baseline, gaps, manual smoke."
@why: "Separates pure/headless confidence from macOS hardware/UI integration that needs a signed app, permissions, mic, and real targets."
@role: reference
@stability: draft
@tags: [golos, testing, coverage, pytest]
related_docs: [docs/TECH.md, README.md, RELEASE_CHECKLIST.md]
---

# Testing guide

This document describes the **reproducible automated test foundation** for
golos (`dictate` + `dictate_core`). It does **not** claim full coverage.

| Layer | What it proves | What it does **not** prove |
|---|---|---|
| **Pure / unit** | Learning, dictionary, formatter prompts/local corrections, WAV/STT helpers, OpenRouter key helpers | Live STT/LLM quality, mic capture |
| **Headless app state** | Idle/recording/locked/processing/success transitions, stale timers, cancel | Real NSApplication run loop |
| **Hotkey matrix** | fn/right modifiers, F5, Space swallow, tap recovery, monitor fallback | Input Monitoring permission, real CGEventTap on hardware |
| **Bubble model** | Collapse generation, stale callback rejection, success→recording visibility, self-heal enforce paths, WindowServer presentation-verify generation guard / bounded recreate / idle lifecycle discard | Real NSPanel/CoreAnimation drawing / live CGWindowList compositing |
| **Diagnostics** | Redacted support-zip contents, secret scrubbing, history metadata only | Live menu Save panel, real `~/.golos/logs` on a user machine |
| **Persistence** | Config heal/normalize, history JSONL, dict/corrections on **temp paths** | Live `~/.golos` migration on a user machine |
| **Recovery** | Failed-run JSONL (STT/format/insert), legacy load compat, retry w/wo audio, copy-ready, no auto-insert; home grouping by `run_id`; busy retry vs live coordination | Real Settings UI retry buttons, live paste into apps |
| **Pipeline contracts** | Success, formatter passthrough/failure, cancel, insert/history failure (all mocked); partial success → `✓ inserted raw` | Live OpenRouter/Deepgram, Accessibility insert, clipboard |
| **Soak / adversarial** | ≥250 rapid state/event cycles: no stuck held key, no stale timer forcing a newer recording idle | Long-running production soak under load |
| **Learning TTL** | Fake-clock edit-window expiry: clear once, identity-safe concurrent clear, 1000 stale app switches → zero worker starts | Live AX / real multi-hour session |

Legacy focused scripts under `scripts/` remain available and must keep passing;
pytest under `tests/` is the discoverable, CI-friendly path.

---

## Setup

```sh
# from repo root, with the project venv
.venv/bin/pip install -r requirements-dev.txt
# or
.venv/bin/pip install -e ".[dev]"
```

Dev extras: `pytest`, `pytest-cov` (declared in `pyproject.toml` `[project.optional-dependencies] dev`
and mirrored in `requirements-dev.txt`).

---

## Exact commands

```sh
# Quiet unit + headless suite (default)
.venv/bin/python -m pytest -q

# Full package coverage with branch analysis
.venv/bin/python -m pytest --cov=dictate --cov=dictate_core --cov-branch --cov-report=term-missing

# Core-only coverage (pure library target)
.venv/bin/python -m pytest --cov=dictate_core --cov-branch --cov-report=term-missing

# HTML report (optional)
.venv/bin/python -m pytest --cov=dictate --cov=dictate_core --cov-branch --cov-report=html

# Compile check
python3 -m compileall -q dictate dictate_core scripts tests

# Legacy focused scripts (still pass; not deleted by this foundation)
.venv/bin/python scripts/test_learning.py
.venv/bin/python scripts/test_learning_reviewer.py
.venv/bin/python scripts/test_app_state.py
.venv/bin/python scripts/test_bubble_state.py
.venv/bin/python scripts/test_hotkey_events.py
```

**Guardrails (automated suite):** deterministic; no OpenRouter/Deepgram/OpenAI
calls; no GUI app launch; no mic capture; no clipboard mutation; no synthetic
keys; no writes to the real `~/.golos` (tests use `tmp_path` and a fake `HOME`).

Scripts that **do** hit the network or Accessibility intentionally (not part of
`pytest`):

| Script | Needs |
|---|---|
| `scripts/test_formatter_behavior.py` | Live OpenRouter + `~/.golos/config.toml` |
| `scripts/test_multiline_insert.py` | Accessibility + TextEdit |

---

## Coverage tooling

Configured in `pyproject.toml`:

- **Branch coverage** enabled (`[tool.coverage.run] branch = true`).
- **Omissions** only for generated/build trees (`build/`, `dist/`, `.venv/`,
  `site-packages`, egg-info) — **not** production modules solely to inflate %.
- **`fail_under`**: floor at or below the measured combined baseline (see below).
  Raise only after intentional gains.

### Separate targets

| Target | Intent | Rationale |
|---|---|---|
| **`dictate_core` pure** | **High** (aim ≥70%+ of headless code; recorder/mic adapters excluded in practice) | Logic is pure Python and mockable |
| **`dictate` OS adapters** | **Low until integration suite exists** | Requires signed app, permissions, mic, real frontmost apps, AX |
| **Combined `dictate`+`dictate_core`** | Honest floor only | Dominated by UI/onboarding/settings/providers |

Do **not** treat combined % as “product quality.” Prefer core + headless state
metrics, plus the manual smoke checklist for ship confidence.

---

## Current baseline (measured)

**Date:** 2026-07-21 (233 tests)
**Command:**

```sh
.venv/bin/python -m pytest --cov=dictate --cov=dictate_core --cov-branch --cov-report=term-missing
```

| Scope | Branch-aware cover | Notes |
|---|---|---|
| **`dictate` + `dictate_core` (combined)** | **34.19%** | Honest branch-aware baseline; `fail_under=24` stays conservative |
| **`dictate_core` only** | **75%** | Includes 0% on `recorder.py` (PortAudio/mic) |
| **`dictate_core` excluding `recorder.py`** | **~81%** (estimated from per-file) | Pure learning/formatter/dict/STT helpers |

Illustrative per-package hotspots (same run; exact lines shift with code changes):

| Module | Cover (approx.) | Headless status |
|---|---|---|
| `dictate_core/dictionary.py` | 100% | Covered |
| `dictate_core/learning.py` | ~90% | Covered |
| `dictate_core/learning_reviewer.py` | high | Payload/parse/validate/fallback (mocked HTTP) |
| `dictate_core/formatter.py` | 82% | Prompt/local; live HTTP mocked |
| `dictate_core/stt.py` | 69% | Helpers + mocked backends; no mlx/live |
| `dictate_core/recorder.py` | 0% | Needs mic / sounddevice |
| `dictate/history.py` | 86% | Temp-path tests |
| `dictate/config.py` | 87% | Temp-path migrate/load/update |
| `dictate/hotkeys.py` | ~61% | Decision matrix; no real tap install |
| `dictate/app.py` | 53% | State + pipeline contracts; not `run_app` |
| `dictate/bubble.py` | 21% | State model only; not ObjC views |
| `dictate/settings.py`, `onboarding.py`, `providers.py`, `context.py`, `insert.py`, `permissions.py`, … | ~0% | macOS integration |

Re-measure after large refactors and update this section (date + numbers).

---

## What the suite covers (by tier)

### 1. Pure unit (`dictate_core`)

- Learning: short whole-field near-miss, embedded refusal, anchors 8/12,
  long-field short proper-name (Mercy→Mercey), scroll tolerance,
  plausibility, logging
- Dictionary / corrections loaders (temp files)
- Formatter: `apply_literal_corrections`, context block/rules rendering,
  system prompt modes (transcribe vs answer), disabled/empty passthrough,
  mocked network failure → raw
- STT: `validate_languages`, `language_hint`, `wav_bytes` / `write_wav`,
  `make_backend` factory, OpenRouter STT JSON body contract (mocked httpx)
- OpenRouter: key resolution (env > config, char-array heal), model id filters
- VoicePipeline: wav decode contracts, key requirement, mlx construct, suggest_pairs

### 2. Headless app state

- idle → recording / locked; locked ignores release; press ends locked
- success → immediate press/toggle starts new recording
- stale `_finish_success` cannot cancel a newer recording
- processing ignores press/toggle; Esc cancel flag; Esc cancels recording
- mic start failure stays idle; hotkey test-handler intercept

### 3. Hotkey decision / event matrix

- SecondaryFn mask `0x800000` (not legacy `0x200000`)
- fn / right_option / right_command flagsChanged; F5 swallow; Space toggle once
- NSEvent fallback when tap inactive; no double-fire when tap active
- disabled-tap recovery clears stuck held
- `double_tap_decision` pure matrix; live `configure` hold-key rebind (no `start()`)

### 4. Bubble state model

- recording → processing collapse → processing mode
- stale collapse callback rejected after newer state
- success → immediate recording remains visible
- pure geometry helpers (`edge_falloff`, `success_decay`, …)

### 5. Persistence / config (temp only)

- `ensure_data_dir` create / migrate from old or project (copy-once)
- `load_config` absolute path preserve + char-array heal
- `update_config` on temp file
- `append_history` JSONL; dictionary/corrections roundtrip
- recovery: STT/insert failure writes, formatter fallback, legacy normalize,
  retry with/without retained WAV, attempt immutability, copy-ready
- history home grouping: one latest row per `run_id`; legacy rows stay single;
  `attempts_count` on merged views; JSONL unchanged
- busy coordination: retry during live processing / live ownership →
  `busy=True` and no attempt line; hotkey during history-retry ownership
  does not record (notice only); immediate re-press after success unchanged
- processing-stage Esc → schema-v2 `status=cancelled` / `stage=insert` with
  retained raw/final/audio/fast/fallback; no insert; copy-ready still works
- recording-stage Esc remains abort/discard with no history line

### 6. Pipeline contracts (all deps mocked)

- success path (insert + history + success state)
- formatter disabled / HTTP failure passthrough
- formatter raise / soft fallback + insert → `status=partial` and success
  label `✓ inserted raw` (lifecycle and `show_text=false` preserved)
- cancellation discards insert (returns idle; cancelled recovery in recovery tests)
- insertion failure → idle
- history failure still inserts
- short audio tap ignored; empty transcript / missing STT / STT exception persisted as failures
- fast mode local corrections skip stage 2

### 7. Soak / adversarial

- **250** rapid mixed cycles of hold/toggle/success-interrupt/recovery/processing
- asserts: no stuck `_fn_held`; stale success timer never forces a newer
  recording back to idle

---

## Remaining gaps (not claimed covered)

| Area | Why not automated here |
|---|---|
| Real microphone + PortAudio (`Recorder`) | Hardware + CoreAudio threading |
| mlx-whisper / live cloud STT quality | Network, models, audio content |
| Live formatter behavior (question vs answer) | See `scripts/test_formatter_behavior.py` |
| Accessibility insert (type/paste/clipboard) | Permissions + target apps; see multiline script |
| CGEventTap install + Input Monitoring | Entitlements / user consent |
| Bubble ObjC drawing, wings animation, notch geometry | AppKit main-thread UI |
| Settings UI, onboarding wizard, menu bar | Full app |
| Context providers (browser, VS Code, Finder) | AX + Automation consent |
| Edit watcher live cues | AX polling against real fields |
| Signed/notarized `golos.app` identity | Separate from Terminal grants |
| Multi-hour production soak | Manual / dedicated harness |

---

## Manual signed-build smoke checklist

Run against **`dist/golos.app`** (or the installed app), **not** only the
terminal venv. Permissions must be granted to **golos.app** itself.

1. **Permissions** — Microphone, Input Monitoring, Accessibility all ✓ in
   System Settings (and onboarding wizard shows green). After granting Input
   Monitoring, relaunch the app. A replaced unsigned build may need regrant.
2. **fn hold** — Hold fn: bubble/wings show recording; release: processing →
   text inserts at cursor in a plain text field (TextEdit / Notes).
3. **Lock** — fn+Space (or configured toggle): locked recording continues
   after release; single fn press stops and processes.
4. **Processing** — Visible processing state after release; no permanent hang.
5. **Insert + Accessibility preflight** — Single-line types; multi-line pastes
   then async CAS restore (transcript should not remain on Cmd+V after ~1.5 s
   unless you copied something else or disabled restore). No wrong clipboard
   paste into the target; success UI means events posted (not target-app
   verified delivery). With Accessibility denied: no green success, History
   keeps the result, warning notice. Menu Test insertion posts
   `✅ golos insertion test`. Escape hatch: Settings uncheck restore, or
   `method=type` for clipboard-free multi-line.
6. **Rapid repeat** — Immediately press fn again during the green success
   flash: new recording starts; strip does not disappear permanently
   (visual-panel self-heal; do not claim every UI glitch is gone).
7. **Export Diagnostics…** — Menu creates a local redacted zip; inspect that it
   excludes keys/audio/transcript/prompt/context content; nothing auto-uploads.
8. **Edit learning** — Insert a misheard word, fix it in-field; cue or
   suggestions appear / promote to `corrections.tsv` as designed; no crash.

Optional: Esc cancels mid-recording; Settings live-reload dictionary; quit from
menu leaves no stuck global hotkey.

---

## Policy

- Prefer adding **pytest** cases under `tests/` over one-off scripts for
  regressions that can run headless.
- Keep scripts for intentional **integration** probes (live API, TextEdit).
- Never omit hard production files from coverage solely to raise the %.
- Update the baseline table when the floor moves; keep `fail_under` ≤ measured
  combined coverage.
