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

log = logging.getLogger(__name__)


class AppController:
    """Owns dictation state and wires hotkeys → recorder → STT → format → insert.

    Hotkey handlers (on_press/on_release/on_toggle/on_escape) are invoked on the
    main thread by HotkeyMonitor. Long work is always offloaded: context gather
    and edit capture on daemon workers, the full pipeline on another worker.
    `self._lock` only protects state transitions at hotkey boundaries — the
    pipeline itself does not hold it across network I/O.
    """

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

    # -- UI state helper -------------------------------------------------

    def _set_state(self, state):
        """Main thread: flip controller + bubble state and mirror callbacks."""
        self._state_gen += 1
        self.state = state
        self.bubble.set_state(state)
        log.info("State: %s", state)
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

    # -- hotkey callbacks (main thread) ----------------------------------

    def on_press(self):
        """Hold-key down. idle/success→recording, or end locked mode."""
        handler = self.hotkey_test_handler
        if handler is not None:
            handler("press")
            return
        with self._lock:
            if self.state in ("idle", "success"):
                self._begin_recording("recording")
                return
            if self.state != "locked":
                return
        # locked recording: a single fn press ends it (Wispr Flow behavior)
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
        with self._lock:
            if self.state == "recording":
                self._set_state("locked")
                return
            if self.state in ("idle", "success"):
                self._begin_recording("locked")
                return
            if self.state != "locked":
                return
        self._finish_recording()

    # -- settings / live reload -------------------------------------------

    def on_app_switch(self, new_bundle_id: str):
        """Frontmost app changed (NSWorkspaceDidActivateApplicationNotification).

        If an insertion is still pending in the app we just left, capture any
        manual edit from that app's focused field (best-effort AX via pid).
        """
        li = self.last_insertion
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
            pairs = capture_edit(self, text=text)
            if pairs:
                log.info("Learned %d suggestion(s) from your edit in %s.",
                         len(pairs), li.get("app_name", ""))
                AppHelper.callAfter(self._notice_learning, pairs)
        except Exception as e:
            log.info("App-switch edit capture failed: %s", e)

    def _capture_pending_edit(self):
        """45s fallback timer after an insertion (fires only if still pending)."""
        if not self.last_insertion:
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
            log.info("Cue accepted: %r -> %r added to corrections.", wrong, right)
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
            threading.Thread(target=self._discard_recording, daemon=True).start()
        elif state == "processing":
            self._cancel_requested = True
            log.info("Cancel requested — pipeline result will be discarded.")

    def _discard_recording(self):
        """Worker: abort the stream (no callback-completion wait) and discard."""
        try:
            self.recorder.abort()
            log.info("Recording discarded (cancelled by user).")
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
        """Write the captured wav to ~/.dictate/recordings/YYYY-MM-DD/ (raw
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
        """
        from PyObjCTools import AppHelper
        from .insert import insert_text
        from .history import append_history

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
        insert_scheduled = False
        try:
            if self.stt is None:
                log.error("No STT backend available.")
                return
            prompt = ", ".join(self.dictionary_terms)
            raw = self.stt.transcribe(audio, prompt=prompt)
            log.info("Raw transcript: %r", raw)
            if not raw:
                return
            # Fast mode: short single-line dictations skip stage 2 entirely;
            # literal corrections are applied locally instead of by the LLM.
            fast = False
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
                final = self.formatter.format(raw, self._fmt_context,
                                              audio_wav=audio_wav)
            if final != raw:
                log.info("Formatted: %r", final)

            if self._cancel_requested:
                log.info("Insertion cancelled by user; result discarded.")
                return

            def insert_and_flash():
                ins_cfg = self.cfg.get("insert", {})
                if insert_text(final,
                               method=ins_cfg.get("method", "auto"),
                               restore_clipboard=ins_cfg.get(
                                   "restore_clipboard", False)):
                    import time as _time
                    self.last_insertion = {
                        "ts": _time.time(),
                        "app_name": self._context.get("app_name", ""),
                        "bundle_id": self._context.get("bundle_id", ""),
                        "pid": self._context.get("pid"),
                        "raw": raw,
                        "final": final,
                        # Retained WAV path only when [audio] keep_recordings
                        # saved one; never store raw audio bytes here.
                        "audio_path": audio_path,
                    }
                    # Fallback edit-capture: if the insertion is still pending
                    # in 45s (no new recording, no app switch), check now.
                    AppHelper.callLater(45, self._capture_pending_edit)
                    # Live edit cues: watch the field for manual corrections.
                    if self._watcher is not None:
                        self._watcher.start()
                    success_gen = self._set_state("success")
                    AppHelper.callLater(1.2, self._finish_success, success_gen)
                else:
                    self._set_state("idle")

            AppHelper.callAfter(insert_and_flash)
            insert_scheduled = True
            try:
                append_history(
                    self.history_path,
                    self._context.get("app_name", ""),
                    self._context.get("bundle_id", ""),
                    raw, final,
                    context=_history_context(self._fmt_context),
                    audio=audio_path,
                    fast=fast,
                )
            except Exception as e:
                log.warning("Could not write history: %s", e)
        except Exception as e:
            log.exception("Pipeline failed: %s", e)
        finally:
            self._cancel_requested = False
            if not insert_scheduled:
                AppHelper.callAfter(self._set_state, "idle")


def _history_context(context: dict) -> dict:
    """Context dict for history.jsonl: workspace_files truncated to 50 lines."""
    ctx = dict(context)
    files = ctx.get("workspace_files")
    if isinstance(files, str) and files.count("\n") > 50:
        ctx["workspace_files"] = "\n".join(files.splitlines()[:50]) + "\n…"
    return ctx


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
        log.info("Could not verify formatter model audio support: %s", e)


def _env_key(section):
    from .config import env_key
    return env_key(section)


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
    log_report()

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

    device = cfg.get("audio", {}).get("device", 0) or None
    recorder = Recorder(
        device=device,
        on_level=lambda rms: AppHelper.callAfter(bubble.push_level, rms),
    )

    controller = AppController(
        cfg, recorder, stt_backend, formatter, bubble,
        dictionary_terms, corrections, paths["history"],
    )

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

    # First run: onboarding wizard (permissions, fn key, API key).
    if not cfg.get("app", {}).get("onboarded"):
        AppHelper.callAfter(controller.open_onboarding)

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
