"""Live edit cues: watch the target field after an insertion and surface the
user's manual corrections within seconds, clickable to keep.

After each successful insert, poll the focused field every 2.5 s for up to
3 minutes. A (wrong -> right) pair becomes a cue only when the field text is
UNCHANGED between two consecutive polls (the user paused) — mid-typing never
fires. Replacements only; appends/prepend alone produce no pairs.

Shared state with the learning loop: pairs the watcher records go into its
`seen` set; capture_edit filters that set out so nothing is recorded twice.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

POLL_INTERVAL = 2.5   # seconds between field reads
MAX_WATCH_SECONDS = 180.0


class EditWatcher:
    """One watcher per app; `start()` re-arms it for the newest insertion."""

    def __init__(self, app_controller):
        self.app_controller = app_controller
        self.seen: set[tuple[str, str]] = set()  # pairs recorded for this insertion
        self._insertion = None
        self._last_text = None
        self._gen = 0
        self._started = 0.0
        self._busy = False           # a poll worker is in flight

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        cfg = self.app_controller.cfg
        if not cfg.get("learning", {}).get("live_cues", True):
            return
        li = self.app_controller.last_insertion
        if not li:
            return
        self._insertion = li
        self.seen = set()
        self._last_text = None
        self._started = time.monotonic()
        self._gen += 1
        log.info("Edit watcher started (poll every %.1fs).", POLL_INTERVAL)
        self._schedule()

    def stop(self, reason: str = "") -> None:
        if self._insertion is not None:
            log.info("Edit watcher stopped (%s).", reason or "manual")
        self._gen += 1          # pending callLater polls become no-ops
        self._insertion = None
        self._last_text = None

    def _schedule(self) -> None:
        from PyObjCTools import AppHelper
        AppHelper.callLater(POLL_INTERVAL, self._poll, self._gen)

    # -- polling -------------------------------------------------------------

    def _poll(self, gen: int) -> None:
        """Main-thread tick: cheap guards + schedule the WORKER that does the
        AX read and the diff (slow fields can stall the run loop)."""
        if gen != self._gen or self._insertion is None:
            return  # superseded or stopped — no timer leak
        li = self.app_controller.last_insertion
        if li is not self._insertion:
            self.stop("insertion consumed")
            return
        if time.monotonic() - self._started > MAX_WATCH_SECONDS:
            self.stop("3 minutes elapsed")
            return
        if self._busy:
            self._schedule()  # previous poll still working — skip this tick
            return
        self._busy = True
        threading.Thread(target=self._poll_work,
                         args=(gen, li), daemon=True).start()
        self._schedule()

    def _poll_work(self, gen: int, li: dict) -> None:
        """Worker: frontmost check + AX read + pair extraction."""
        from PyObjCTools import AppHelper
        try:
            from .context import frontmost_context
            from .learning import read_focused_text
            from dictate_core.learning import suggest_pairs
            front = frontmost_context()
            if li.get("bundle_id") and front.get("bundle_id") != li["bundle_id"]:
                AppHelper.callAfter(self._stop_from_worker, gen, "app switch")
                return
            text = read_focused_text()
            if text is None:
                return
            pairs = suggest_pairs(text, li.get("final", ""))
            AppHelper.callAfter(self._handle_poll_result, gen, text, pairs)
        except Exception as e:
            log.info("Edit watcher poll failed: %s", e)
        finally:
            self._busy = False

    def _stop_from_worker(self, gen: int, reason: str) -> None:
        if gen == self._gen:
            self.stop(reason)

    def _handle_poll_result(self, gen: int, text: str,
                            pairs: list[tuple[str, str]]) -> None:
        """Main thread: debounce + fire at most one pending cue."""
        if gen != self._gen or self._insertion is None:
            return
        if text == self._last_text:
            # stable field (user paused): fire at most one pending cue
            for wrong, right in pairs:
                if (wrong, right) not in self.seen:
                    self.seen.add((wrong, right))
                    self._fire(wrong, right)
                    break
        self._last_text = text

    # -- cue -----------------------------------------------------------------

    def _fire(self, wrong: str, right: str) -> None:
        log.info("Edit cue: %r -> %r", wrong, right)
        from .learning import append_suggestions
        try:
            append_suggestions(self.app_controller.cfg["paths"]["suggestions"],
                               self._insertion.get("app_name", ""),
                               [(wrong, right)])
        except Exception as e:
            log.warning("Could not record cue to suggestions: %s", e)
        secs = self.app_controller.cfg.get("learning", {}) \
            .get("live_cue_seconds", 8)
        self.app_controller.bubble.cue(
            wrong, right, secs,
            lambda w, r: self.app_controller.accept_cue(w, r))
