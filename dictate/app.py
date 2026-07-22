"""NSApplication setup and the AppController state machine.

States: idle -> recording (hold) / locked (fn+Space toggle) -> processing -> idle.
UI and hotkey callbacks run on the main run loop; record stop/STT/format/insert
and Accessibility reads run on worker threads. UI updates from workers go
through PyObjCTools.AppHelper.callAfter (never touch AppKit from workers).

Threading invariant (CoreAudio): recorder.start() may run on main (fast path);
recorder.stop()/abort() must only run on workers — see dictate_core.recorder.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)


def is_wake_lifecycle_reason(reason: str) -> bool:
    """True for system/display wake notifications (not Spaces / screen params).

    Pure helper so the shared display-lifecycle observer can branch without a
    second NSWorkspace observer. Accepts full NSNotification names and short
    test tokens like ``\"wake\"``.
    """
    name = reason or ""
    lower = name.lower()
    if "activespace" in lower or "screenparameters" in lower:
        return False
    if "screensdidwake" in lower or "didwake" in lower:
        return True
    if lower in ("wake", "screens_wake", "display_wake", "system_wake"):
        return True
    # Bare token / log-friendly: require "wake" but not space/screen-param noise.
    return "wake" in lower


class CoalescedLevelBridge:
    """Keep at most one audio-level callback queued on the AppKit main loop."""

    def __init__(self, bubble, call_after):
        self.bubble = bubble
        self.call_after = call_after
        self._lock = threading.Lock()
        self._latest = 0.0
        self._scheduled = False

    def submit(self, rms: float) -> None:
        with self._lock:
            self._latest = float(rms)
            if self._scheduled:
                return
            self._scheduled = True
        try:
            self.call_after(self._drain)
        except Exception:
            with self._lock:
                self._scheduled = False
            raise

    def _drain(self) -> None:
        with self._lock:
            value = self._latest
            self._scheduled = False
        self.bubble.push_level(value)


class AppController:
    """Owns dictation state and wires hotkeys → recorder → STT → format → insert.

    Hotkey handlers (on_press/on_release/on_toggle/on_escape) are invoked on the
    main thread by HotkeyMonitor. Long work is always offloaded: context gather
    and edit capture on daemon workers, the full pipeline on another worker.
    `self._lock` only protects state transitions at hotkey boundaries — the
    pipeline itself does not hold it across network I/O.

    Pipeline ownership (`_pipeline_coord` / `_pipeline_owner`) coordinates the
    shared STT + formatter between the live dictation worker and History
    retries. Acquisition is a short critical section only — never held across
    network I/O. Values: None | ``"live"`` | ``"history_retry"``.
    """

    # Owners for the shared STT/formatter pipeline (see try_acquire_pipeline).
    PIPELINE_LIVE = "live"
    PIPELINE_HISTORY_RETRY = "history_retry"

    def __init__(self, cfg, recorder, stt_backend, formatter, bubble,
                 dictionary_terms, corrections, history_path):
        self.cfg = cfg
        self.recorder = recorder
        self.stt = stt_backend
        self.formatter = formatter
        self.bubble = bubble
        self.dictionary_terms = dictionary_terms
        self.corrections = corrections
        self.history_path = history_path
        self.state = "idle"          # idle | recording | locked | processing | success
        self._state_gen = 0           # invalidates delayed callbacks from older states
        self._lock = threading.Lock()
        # Short critical sections only — never hold across STT/format I/O.
        self._pipeline_coord = threading.Lock()
        self._pipeline_owner = None   # None | "live" | "history_retry"
        self._context = {"app_name": "", "bundle_id": "", "window_title": ""}
        self._fmt_context = {}           # formatter-facing, toggle-filtered
        self._settings = None        # settings window controller, built lazily
        # {ts, app_name, bundle_id, pid, raw, final, audio_path?}
        # audio_path is a retained WAV path only — never raw audio bytes.
        self.last_insertion = None
        self._cancel_requested = False
        self._watcher = None         # EditWatcher, created lazily in run_app
        self._hotkey_monitor = None  # set by run_app
        self.on_state_change = None  # optional callback(state) for UI mirrors
        self.hotkey_test_handler = None  # onboarding test pad: press/release hook
        self._fmt_context_ready = threading.Event()
        self._fmt_context_ready.set()
        # Coalesce DidWake + ScreensDidWake so we show at most one idle
        # permission warning per wake burst (no periodic prompts).
        self._last_wake_perm_warn_at = None

    # -- pipeline ownership (STT/formatter mutual exclusion) ---------------

    def try_acquire_pipeline(self, owner: str) -> bool:
        """Claim exclusive use of shared STT/formatter. Short lock only.

        Never hold this across network I/O — set the owner flag and return.
        History retries also refuse when live dictation is mid-recording or
        mid-processing. The state lock is acquired before the ownership lock,
        matching hotkey handlers, so a retry cannot slip into the tiny window
        between an idle hotkey check and the recording state transition.
        """
        with self._lock:
            with self._pipeline_coord:
                if self._pipeline_owner is not None:
                    return False
                if owner == self.PIPELINE_HISTORY_RETRY:
                    if self.state in ("recording", "locked", "processing"):
                        return False
                self._pipeline_owner = owner
                return True

    def release_pipeline(self, owner: str) -> None:
        """Release ownership if still held by ``owner`` (idempotent)."""
        with self._pipeline_coord:
            if self._pipeline_owner == owner:
                self._pipeline_owner = None

    def pipeline_owner(self) -> str | None:
        """Current pipeline owner, or None when free."""
        with self._pipeline_coord:
            return self._pipeline_owner

    def _history_retry_blocks_hotkey(self) -> bool:
        """True when a History retry owns STT/formatter (idle-safe check)."""
        with self._pipeline_coord:
            return self._pipeline_owner == self.PIPELINE_HISTORY_RETRY

    # -- UI state helper -------------------------------------------------

    def _set_state(self, state, *, success_label=None):
        """Main thread: flip controller + bubble state and mirror callbacks.

        ``success_label`` optionally overrides the green success strip/pill
        text (e.g. "✓ inserted raw" for format-fallback partial success).
        """
        self._state_gen += 1
        self.state = state
        try:
            self.bubble.set_state(state, success_label=success_label)
        except TypeError:
            # Older / fake bubbles that only accept the state name.
            self.bubble.set_state(state)
        try:
            visual = self.bubble.diagnostic_snapshot()
        except Exception as exc:
            visual = {"snapshot_error": type(exc).__name__}
        log.info("State: %s visual=%s", state, visual)
        if self.on_state_change is not None:
            try:
                self.on_state_change(state)
            except Exception as e:
                log.info("on_state_change failed: %s", e)
        return self._state_gen

    def _finish_success(self, generation):
        """Hide success only if no newer recording/state superseded its timer."""
        if generation != self._state_gen or self.state != "success":
            return
        self._set_state("idle")

    def _idle_then_notice(self, text, kind="warn", seconds=1.5):
        """Main thread: ensure idle, then show a notice.

        Real Bubble.notice is idle-only — calling it while still processing
        drops the message. One transition (processing→idle) then notice.
        """
        if self.state != "idle":
            self._set_state("idle")
        self.bubble.notice(text, kind, seconds)

    # -- hotkey callbacks (main thread) ----------------------------------

    def on_press(self):
        """Hold-key down. idle/success→recording, or end locked mode."""
        handler = self.hotkey_test_handler
        if handler is not None:
            handler("press")
            return
        blocked_by_retry = False
        with self._lock:
            if self.state in ("idle", "success"):
                # History retry owns STT/formatter — do not start recording.
                # Owner check is a separate short lock; never held across I/O.
                if self._history_retry_blocks_hotkey():
                    blocked_by_retry = True
                else:
                    self._begin_recording("recording")
                    return
            elif self.state != "locked":
                return
            else:
                # locked recording: a single fn press ends it (Wispr Flow)
                pass
        if blocked_by_retry:
            # Idle-safe: transition through idle so Bubble.notice is not dropped.
            self._idle_then_notice(
                "History retry is still running", "warn", 1.5)
            return
        if self.state == "locked":
            self._finish_recording()

    def on_release(self):
        """Hold-key up (main thread). Ends hold-to-talk; locked mode ignores it."""
        handler = self.hotkey_test_handler
        if handler is not None:
            handler("release")
            return
        with self._lock:
            if self.state != "recording":
                return  # locked mode ignores release
        self._finish_recording()

    def on_toggle(self):
        """fn+Space (or double-tap): lock hold, start locked, or finish locked."""
        blocked_by_retry = False
        with self._lock:
            if self.state == "recording":
                self._set_state("locked")
                return
            if self.state in ("idle", "success"):
                if self._history_retry_blocks_hotkey():
                    blocked_by_retry = True
                else:
                    self._begin_recording("locked")
                    return
            elif self.state != "locked":
                return
        if blocked_by_retry:
            self._idle_then_notice(
                "History retry is still running", "warn", 1.5)
            return
        if self.state == "locked":
            self._finish_recording()

    # -- settings / live reload -------------------------------------------

    def on_app_switch(self, new_bundle_id: str):
        """Frontmost app changed (NSWorkspaceDidActivateApplicationNotification).

        If an insertion is still pending in the app we just left, capture any
        manual edit from that app's focused field (best-effort AX via pid).
        Stale insertions past the edit window are expired here (once) so a
        long session never spawns thrashing too-old capture workers.
        """
        from .learning import eligible_last_insertion
        li = eligible_last_insertion(self)
        if not li or not li.get("bundle_id"):
            return
        if new_bundle_id == li["bundle_id"]:
            return
        # Preserve a correction already observed by the live watcher even if
        # the user switches away before the second stable debounce poll.
        if self._watcher is not None:
            self._watcher.flush_pending("app switch")
        # AX read of the OLD app's field + diff happen on a worker — the
        # main thread never blocks on Accessibility reads.
        threading.Thread(target=self._capture_on_switch, args=(li,),
                         daemon=True).start()

    def _capture_on_switch(self, li):
        """Worker: read the previous app's focused field and capture the edit."""
        from PyObjCTools import AppHelper
        from .learning import capture_edit, read_focused_text_for_pid
        try:
            text = read_focused_text_for_pid(li.get("pid")) if li.get("pid") else None
            # expected=li: a newer paste must not be cleared or mis-diffed by
            # this worker, which retained the pre-switch insertion dict.
            pairs = capture_edit(self, text=text, expected=li)
            if pairs:
                log.info("Learned %d suggestion(s) from your edit in %s.",
                         len(pairs), li.get("app_name", ""))
                AppHelper.callAfter(self._notice_learning, pairs)
        except Exception as e:
            log.info("App-switch edit capture failed: %s", e)

    def _capture_pending_edit(self):
        """45s fallback timer after an insertion (fires only if still pending)."""
        from .learning import eligible_last_insertion
        if not eligible_last_insertion(self):
            return
        from .learning import capture_edit_async
        capture_edit_async(self, self._after_timed_capture)

    def _after_timed_capture(self, pairs):
        """Main-thread callback for the 45s timer path."""
        if pairs:
            self._notice_learning(pairs)

    def _notice_learning(self, pairs):
        """Passive-capture feedback (only when nothing else is on screen)."""
        from .settings import _trunc
        if self.state != "idle":
            return
        wrong, right = pairs[0]
        extra = f" (+{len(pairs) - 1} more)" if len(pairs) > 1 else ""
        self.bubble.notice(
            f'learned "{_trunc(wrong)} → {_trunc(right)}"{extra}', "info")

    def accept_cue(self, wrong: str, right: str) -> None:
        """User clicked the edit cue: promote the pair to corrections, dismiss
        it from future suggestions, live-reload. The watcher already recorded
        it (and marked it seen), so it won't re-cue."""
        from .learning import promote_to_corrections, dismiss_pair
        paths = self.cfg["paths"]
        try:
            promote_to_corrections(paths["corrections"], wrong, right)
            dismiss_pair(paths["dismissed"], wrong, right)
            self.reload_dictionary()
            log.info("Cue accepted and added to corrections.")
        except Exception as e:
            log.warning("Could not accept cue: %s", e)

    def present_reviewer_suggestions(self, pairs, meta=None) -> None:
        """Main thread: distinct 'suggestion ready' animation then cue.

        Never auto-promotes. Generation/state guards live on the bubble so a
        newer recording/processing state is never overridden.
        """
        if not pairs:
            return
        wrong, right = pairs[0]
        secs = self.cfg.get("learning", {}).get("live_cue_seconds", 8)
        present = getattr(self.bubble, "suggestion_ready", None)
        if present is not None:
            present(wrong, right, secs,
                    lambda w, r: self.accept_cue(w, r))
        else:
            self.bubble.cue(wrong, right, secs,
                            lambda w, r: self.accept_cue(w, r))

    def open_settings(self):
        """Menu-bar "Settings…" action (main thread)."""
        if self._settings is None:
            from .settings import build_settings_window
            self._settings = build_settings_window(self)
        self._settings.show()

    def open_onboarding(self):
        """Menu-bar "Welcome / Setup…" action (main thread)."""
        from .onboarding import show_onboarding
        show_onboarding(self)

    def reload_dictionary(self):
        """Re-read dictionary.txt / corrections.tsv into the running pipeline."""
        from .dictionary import load_terms, load_corrections
        paths = self.cfg["paths"]
        self.dictionary_terms = load_terms(paths["dictionary"])
        self.corrections = load_corrections(paths["corrections"])
        self.formatter.set_vocabulary(self.dictionary_terms, self.corrections)
        log.info("Reloaded %d dictionary terms, %d corrections.",
                 len(self.dictionary_terms), len(self.corrections))

    def apply_settings(self):
        """Re-read config.toml and rebuild STT backend + formatter in place.

        Called after the Settings window saves. Bubble style is read only at
        startup (needs a restart to change).
        """
        from .config import load_config
        from .stt import make_backend
        self.cfg = load_config()
        self.stt = make_backend(self.cfg, _env_key)
        self.formatter.configure(self.cfg, self.dictionary_terms, self.corrections)
        self.bubble.set_sensitivity(
            self.cfg.get("bubble", {}).get("sensitivity", 1.0))
        self.bubble.set_show_text(
            self.cfg.get("bubble", {}).get("show_text", True))
        if self._hotkey_monitor is not None:
            self._hotkey_monitor.reconfigure(self.cfg)  # live hold-key rebind
        log.info("Settings applied: stt.backend=%s",
                 self.cfg.get("stt", {}).get("backend"))

    # -- pipeline ---------------------------------------------------------

    def _begin_recording(self, mode):
        """Main thread: start mic capture and spawn the context worker.

        mode is "recording" (hold-to-talk) or "locked" (toggle). A new
        recording ends any live edit-watcher session. Mic start is the
        tolerated main-thread CoreAudio call; AX / providers stay off-main.
        """
        # A new recording ends the current edit-watching session.
        if self._watcher is not None:
            self._watcher.stop("new recording")
        # Recording starts IMMEDIATELY (start() is the tolerated fast path);
        # everything slow — AX reads, edit capture, context providers — runs
        # on the context worker below. The pipeline thread waits for it.
        try:
            self.recorder.start()
        except Exception as e:
            log.error("Could not start recording (Microphone permission?): %s", e)
            return
        self._cancel_requested = False
        self._fmt_context_ready.clear()
        self._set_state(mode)
        threading.Thread(target=self._prepare_context, daemon=True).start()

    def _prepare_context(self):
        """Worker thread: edit-capture from the previous insertion + formatter
        context. self._context is for LOCAL use (history, learning);
        self._fmt_context is what the formatter receives — filtered by the
        [context] sharing toggles."""
        from .learning import capture_edit
        try:
            pairs = capture_edit(self)
            if pairs:
                log.info("Learned %d suggestion(s) from your edit.", len(pairs))
        except Exception as e:
            log.info("capture_edit failed: %s", e)
        try:
            from .context import frontmost_context
            context = frontmost_context()
            self._context = context
            fmt_context = dict(context)
            fmt_context.pop("pid", None)  # local bookkeeping, never prompt data
            if self.cfg.get("context", {}).get("enabled", True):
                try:
                    from .providers import gather_context
                    fmt_context = gather_context(
                        context.get("app_name", ""),
                        context.get("bundle_id", ""),
                        context.get("window_title", ""),
                        include_visible=bool(self.formatter.enabled),
                        flags=self.cfg.get("context", {}),
                    )
                except Exception as e:
                    log.info("gather_context failed: %s", e)
            if not self.cfg.get("context", {}).get("enabled", True) \
                    or not self.cfg.get("context", {}).get("app_info", True):
                # app_info=false: strip identity from the formatter context too
                for k in ("app_name", "bundle_id", "window_title"):
                    fmt_context.pop(k, None)
            self._fmt_context = fmt_context
        except Exception as e:
            log.info("context capture failed: %s", e)
        finally:
            self._fmt_context_ready.set()

    def on_escape(self):
        """Esc pressed (routed from the event tap / monitor, always passed
        through to the target app). Cancel recording or a pending insert."""
        with self._lock:
            state = self.state
        if state in ("recording", "locked"):
            # NEVER stop the stream on the main thread (CoreAudio deadlock) —
            # flip state first, abort on a worker.
            self._set_state("idle")
            self.bubble.notice("cancelled", "warn", 1.0)
            # Zero-arg target so test stubs replacing _discard_recording keep working.
            threading.Thread(target=self._discard_recording, daemon=True).start()
        elif state == "processing":
            self._cancel_requested = True
            log.info("Cancel requested — pipeline result will be discarded.")

    def handle_runtime_wake(self, reason: str = "wake", *, status: dict | None = None):
        """Main thread: recover permissions/hotkey state after system/display wake.

        Unit-testable (pass *status* to skip live TCC). Content-free logs only.
        Invoked from the shared display-lifecycle observer for wake reasons —
        not a second NSWorkspace observer.

        - Log a wake marker + permission snapshot (no transcript/content).
        - If recording/locked: idle immediately, abort recorder on a worker
          (never on main — CoreAudio rule).
        - Reset sticky held-key bookkeeping on the HotkeyMonitor.
        - Idempotent ``ensure_tap``: re-enable disabled tap, or recreate only
          the tap when missing and Input Monitoring is granted (no duplicate
          NSEvent monitors / run-loop sources).
        - At most one idle permission warning per wake burst when something
          required is gone; observe-only remains honest when IM is missing.
        - Does not reopen audio devices, re-prompt permissions, or redesign UI.
        """
        from .permissions import (
            check_all,
            missing_kinds,
            permission_snapshot,
            wake_permission_notice,
        )

        log.info("runtime wake reason=%s", reason)
        if status is None:
            try:
                status = check_all()
            except Exception as exc:
                log.info("runtime wake permission check failed: %s", exc)
                status = {
                    "accessibility": False,
                    "input_monitoring": False,
                    "microphone": "unknown",
                }
        snap = permission_snapshot(status)
        log.info("runtime wake permissions=%s", snap)

        result = {
            "reason": reason,
            "permissions": snap,
            "aborted_recording": False,
            "held_reset": False,
            "tap_action": None,
            "permission_warning": False,
            "missing": missing_kinds(status),
        }

        with self._lock:
            state = self.state
        if state in ("recording", "locked"):
            # Worker-only abort — same rule as Esc cancel. Do not finish the
            # pipeline (audio after sleep is not trustworthy). Zero-arg
            # wrapper so _discard_recording stubs in tests stay valid.
            self._set_state("idle")
            discard_reason = f"wake abort ({reason})"

            def _wake_discard():
                self._discard_recording(discard_reason)

            threading.Thread(target=_wake_discard, daemon=True).start()
            result["aborted_recording"] = True
            log.info("runtime wake aborted state=%s → idle", state)

        mon = self._hotkey_monitor
        if mon is not None:
            try:
                result["held_reset"] = bool(mon.reset_held_state())
            except Exception as exc:
                log.info("runtime wake held-key reset failed: %s", exc)
            try:
                im = status.get("input_monitoring")
                # False → stay observe-only; True → recover; missing → try.
                im_flag = bool(im) if im is not None else None
                result["tap_action"] = mon.ensure_tap(input_monitoring=im_flag)
            except Exception as exc:
                log.info("runtime wake ensure_tap failed: %s", exc)
                result["tap_action"] = "error"

        missing = result["missing"]
        if missing:
            now = time.monotonic()
            # Coalesce NSWorkspaceDidWake + ScreensDidWake (and rapid re-entry).
            last_warn = self._last_wake_perm_warn_at
            with self._lock:
                idle_for_notice = self.state == "idle"
            if idle_for_notice and (
                    last_warn is None or now - last_warn >= 5.0):
                notice = wake_permission_notice(missing)
                if notice:
                    self._idle_then_notice(notice, "warn", 2.5)
                    self._last_wake_perm_warn_at = now
                    result["permission_warning"] = True
            elif not idle_for_notice:
                # Never force an in-flight STT/formatter pipeline to idle just
                # to display a permission warning. The menu preflight remains
                # available and the next wake/launch checks again.
                log.info(
                    "runtime wake permission warning deferred state=%s",
                    self.state,
                )

        log.info(
            "runtime wake done aborted=%s held_reset=%s tap=%s warn=%s",
            result["aborted_recording"],
            result["held_reset"],
            result["tap_action"],
            result["permission_warning"],
        )
        return result

    def _discard_recording(self, reason: str = "cancelled by user"):
        """Worker: abort the stream (no callback-completion wait) and discard."""
        try:
            self.recorder.abort()
            log.info("Recording discarded (%s).", reason)
        except Exception as e:
            log.info("Discard failed: %s", e)

    def _finish_recording(self):
        """Main thread: enter processing and spawn the pipeline worker.

        Only flips UI state here — recorder.stop() runs inside _pipeline on
        the worker. Stopping PortAudio on main deadlocks CoreAudio.
        """
        # Main thread ONLY flips state — recorder.stop() happens in the
        # pipeline worker. (Stopping on main deadlocks CoreAudio.)
        self._set_state("processing")
        threading.Thread(target=self._pipeline, daemon=True).start()

    def _save_recording(self, audio) -> str | None:
        """Write the captured wav to ~/.golos/recordings/YYYY-MM-DD/ (raw
        material for python -m dictate.bench). None when disabled/failed."""
        if not self.cfg.get("audio", {}).get("keep_recordings", True):
            return None
        try:
            from datetime import datetime
            from pathlib import Path
            from .stt import write_wav
            from .config import DATA_DIR
            day_dir = DATA_DIR / "recordings" / datetime.now().strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            path = day_dir / (now.strftime("%H%M%S")
                              + f"_{now.microsecond // 1000:03d}.wav")
            write_wav(str(path), audio)
            log.info("Recording saved: %s (%.1fs)", path, len(audio) / 16000)
            return str(path)
        except Exception as e:
            log.warning("Could not save recording: %s", e)
            return None

    def _pipeline(self):
        """Worker thread: stop mic → STT → format → schedule insert on main.

        Privacy: audio leaves the Mac only for non-mlx STT backends, and again
        if [formatting] send_audio is true (formatter multimodal path). The
        raw transcript leaves for stage-2 LLM formatting when enabled.
        self._fmt_context is already filtered by [context] toggles.

        Recovery: each run gets a stable run_id. Failures at STT / format /
        insert are written to history.jsonl with enough state to retry later.
        Esc during processing (after STT/formatting produced text) appends
        status=cancelled at stage=insert and never inserts. Esc while still
        recording remains a pure abort with no history. Success history is
        written only after insert confirms (not when scheduled). Retries
        never rewrite the original failure line.
        """
        from PyObjCTools import AppHelper
        from .insert import insert_text
        from .history import (
            STAGE_FORMAT, STAGE_INSERT, STAGE_STT, STAGE_COMPLETE,
            STATUS_CANCELLED, STATUS_PARTIAL, STATUS_SUCCESS,
            append_failure, append_history, new_run_id,
        )

        # Exclusive live ownership for shared STT/formatter. Short acquire
        # only — release in finally; never hold _pipeline_coord across I/O.
        if not self.try_acquire_pipeline(self.PIPELINE_LIVE):
            log.info("Live pipeline deferred: shared STT/formatter busy (%s).",
                     self.pipeline_owner())
            # Still stop the mic so we do not leave the stream open.
            try:
                self.recorder.stop()
            except Exception as e:
                log.info("stop after busy: %s", e)
            AppHelper.callAfter(
                self._idle_then_notice,
                "History retry is still running", "warn")
            return

        try:
            self._pipeline_body(AppHelper, insert_text)
        finally:
            self.release_pipeline(self.PIPELINE_LIVE)

    def _pipeline_body(self, AppHelper, insert_text):
        """Live pipeline body after ownership is acquired (worker thread)."""
        from .history import (
            STAGE_FORMAT, STAGE_INSERT, STAGE_STT, STAGE_COMPLETE,
            STATUS_CANCELLED, STATUS_PARTIAL, STATUS_SUCCESS,
            append_failure, append_history, new_run_id,
        )

        # Wait (bounded) for the context worker — formatting wants app context,
        # but never stall the pipeline more than 3 s over it.
        if not self._fmt_context_ready.wait(timeout=3.0):
            log.info("Context gather timed out; proceeding with empty context.")

        # recorder.stop() on a WORKER thread — never on main (CoreAudio deadlock).
        audio = self.recorder.stop()
        if len(audio) < 4800:  # < 0.3 s — accidental tap, skip everything
            log.info("Ignored accidental tap (%.2fs of audio).",
                     len(audio) / 16000)
            AppHelper.callAfter(self._set_state, "idle")
            return

        raw = final = ""
        audio_path = self._save_recording(audio)
        run_id = new_run_id()
        fast = False
        format_fallback = False
        insert_scheduled = False
        # True when a failure path already scheduled idle+notice (skip finally).
        idle_noticed = False
        app_name = self._context.get("app_name", "")
        bundle_id = self._context.get("bundle_id", "")
        hist_ctx = _history_context(self._fmt_context)

        def _write_failure(stage, error, raw_text=None, final_text=None,
                           fmt_fallback=False):
            try:
                append_failure(
                    self.history_path,
                    stage=stage,
                    error=error,
                    app_name=app_name,
                    bundle_id=bundle_id,
                    raw_text=raw_text if raw_text is not None else raw,
                    final_text=final_text if final_text is not None else final,
                    context=hist_ctx,
                    audio=audio_path,
                    fast=fast,
                    run_id=run_id,
                    attempt=0,
                    format_fallback=fmt_fallback,
                )
            except Exception as e:
                log.warning("Could not write failure history: %s", e)

        def _fail_visible(message, kind="warn"):
            """Schedule idle→notice once; finally must not re-idle."""
            nonlocal idle_noticed
            idle_noticed = True
            AppHelper.callAfter(self._idle_then_notice, message, kind)

        try:
            if self.stt is None:
                log.error("No STT backend available.")
                _write_failure(STAGE_STT, "no STT backend available")
                _fail_visible("connect OpenRouter or download local STT")
                return
            prompt = ", ".join(self.dictionary_terms)
            try:
                raw = self.stt.transcribe(audio, prompt=prompt)
            except Exception as e:
                log.exception("STT failed: %s", e)
                _write_failure(STAGE_STT, f"stt: {e}", raw_text="", final_text="")
                _fail_visible(
                    "speech recognition failed — open History for details")
                return
            log.debug("Raw transcript: %r", raw)
            if not raw:
                # A >0.3s capture reached STT but produced nothing. Persist it:
                # this can be genuine silence, but it can also be a provider
                # failure and a retained WAV makes it recoverable.
                _write_failure(
                    STAGE_STT,
                    "stt returned empty transcript",
                    raw_text="",
                    final_text="",
                )
                _fail_visible("couldn't hear that — open History to retry")
                return
            # Fast mode: short single-line dictations skip stage 2 entirely;
            # literal corrections are applied locally instead of by the LLM.
            fmt_cfg = self.cfg.get("formatting", {})
            if (fmt_cfg.get("fast_mode") and "\n" not in raw
                    and len(raw.split()) <= fmt_cfg.get("fast_mode_max_words", 10)):
                from dictate_core.formatter import apply_literal_corrections
                final = apply_literal_corrections(raw, self.corrections)
                fast = True
                log.info("fast mode: skipped stage 2 (%d words)", len(raw.split()))
            else:
                audio_wav = None
                if fmt_cfg.get("send_audio"):
                    # Optional: original wav rides with the chat request so the
                    # model can un-garble STT from what it hears. Off by default.
                    from .stt import wav_bytes
                    audio_wav = wav_bytes(audio)
                try:
                    final = self.formatter.format(raw, self._fmt_context,
                                                  audio_wav=audio_wav)
                except Exception as e:
                    # Real Formatter returns raw on API failure; a raising
                    # formatter is treated the same: keep raw, mark fallback.
                    log.warning("Formatting raised (%s); using raw transcript.", e)
                    final = raw
                    format_fallback = True
                else:
                    # Formatter contract: failure returns raw. Detect soft
                    # fallback when enabled formatter returns unchanged raw
                    # after an internal error is already logged there.
                    if (final == raw and getattr(self.formatter, "enabled", True)
                            and not fast):
                        # Soft fallback is normal (disabled path or clean raw).
                        # Only flag when formatter explicitly signals failure
                        # via attribute; default is success with raw=final.
                        format_fallback = bool(
                            getattr(self.formatter, "last_fallback", False))
            if final != raw:
                log.debug("Formatted: %r", final)

            if self._cancel_requested:
                # Processing-stage Esc: STT/format already ran; persist a
                # recoverable cancelled record (same run_id) and never insert.
                # Recording-stage Esc still aborts with no history.
                log.info("Insertion cancelled by user; result discarded.")
                try:
                    append_history(
                        self.history_path,
                        app_name,
                        bundle_id,
                        raw,
                        final,
                        context=hist_ctx,
                        audio=audio_path,
                        fast=fast,
                        run_id=run_id,
                        attempt=0,
                        stage=STAGE_INSERT,
                        status=STATUS_CANCELLED,
                        format_fallback=format_fallback,
                    )
                except Exception as e:
                    log.warning("Could not write cancelled history: %s", e)
                return

            # Close over immutable snapshot for the main-thread insert path.
            snap = {
                "raw": raw,
                "final": final,
                "audio_path": audio_path,
                "fast": fast,
                "format_fallback": format_fallback,
                "run_id": run_id,
                "app_name": app_name,
                "bundle_id": bundle_id,
                "context": hist_ctx,
            }

            def insert_and_flash():
                ins_cfg = self.cfg.get("insert", {})
                ok = insert_text(
                    snap["final"],
                    method=ins_cfg.get("method", "auto"),
                    restore_clipboard=ins_cfg.get("restore_clipboard", True),
                )
                if ok:
                    import time as _time
                    self.last_insertion = {
                        "ts": _time.time(),
                        "app_name": snap["app_name"],
                        "bundle_id": snap["bundle_id"],
                        "pid": self._context.get("pid"),
                        "raw": snap["raw"],
                        "final": snap["final"],
                        # Retained WAV path only when [audio] keep_recordings
                        # saved one; never store raw audio bytes here.
                        "audio_path": snap["audio_path"],
                        "run_id": snap["run_id"],
                    }
                    try:
                        append_history(
                            self.history_path,
                            snap["app_name"],
                            snap["bundle_id"],
                            snap["raw"],
                            snap["final"],
                            context=snap["context"],
                            audio=snap["audio_path"],
                            fast=snap["fast"],
                            run_id=snap["run_id"],
                            attempt=0,
                            stage=STAGE_COMPLETE,
                            status=(STATUS_PARTIAL if snap["format_fallback"]
                                    else STATUS_SUCCESS),
                            format_fallback=snap["format_fallback"],
                        )
                    except Exception as e:
                        log.warning("Could not write history: %s", e)
                    # Fallback edit-capture: if the insertion is still pending
                    # in 45s (no new recording, no app switch), check now.
                    AppHelper.callLater(45, self._capture_pending_edit)
                    # Live edit cues: watch the field for manual corrections.
                    if self._watcher is not None:
                        self._watcher.start()
                    # Partial (format fell back to raw, insert ok): keep the
                    # success animation/fade lifecycle, but label truthfully.
                    success_label = (
                        "✓ inserted raw" if snap["format_fallback"] else None)
                    success_gen = self._set_state(
                        "success", success_label=success_label)
                    AppHelper.callLater(1.2, self._finish_success, success_gen)
                else:
                    try:
                        from .permissions import check_accessibility
                        missing_accessibility = not check_accessibility()
                    except Exception:
                        missing_accessibility = False
                    insert_error = (
                        "Accessibility permission missing"
                        if missing_accessibility else "insertion failed")
                    try:
                        append_failure(
                            self.history_path,
                            stage=STAGE_INSERT,
                            error=insert_error,
                            app_name=snap["app_name"],
                            bundle_id=snap["bundle_id"],
                            raw_text=snap["raw"],
                            final_text=snap["final"],
                            context=snap["context"],
                            audio=snap["audio_path"],
                            fast=snap["fast"],
                            run_id=snap["run_id"],
                            attempt=0,
                            format_fallback=snap["format_fallback"],
                        )
                    except Exception as e:
                        log.warning("Could not write insert-failure history: %s", e)
                    notice = (
                        "Accessibility needed — result saved in History"
                        if missing_accessibility
                        else "couldn't insert — open History to copy")
                    self._idle_then_notice(notice, "warn")

            AppHelper.callAfter(insert_and_flash)
            insert_scheduled = True
        except Exception as e:
            log.exception("Pipeline failed: %s", e)
            stage = STAGE_FORMAT if raw else STAGE_STT
            _write_failure(stage, f"pipeline: {e}",
                           raw_text=raw, final_text=final)
        finally:
            self._cancel_requested = False
            if not insert_scheduled and not idle_noticed:
                AppHelper.callAfter(self._set_state, "idle")

    # -- recovery: copy-ready + retry (no auto-insert) ---------------------

    def copy_ready_for_record(self, record: dict) -> dict:
        """Best available text for History copy. Never inserts into any app.

        Returns the dict from history.copy_ready (text, source, available, …).
        """
        from .history import copy_ready
        return copy_ready(record)

    def retry_capabilities_for_record(self, record: dict) -> dict:
        """What the Settings UI may offer for a history/recovery row."""
        from .history import retry_capabilities
        return retry_capabilities(record)

    def retry_failed_stage(self, record: dict, *,
                           stage: str | None = None,
                           insert: bool = False) -> dict:
        """Regenerate text for a failed (or re-formatable) history record.

        Contract for a later Settings UI:
        - Retries append a new attempt line; the original failure is kept.
        - STT retry requires a retained WAV still on disk (privacy: we never
          invent or secretly keep audio).
        - Format retry uses stored raw (+ optional WAV if send_audio).
        - insert=False (default): never pastes into the frontmost app —
          returns regenerated text for the UI to copy or insert explicitly.
        - insert=True: only then call insert_text with the regenerated text
          into the *current* focus (documented explicit UI action). Callers
          must not pass insert=True for background/automatic retries.
        - While a live dictation owns the shared STT/formatter (or is mid
          recording/processing), returns ``busy=True`` and appends **no**
          attempt line. Ownership is a short flag only — never held across
          network I/O.

        Returns a result dict:
          ok, stage, text, source, record (new attempt), error, audio_retained,
          inserted (bool), busy (bool).
        """
        from pathlib import Path
        from .history import (
            STAGE_FORMAT, STAGE_INSERT, STAGE_STT, STAGE_COMPLETE,
            STATUS_PARTIAL, STATUS_SUCCESS,
            append_failure, append_history, copy_ready, next_attempt_number,
            normalize_record, retry_capabilities,
        )

        def _busy_result(stage_val=None):
            return {
                "ok": False,
                "busy": True,
                "stage": stage_val if stage_val is not None else stage,
                "text": None,
                "source": None,
                "record": None,
                "error": "busy",
                "audio_retained": False,
                "inserted": False,
            }

        # Coordinate with live pipeline before any STT/format work. No history
        # append on the busy path (avoids a misleading attempt line).
        if not self.try_acquire_pipeline(self.PIPELINE_HISTORY_RETRY):
            log.info("History retry busy: owner=%s state=%s",
                     self.pipeline_owner(), self.state)
            return _busy_result()

        try:
            return self._retry_failed_stage_body(
                record, stage=stage, insert=insert)
        finally:
            self.release_pipeline(self.PIPELINE_HISTORY_RETRY)

    def _retry_failed_stage_body(self, record: dict, *,
                                 stage: str | None = None,
                                 insert: bool = False) -> dict:
        """Retry body after history_retry ownership is held."""
        from pathlib import Path
        from .history import (
            STAGE_FORMAT, STAGE_INSERT, STAGE_STT, STAGE_COMPLETE,
            STATUS_PARTIAL, STATUS_SUCCESS,
            append_failure, append_history, copy_ready, next_attempt_number,
            normalize_record, retry_capabilities,
        )

        norm = normalize_record(record)
        if not norm:
            return {
                "ok": False,
                "busy": False,
                "stage": stage,
                "text": None,
                "source": None,
                "record": None,
                "error": "invalid record",
                "audio_retained": False,
                "inserted": False,
            }

        caps = retry_capabilities(norm)
        # Default priority: STT → INSERT → FORMAT. Insert-stage failures with
        # final text must reuse stored text (no formatter / no model tokens).
        target = stage or (
            STAGE_STT if caps["can_retry_stt"]
            else STAGE_INSERT if caps["can_retry_insert"]
            else STAGE_FORMAT if caps.get("can_retry_format")
            else None
        )
        run_id = norm.get("run_id") or None
        attempt_n = next_attempt_number(self.history_path, run_id)
        app_name = norm.get("app") or ""
        bundle_id = norm.get("bundle_id") or ""
        context = norm.get("context") or {}
        audio_path = norm.get("audio") if caps.get("has_audio") else None
        # Honest: only report retained if path exists (not merely was logged).
        audio_retained = bool(audio_path and Path(str(audio_path)).is_file())
        if norm.get("audio") and not audio_retained:
            log.info("Retry: recorded audio path missing on disk: %s",
                     norm.get("audio"))

        raw = (norm.get("raw") or "") or ""
        final = (norm.get("final") or "") or ""
        fast = False
        format_fallback = False
        error = None
        result_stage = target or STAGE_FORMAT

        try:
            if target == STAGE_STT:
                if not audio_retained:
                    error = ("audio not retained; cannot re-run STT "
                             "(privacy: WAV only kept when keep_recordings)")
                    rec = append_failure(
                        self.history_path,
                        stage=STAGE_STT,
                        error=error,
                        app_name=app_name,
                        bundle_id=bundle_id,
                        raw_text=raw,
                        final_text=final,
                        context=context,
                        audio=None,
                        run_id=run_id,
                        attempt=attempt_n,
                        kind="attempt",
                    )
                    return {
                        "ok": False,
                        "stage": STAGE_STT,
                        "text": copy_ready(norm).get("text"),
                        "source": copy_ready(norm).get("source"),
                        "record": rec,
                        "error": error,
                        "audio_retained": False,
                        "inserted": False,
                    }
                if self.stt is None:
                    error = "no STT backend available"
                    rec = append_failure(
                        self.history_path,
                        stage=STAGE_STT,
                        error=error,
                        app_name=app_name,
                        bundle_id=bundle_id,
                        raw_text=raw,
                        final_text=final,
                        context=context,
                        audio=audio_path,
                        run_id=run_id,
                        attempt=attempt_n,
                        kind="attempt",
                    )
                    return {
                        "ok": False,
                        "stage": STAGE_STT,
                        "text": None,
                        "source": None,
                        "record": rec,
                        "error": error,
                        "audio_retained": True,
                        "inserted": False,
                    }
                from .stt import load_wav
                audio = load_wav(str(audio_path))
                prompt = ", ".join(self.dictionary_terms)
                raw = self.stt.transcribe(audio, prompt=prompt) or ""
                if not raw:
                    error = "stt returned empty transcript"
                    rec = append_failure(
                        self.history_path,
                        stage=STAGE_STT,
                        error=error,
                        app_name=app_name,
                        bundle_id=bundle_id,
                        raw_text="",
                        final_text="",
                        context=context,
                        audio=audio_path,
                        run_id=run_id,
                        attempt=attempt_n,
                        kind="attempt",
                    )
                    return {
                        "ok": False,
                        "stage": STAGE_STT,
                        "text": None,
                        "source": None,
                        "record": rec,
                        "error": error,
                        "audio_retained": True,
                        "inserted": False,
                    }
                # After STT, also format so copy-ready has best text.
                target = STAGE_FORMAT
                result_stage = STAGE_STT

            if target in (STAGE_FORMAT, STAGE_STT) and raw:
                fmt_cfg = self.cfg.get("formatting", {})
                if (fmt_cfg.get("fast_mode") and "\n" not in raw
                        and len(raw.split()) <= fmt_cfg.get(
                            "fast_mode_max_words", 10)):
                    from dictate_core.formatter import apply_literal_corrections
                    final = apply_literal_corrections(raw, self.corrections)
                    fast = True
                else:
                    audio_wav = None
                    if fmt_cfg.get("send_audio") and audio_retained:
                        from .stt import wav_bytes, load_wav
                        try:
                            audio_wav = wav_bytes(load_wav(str(audio_path)))
                        except Exception as e:
                            log.info("Retry: could not load wav for format: %s", e)
                    try:
                        final = self.formatter.format(
                            raw, context, audio_wav=audio_wav)
                    except Exception as e:
                        log.warning("Retry format raised (%s); using raw.", e)
                        final = raw
                        format_fallback = True
                    else:
                        format_fallback = bool(
                            getattr(self.formatter, "last_fallback", False))
                result_stage = STAGE_FORMAT if target == STAGE_FORMAT else result_stage

            elif target == STAGE_INSERT:
                # Re-use best stored text; no regeneration required.
                final = final or raw
                if not (final or "").strip():
                    error = "no text available to insert/copy"
                    rec = append_failure(
                        self.history_path,
                        stage=STAGE_INSERT,
                        error=error,
                        app_name=app_name,
                        bundle_id=bundle_id,
                        raw_text=raw,
                        final_text=final,
                        context=context,
                        audio=audio_path if audio_retained else None,
                        run_id=run_id,
                        attempt=attempt_n,
                        kind="attempt",
                    )
                    return {
                        "ok": False,
                        "stage": STAGE_INSERT,
                        "text": None,
                        "source": None,
                        "record": rec,
                        "error": error,
                        "audio_retained": audio_retained,
                        "inserted": False,
                    }
                result_stage = STAGE_INSERT

            text = (final or raw or "").strip() and (final or raw)
            source = "final" if (final or "").strip() else (
                "raw" if (raw or "").strip() else None)

            inserted = False
            if insert and text:
                # Explicit UI-only path: paste into *current* focus — never
                # auto-target the original app from the record.
                from .insert import insert_text
                ins_cfg = self.cfg.get("insert", {})
                inserted = bool(insert_text(
                    text,
                    method=ins_cfg.get("method", "auto"),
                    restore_clipboard=ins_cfg.get("restore_clipboard", True),
                ))
                if not inserted:
                    rec = append_failure(
                        self.history_path,
                        stage=STAGE_INSERT,
                        error="insertion failed on explicit retry",
                        app_name=app_name,
                        bundle_id=bundle_id,
                        raw_text=raw,
                        final_text=final,
                        context=context,
                        audio=audio_path if audio_retained else None,
                        fast=fast,
                        run_id=run_id,
                        attempt=attempt_n,
                        format_fallback=format_fallback,
                        kind="attempt",
                    )
                    return {
                        "ok": False,
                        "stage": STAGE_INSERT,
                        "text": text,
                        "source": source,
                        "record": rec,
                        "error": "insertion failed",
                        "audio_retained": audio_retained,
                        "inserted": False,
                    }

            status = STATUS_PARTIAL if format_fallback else STATUS_SUCCESS
            out_stage = STAGE_COMPLETE if (
                insert and inserted) else (result_stage or STAGE_FORMAT)
            if insert and inserted:
                out_stage = STAGE_COMPLETE
            elif not insert:
                # Regenerated for copy; mark success of the retry stage.
                status = STATUS_PARTIAL if format_fallback else STATUS_SUCCESS
                out_stage = result_stage or STAGE_FORMAT

            rec = append_history(
                self.history_path,
                app_name,
                bundle_id,
                raw,
                final or raw,
                context=context,
                audio=audio_path if audio_retained else None,
                fast=fast,
                run_id=run_id,
                attempt=attempt_n,
                stage=out_stage,
                status=status,
                format_fallback=format_fallback,
                kind="attempt",
            )
            return {
                "ok": True,
                "stage": out_stage,
                "text": text,
                "source": source,
                "record": rec,
                "error": None,
                "audio_retained": audio_retained,
                "inserted": inserted,
            }
        except Exception as e:
            log.exception("retry_failed_stage failed: %s", e)
            try:
                rec = append_failure(
                    self.history_path,
                    stage=target or STAGE_STT,
                    error=str(e),
                    app_name=app_name,
                    bundle_id=bundle_id,
                    raw_text=raw,
                    final_text=final,
                    context=context,
                    audio=audio_path if audio_retained else None,
                    run_id=run_id,
                    attempt=attempt_n,
                    kind="attempt",
                )
            except Exception as write_e:
                log.warning("Could not write retry failure: %s", write_e)
                rec = None
            fallback_text = final or raw or None
            return {
                "ok": False,
                "stage": target,
                "text": fallback_text if fallback_text else None,
                "source": "final" if final else ("raw" if raw else None),
                "record": rec,
                "error": str(e),
                "audio_retained": audio_retained,
                "inserted": False,
            }


def _history_context(context: dict) -> dict:
    """Context dict for history.jsonl: workspace_files truncated to 50 lines."""
    from .history import _truncate_context
    return _truncate_context(context)


def _acquire_instance_lock(lock_path):
    """Exclusive non-blocking flock on the lock file.

    Returns the open file handle (kept alive for process lifetime; the OS
    releases the lock on death, even SIGKILL), or None if already held."""
    import fcntl
    import os
    fd = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        return None
    fd.seek(0)
    fd.truncate()
    fd.write(f"pid {os.getpid()}\n")
    fd.flush()
    return fd


def _read_lock_pid(lock_path) -> int | None:
    """Pid recorded in the lock file ("pid N"), or None."""
    try:
        with open(lock_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("pid "):
                    return int(line[4:])
    except (OSError, ValueError):
        pass
    return None


def _refusal_message(lock_path) -> str:
    pid = _read_lock_pid(lock_path)
    if pid is not None:
        return (f"golos is already running (pid {pid}). Quit it from its "
                f"menu, or run: kill {pid}  (or ./dictate.sh restart)")
    return "golos is already running (see ~/.golos/dictate.lock)"


def _check_audio_model(formatter) -> None:
    """Worker: warn once if [formatting] send_audio is on but the configured
    formatter model lacks audio input modalities."""
    try:
        from .openrouter import fetch_models, audio_model_ids
        if formatter.model not in audio_model_ids(fetch_models(formatter.api_key)):
            log.warning("[formatting] send_audio=true but model %s has no "
                        "audio input modality — audio will be ignored or fail. "
                        "Pick an audio-capable model (e.g. gemini-2.5-flash).",
                        formatter.model)
    except Exception as e:
        log.info("Could not verify formatter model audio support: %s", e,
                 exc_info=True)


def _env_key(section):
    from .config import env_key
    return env_key(section)


def _needs_onboarding(cfg: dict, permission_status: dict) -> bool:
    """Reopen setup when this exact binary lacks a required macOS grant.

    The config is shared under ~/.golos, but TCC permissions belong to the
    executable identity. A DMG app therefore must not inherit an old
    `onboarded = true` flag and silently skip its own permission setup.
    """
    from .permissions import granted
    if not cfg.get("app", {}).get("onboarded"):
        return True
    return any(not granted(value) for value in permission_status.values())


def run_app(cfg):
    """Set up NSApplication and enter the run loop (blocks)."""
    import os
    import sys
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from PyObjCTools import AppHelper

    from .bubble import Bubble
    from .hotkeys import HotkeyMonitor
    from .recorder import Recorder
    from .stt import make_backend
    from .formatter import Formatter
    from .config import env_key, LOCK_PATH
    from .dictionary import load_terms, load_corrections
    from .settings import build_status_item

    # Single-instance guard: the OS releases the flock on process death,
    # even SIGKILL, so a zombie can never wedge the lock file.
    lock_path = LOCK_PATH
    instance_lock = _acquire_instance_lock(lock_path)
    if instance_lock is None:
        print(_refusal_message(lock_path))
        sys.exit(1)
    log.info("dictate starting (pid %d)", os.getpid())

    paths = cfg["paths"]
    dictionary_terms = load_terms(paths["dictionary"])
    corrections = load_corrections(paths["corrections"])
    log.info("Loaded %d dictionary terms, %d corrections.",
             len(dictionary_terms), len(corrections))

    from .permissions import log_report
    permission_status = log_report()

    stt_backend = make_backend(cfg, env_key)
    formatter = Formatter(cfg, dictionary_terms, corrections)

    # Warn once if send_audio is on but the model can't hear audio.
    if cfg.get("formatting", {}).get("send_audio"):
        threading.Thread(target=_check_audio_model, args=(formatter,),
                         daemon=True).start()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no dock icon

    # App icon for dialogs (dev runs show a generic icon otherwise).
    try:
        from AppKit import NSImage, NSBundle
        from .config import PROJECT_ROOT
        icon_path = NSBundle.mainBundle().pathForResource_ofType_("golos", "icns")
        if icon_path is None:
            icon_path = str(PROJECT_ROOT / "golos.icns")
        icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if icon is not None:
            app.setApplicationIconImage_(icon)
    except Exception as e:
        log.info("Could not set application icon: %s", e)

    bubble_style = cfg.get("bubble", {}).get("style", "notch")
    bubble = Bubble(style=bubble_style)
    bubble.set_sensitivity(cfg.get("bubble", {}).get("sensitivity", 1.0))
    bubble.set_show_text(cfg.get("bubble", {}).get("show_text", True))

    device = cfg.get("audio", {}).get("device", 0) or None
    level_bridge = CoalescedLevelBridge(bubble, AppHelper.callAfter)
    recorder = Recorder(device=device, on_level=level_bridge.submit)

    controller = AppController(
        cfg, recorder, stt_backend, formatter, bubble,
        dictionary_terms, corrections, paths["history"],
    )
    controller._level_bridge = level_bridge  # keep the coalescer alive

    # Live edit cues: watch the target field after each insertion.
    if cfg.get("learning", {}).get("live_cues", True):
        from .editwatcher import EditWatcher
        controller._watcher = EditWatcher(controller)

    # menu-bar icon with Settings…/Quit (keep references alive on the controller)
    controller._status_item, controller._status_target = \
        build_status_item(controller.open_settings, controller.reload_dictionary,
                          controller.open_onboarding,
                          on_notice=bubble.notice)

    monitor = HotkeyMonitor(cfg, controller.on_press, controller.on_release,
                            controller.on_toggle,
                            is_locked=lambda: controller.state == "locked",
                            on_escape=controller.on_escape)
    monitor.start()
    controller._hotkey_monitor = monitor  # keep alive

    # Watch app switches to capture edits made to the last insertion.
    import objc
    from Foundation import NSObject
    global _AppSwitchObserver
    try:
        _AppSwitchObserver
    except NameError:
        class _AppSwitchObserver(NSObject):
            def initWithCallback_(self, cb):
                self = objc.super(_AppSwitchObserver, self).init()
                if self is None:
                    return None
                self._cb = cb
                return self

            def appActivated_(self, note):
                try:
                    app = note.userInfo().get("NSWorkspaceApplicationKey")
                    if app is not None:
                        self._cb(app.bundleIdentifier() or "")
                except Exception:
                    pass

    from AppKit import NSWorkspace
    observer = _AppSwitchObserver.alloc().initWithCallback_(controller.on_app_switch)
    NSWorkspace.sharedWorkspace().notificationCenter() \
        .addObserver_selector_name_object_(
            observer, "appActivated:",
            "NSWorkspaceDidActivateApplicationNotification", None)
    controller._app_switch_observer = observer  # keep alive

    # Display sleep/wake, screen reconfiguration, and Spaces can leave the
    # status strip AppKit-visible while WindowServer stops compositing it.
    # Bubble.handle_display_lifecycle rebuilds/re-verifies on the main thread
    # without permanent idle polling.
    global _DisplayLifecycleObserver
    try:
        _DisplayLifecycleObserver
    except NameError:
        class _DisplayLifecycleObserver(NSObject):
            def initWithCallback_(self, cb):
                self = objc.super(_DisplayLifecycleObserver, self).init()
                if self is None:
                    return None
                self._cb = cb
                return self

            def displayLifecycle_(self, note):
                try:
                    name = str(note.name()) if note is not None else "unknown"
                except Exception:
                    name = "unknown"
                try:
                    self._cb(name)
                except Exception as exc:
                    log.info("display lifecycle handler failed: %s", exc)

    def _on_display_lifecycle(reason: str):
        # Same observer for Bubble presentation recovery and runtime
        # permissions/hotkey recovery after sleep — never a second competing
        # NSWorkspace observer.
        handler = getattr(bubble, "handle_display_lifecycle", None)
        if callable(handler):
            handler(reason)
        if is_wake_lifecycle_reason(reason):
            try:
                controller.handle_runtime_wake(reason)
            except Exception as exc:
                log.info("runtime wake handler failed: %s", exc)

    display_observer = _DisplayLifecycleObserver.alloc().initWithCallback_(
        _on_display_lifecycle)
    ws_center = NSWorkspace.sharedWorkspace().notificationCenter()
    for notif in (
        "NSWorkspaceDidWakeNotification",
        "NSWorkspaceScreensDidWakeNotification",
        "NSWorkspaceActiveSpaceDidChangeNotification",
    ):
        try:
            ws_center.addObserver_selector_name_object_(
                display_observer, "displayLifecycle:", notif, None)
        except Exception as exc:
            log.info("Could not observe %s: %s", notif, exc)
    try:
        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            display_observer, "displayLifecycle:",
            "NSApplicationDidChangeScreenParametersNotification", None)
    except Exception as exc:
        log.info("Could not observe screen parameters: %s", exc)
    controller._display_lifecycle_observer = display_observer  # keep alive

    # An accessory app's windows stay off-screen until the app has been
    # activated once (Window Server quirk). Activate briefly at launch, then
    # return focus to the app the user was in.
    from AppKit import NSWorkspace
    previous = NSWorkspace.sharedWorkspace().frontmostApplication()
    app.activateIgnoringOtherApps_(True)
    AppHelper.callAfter(_yield_focus, previous)

    # Ctrl+C / SIGTERM clean shutdown. Python signal handlers only run when
    # the interpreter gets cycles — NSApplication's run loop starves them, so
    # a repeating no-op NSTimer is installed to pump Python (the handler runs
    # at the next timer tick at the latest).
    _install_signal_handlers(app)

    # First run, or a new executable identity without its own TCC grants:
    # reopen setup. The latter is common when moving from a terminal/dev build
    # to the unsigned DMG app while keeping the same ~/.golos configuration.
    if _needs_onboarding(cfg, permission_status):
        AppHelper.callAfter(controller.open_onboarding)
        if cfg.get("app", {}).get("onboarded"):
            AppHelper.callAfter(
                bubble.notice,
                "Permissions needed for this copy of golos", "warn", 3.0)

    log.info("dictate running. Hold %s to talk; %s+Space toggles locked mode.",
             cfg.get("hotkey", {}).get("hold_key", "fn"),
             cfg.get("hotkey", {}).get("hold_key", "fn"))
    app.run()


_SignalPumper = None


def _install_signal_handlers(app):
    """SIGINT/SIGTERM -> log + terminate the NSApplication cleanly."""
    import os
    import signal
    import objc
    from Foundation import NSObject, NSTimer

    def _shutdown(signum, frame):
        log.info("shutting down (signal %d)", signum)
        try:
            app.terminate_(None)
        except Exception:
            os._exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    global _SignalPumper
    if _SignalPumper is None:
        class _Pumper(NSObject):
            def pump_(self, timer):
                pass  # no-op: gives the interpreter cycles for pending signals

        _SignalPumper = _Pumper

    pumper = _SignalPumper.alloc().init()
    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.5, pumper, "pump:", None, True)
    # Keep both alive for the process lifetime.
    _install_signal_handlers._refs = (pumper, timer)


def _yield_focus(previous):
    """Return activation to the app that was frontmost before our launch bump."""
    from AppKit import NSApplicationActivateIgnoringOtherApps
    if previous is not None and not previous.isTerminated():
        previous.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
