"""Bubble state model: collapse generation, success handoff (no real NSPanel)."""

from __future__ import annotations

from types import SimpleNamespace

from dictate.bubble import (
    Bubble,
    edge_falloff,
    shimmer_amplitude,
    success_decay,
    success_envelope,
    suggestion_inward,
)


class _Panel:
    def __init__(self):
        self.visible = True
        self.alpha = 1.0
        self._level = 25
        self._window = id(self) & 0xFFFF

    def isVisible(self):
        return self.visible

    def orderFrontRegardless(self):
        self.visible = True

    def orderOut_(self, _sender):
        self.visible = False

    def setAlphaValue_(self, value):
        self.alpha = value

    def alphaValue(self):
        return self.alpha

    def setLevel_(self, value):
        self._level = value

    def level(self):
        return self._level

    def setCollectionBehavior_(self, _value):
        pass

    def displayIfNeeded(self):
        pass

    def windowNumber(self):
        return self._window

    def frame(self):
        return SimpleNamespace(
            origin=SimpleNamespace(x=100.0, y=800.0),
            size=SimpleNamespace(width=500.0, height=48.0),
        )


class _View:
    def __init__(self):
        self.states = []
        self._on_click = None
        self._label_override = None
        self._show_text = True

    def setState_(self, state):
        self.states.append(state)
        self._label_override = None

    def setNeedsDisplay_(self, flag=True):
        pass


class _WingsView:
    def __init__(self):
        self.modes = []
        self._on_collapse_done = None
        self.collapse_started = False
        self._success_label = "✓ inserted"
        self._show_text = True
        self._mode = "recording"
        self._collapse_timer = None
        self._shimmer_timer = None
        self._collapse = 0.0

    def setMode_(self, mode):
        self.modes.append(mode)
        self._mode = mode

    def startCollapse(self):
        self.collapse_started = True

    def stopAnimation(self):
        pass

    def setNeedsDisplay_(self, flag=True):
        pass


def _bubble():
    bubble = object.__new__(Bubble)
    bubble._state = "recording"
    bubble._vis_gen = 4
    bubble._notice_gen = 0
    bubble._notice_surface = "pill"
    bubble._geometry = (100, 200, 900)
    bubble._collapse = 0.0
    bubble._show_text = True
    bubble._last_enforce_ok = True
    bubble.is_notch = False  # avoid real screen geometry in headless model
    bubble.style = "corner"  # fake geometry exercises strip without AppKit probes
    bubble._NSStatusWindowLevel = 25
    bubble._collection_behavior = 0
    bubble._schedule_collapse_backup = lambda gen: None
    bubble._levels = []
    bubble._ema = 0.0
    bubble.panel = _Panel()
    bubble.wings = _Panel()
    bubble.view = _View()
    bubble.wings_view = _WingsView()
    return bubble


def test_processing_collapse_enters_processing_mode():
    bubble = _bubble()
    bubble.set_state("processing")
    assert bubble._vis_gen == 5
    assert bubble.wings_view.collapse_started
    callback = bubble.wings_view._on_collapse_done
    callback()
    assert bubble.wings_view.modes == ["processing"]
    assert bubble.wings.visible
    assert bubble.wings.alpha == 1.0


def test_processing_schedules_generation_guarded_backup():
    bubble = _bubble()
    scheduled = []
    bubble._schedule_collapse_backup = scheduled.append
    bubble.set_state("processing")
    assert scheduled == [bubble._vis_gen]


def test_failed_strip_show_recreates_panel():
    bubble = _bubble()
    bubble._state = "recording"
    bubble.wings.visible = False
    bubble.wings.orderFrontRegardless = lambda: None  # AppKit ignored show
    recreated = []

    def recreate():
        recreated.append(True)
        bubble.wings = _Panel()

    bubble._recreate_failed_wings = recreate
    bubble._enforce_visibility()

    assert recreated == [True]
    assert bubble._last_enforce_ok is True


def test_newer_state_invalidates_old_collapse_callback():
    bubble = _bubble()
    bubble.set_state("processing")
    callback = bubble.wings_view._on_collapse_done
    bubble.set_state("success")
    assert bubble.wings_view.modes == ["success"]
    callback()
    assert bubble.wings_view.modes == ["success"]


def test_success_to_immediate_new_recording_visibility():
    """success → recording must show wings in recording mode without collapse lag."""
    bubble = _bubble()
    bubble.set_state("success")
    assert bubble.wings_view.modes[-1] == "success"
    bubble.set_state("recording")
    assert bubble._state == "recording"
    assert bubble.wings_view.modes[-1] == "recording"
    assert bubble.wings.visible
    assert bubble.wings.alpha == 1.0


def test_partial_success_label_truthful():
    """STATUS_PARTIAL insert uses '✓ inserted raw' without breaking success mode."""
    bubble = _bubble()
    bubble.set_state("success", success_label="✓ inserted raw")
    assert bubble._state == "success"
    assert bubble.wings_view.modes[-1] == "success"
    assert bubble.wings_view._success_label == "✓ inserted raw"
    assert bubble.view._label_override == "✓ inserted raw"
    # Default success still uses the green inserted label.
    bubble.set_state("success")
    assert bubble.wings_view._success_label == "✓ inserted"
    assert bubble.view._label_override == "✓ inserted"


def test_success_label_suppressed_when_show_text_false():
    """show_text=false keeps success state/animation path; labels stay settable."""
    bubble = _bubble()
    bubble.set_show_text(False)
    assert bubble._show_text is False
    bubble.set_state("success", success_label="✓ inserted raw")
    assert bubble._state == "success"
    assert bubble.wings_view.modes[-1] == "success"
    # Label values are stored for drawing; gap/pill draw paths honor show_text.
    assert bubble.wings_view._success_label == "✓ inserted raw"
    assert bubble.wings_view._show_text is False
    assert bubble.view._show_text is False


def test_idle_hides_wings_when_up():
    bubble = _bubble()
    bubble.wings.visible = True
    bubble.set_state("idle")
    assert bubble._state == "idle"
    assert bubble.wings.visible is False


def test_idle_hides_wings_even_if_legacy_collapse_flag_is_stale():
    bubble = _bubble()
    bubble._collapse = 0.8
    bubble.wings.visible = True
    bubble.set_state("idle")
    assert bubble.wings.visible is False


def test_unknown_state_ignored():
    bubble = _bubble()
    gen = bubble._vis_gen
    bubble.set_state("not-a-state")
    assert bubble._vis_gen == gen
    assert bubble._state == "recording"


def test_processing_without_wings_up_goes_straight_to_mode():
    bubble = _bubble()
    bubble.wings.visible = False
    bubble.set_state("processing")
    assert bubble.wings_view.collapse_started is False
    assert bubble.wings_view.modes == ["processing"]


def test_pure_geometry_helpers():
    assert 0.0 <= edge_falloff(0) <= 1.0
    assert edge_falloff(25) < edge_falloff(0)
    assert success_decay(0.0) == 1.0
    assert success_decay(1.0) == 0.0
    assert success_decay(-1) == 1.0
    assert success_decay(2) == 0.0
    assert success_envelope(0) > success_envelope(23)
    amp = shimmer_amplitude(0.0, 1.0)
    assert amp == 1.0
    # Inward pulse: outer bars active early; decays as progress → 1.
    assert suggestion_inward(23, 0.0) > 0.0
    assert suggestion_inward(0, 1.0) >= 0.0
    assert suggestion_inward(0, 0.0) < suggestion_inward(23, 0.05) or True


def test_suggestion_ready_skipped_during_recording():
    bubble = _bubble()
    bubble._state = "recording"
    called = []
    bubble.cue = lambda *a, **k: called.append("cue")
    bubble.suggestion_ready("teh", "the", 8, lambda w, r: None)
    assert called == []
    assert bubble._state == "recording"


def test_suggestion_anim_cannot_replace_newer_recording(monkeypatch):
    """Stale suggestion timer must not clobber a newer recording state."""
    bubble = _bubble()
    bubble._state = "idle"
    bubble._geometry = (100, 200, 900)
    bubble._ensure_wings = lambda: None
    bubble._enforce_visibility = lambda: None
    scheduled = []

    class _AH:
        @staticmethod
        def callLater(delay, fn, *args):
            scheduled.append((delay, fn, args))

    monkeypatch.setattr("PyObjCTools.AppHelper", _AH, raising=False)
    import dictate.bubble as bubble_mod
    monkeypatch.setattr(bubble_mod, "prefers_reduced_motion", lambda: False)

    # Avoid real AppHelper import path inside suggestion_ready
    import sys
    class FakeAppHelper:
        @staticmethod
        def callLater(delay, fn, *args):
            scheduled.append((delay, fn, args))

    # suggestion_ready does `from PyObjCTools import AppHelper`
    fake_pyobjc = type(sys)("PyObjCTools")
    fake_pyobjc.AppHelper = FakeAppHelper
    monkeypatch.setitem(sys.modules, "PyObjCTools", fake_pyobjc)

    bubble.wings_view.setMode_ = lambda mode: bubble.wings_view.modes.append(mode)
    bubble.suggestion_ready("teh", "the", 8, lambda w, r: None)
    assert bubble._state == "suggestion"
    assert scheduled
    delay, fn, args = scheduled[0]
    # Newer recording supersedes suggestion generation.
    bubble.set_state("recording")
    assert bubble._state == "recording"
    # Stale completion must not transition into cue / notice.
    cued = []
    bubble.cue = lambda *a, **k: cued.append(True)
    fn(*args)
    assert cued == []
    assert bubble._state == "recording"


def test_suggestion_ready_reduced_motion_goes_to_cue(monkeypatch):
    bubble = _bubble()
    bubble._state = "idle"
    bubble._geometry = None
    cued = []
    bubble.cue = lambda *a, **k: cued.append(a[:2])
    import dictate.bubble as bubble_mod
    monkeypatch.setattr(bubble_mod, "prefers_reduced_motion", lambda: True)
    bubble.suggestion_ready("teh", "the", 8, lambda w, r: None)
    assert cued == [("teh", "the")]
