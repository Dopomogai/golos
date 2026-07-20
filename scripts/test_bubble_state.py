"""Headless regression checks for notch state-generation handoffs."""

from dictate.bubble import Bubble


class _Panel:
    def __init__(self):
        self.visible = True
        self.alpha = 1.0

    def isVisible(self):
        return self.visible

    def orderFrontRegardless(self):
        self.visible = True

    def orderOut_(self, _sender):
        self.visible = False

    def setAlphaValue_(self, value):
        self.alpha = value


class _View:
    def __init__(self):
        self.states = []

    def setState_(self, state):
        self.states.append(state)


class _WingsView:
    def __init__(self):
        self.modes = []
        self._on_collapse_done = None
        self.collapse_started = False

    def setMode_(self, mode):
        self.modes.append(mode)

    def startCollapse(self):
        self.collapse_started = True

    def stopAnimation(self):
        pass


def _bubble():
    bubble = object.__new__(Bubble)
    bubble._state = "recording"
    bubble._vis_gen = 4
    bubble._notice_gen = 0
    bubble._notice_surface = "pill"
    bubble._geometry = (100, 200, 900)
    bubble._collapse = 0.0
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


def test_newer_state_invalidates_old_collapse_callback():
    bubble = _bubble()
    bubble.set_state("processing")
    callback = bubble.wings_view._on_collapse_done

    bubble.set_state("success")
    assert bubble.wings_view.modes == ["success"]
    callback()

    assert bubble.wings_view.modes == ["success"]


if __name__ == "__main__":
    test_processing_collapse_enters_processing_mode()
    test_newer_state_invalidates_old_collapse_callback()
    print("PASS: processing collapse generation handoff")
