"""Live edit cues: watch the target field after an insertion and surface the
user's manual corrections within seconds, clickable to keep.

After each successful insert, poll the focused field every 1.0 s for up to
3 minutes. A (wrong -> right) pair becomes a cue only when the field text is
UNCHANGED between two consecutive polls (the user paused) — mid-typing never
fires. A locally detected pending replacement is flushed if the user switches
apps before the second stable poll, so a quick edit-then-switch is not lost.
Replacements only; appends/prepend alone produce no pairs.

Shared state with the learning loop: pairs the watcher records go into its
`seen` set; capture_edit filters that set out so nothing is recorded twice.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

POLL_INTERVAL = 1.0   # fast enough to retain edit-then-switch corrections
MAX_WATCH_SECONDS = 180.0


class EditWatcher:
    """One watcher per app; `start()` re-arms it for the newest insertion."""

    def __init__(self, app_controller):
        self.app_controller = app_controller
        self.seen: set[tuple[str, str]] = set()  # pairs recorded for this insertion
        self._insertion = None
        self._last_text = None
        self._pending_pairs: list[tuple[str, str]] = []
        self._gen = 0
        self._started = 0.0
        self._busy = False           # a poll worker is in flight

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Arm for the current last_insertion. Bumps generation so old polls die."""
        cfg = self.app_controller.cfg
        if not cfg.get("learning", {}).get("live_cues", True):
            return
        li = self.app_controller.last_insertion
        if not li:
            return
        self._insertion = li
        self.seen = set()
        self._last_text = None
        self._pending_pairs = []
        self._started = time.monotonic()
        self._gen += 1
        log.info("Edit watcher started (poll every %.1fs).", POLL_INTERVAL)
        self._schedule()

    def stop(self, reason: str = "") -> None:
        """Disarm. Generation bump makes in-flight/scheduled polls no-ops."""
        if self._insertion is not None:
            log.info("Edit watcher stopped (%s).", reason or "manual")
        self._gen += 1          # pending callLater polls become no-ops
        self._insertion = None
        self._last_text = None
        self._pending_pairs = []

    def flush_pending(self, reason: str = "focus loss") -> bool:
        """Record one locally detected edit before disarming.

        The reviewer intentionally waits for a stable field. This fallback is
        deterministic and human-gated: it only preserves a replacement pair
        already found in the most recent AX snapshot, then shows the ordinary
        clickable cue. Returns True when a cue was emitted.
        """
        if self._insertion is None:
            return False
        for wrong, right in self._pending_pairs:
            if (wrong, right) in self.seen:
                continue
            self.seen.add((wrong, right))
            log.info("Flushing pending edit cue on %s.", reason)
            self._fire(wrong, right, {
                "provenance": "deterministic-focus-loss",
                "from_reviewer": False,
            })
            self._pending_pairs = []
            return True
        return False

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
        """Worker: frontmost check + AX read + pair extraction.

        Pair extraction (including the optional learning reviewer) runs only
        when the field text matches the previous poll — mid-typing never
        burns a reviewer attempt or records a cue.
        """
        from PyObjCTools import AppHelper
        try:
            from .context import frontmost_context
            from .learning import propose_pairs, read_focused_text
            from dictate_core.learning import suggest_pairs
            front = frontmost_context()
            if li.get("bundle_id") and front.get("bundle_id") != li["bundle_id"]:
                AppHelper.callAfter(self._stop_from_worker, gen, "app switch")
                return
            text = read_focused_text()
            if text is None:
                return
            last = self._last_text
            if text != last:
                # Still changing: cache only the local diff. Network review
                # waits for stability, but focus loss can retain this pair.
                pending = suggest_pairs(text, li.get("final", ""))
                AppHelper.callAfter(
                    self._handle_poll_result, gen, text, None,
                    {"pending_pairs": pending})
                return
            # Stable pause (second consecutive identical read).
            pairs, meta = propose_pairs(li, text, self.app_controller.cfg)
            AppHelper.callAfter(self._handle_poll_result, gen, text, pairs, meta)
        except Exception as e:
            log.info("Edit watcher poll failed: %s", e)
        finally:
            self._busy = False

    def _stop_from_worker(self, gen: int, reason: str) -> None:
        if gen == self._gen:
            if reason == "app switch":
                self.flush_pending(reason)
            self.stop(reason)

    def _handle_poll_result(self, gen: int, text: str,
                            pairs: list[tuple[str, str]] | None,
                            meta: dict | None = None) -> None:
        """Main thread: debounce + fire at most one pending cue."""
        if gen != self._gen or self._insertion is None:
            return
        if pairs is None:
            # Unstable poll: only advance the debounce snapshot.
            self._last_text = text
            self._pending_pairs = list((meta or {}).get("pending_pairs") or [])
            return
        meta = meta or {}
        # Stable field (user paused): fire at most one pending cue.
        for wrong, right in pairs:
            if (wrong, right) not in self.seen:
                self.seen.add((wrong, right))
                self._fire(wrong, right, meta)
                break
        self._pending_pairs = []
        self._last_text = text

    # -- cue -----------------------------------------------------------------

    def _fire(self, wrong: str, right: str, meta: dict | None = None) -> None:
        log.info("Edit cue ready.")
        meta = meta or {}
        from .learning import append_suggestions
        try:
            append_suggestions(
                self.app_controller.cfg["paths"]["suggestions"],
                self._insertion.get("app_name", ""),
                [(wrong, right)],
                provenance=meta.get("provenance"),
                model=meta.get("model"),
                confidences=(meta.get("confidences") or [None])[:1],
            )
        except Exception as e:
            log.warning("Could not record cue to suggestions: %s", e)
        secs = self.app_controller.cfg.get("learning", {}) \
            .get("live_cue_seconds", 8)
        if meta.get("from_reviewer"):
            present = getattr(self.app_controller, "present_reviewer_suggestions",
                              None)
            if present is not None:
                present([(wrong, right)], meta)
                return
        self.app_controller.bubble.cue(
            wrong, right, secs,
            lambda w, r: self.app_controller.accept_cue(w, r))
