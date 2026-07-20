"""Headless regression checks for interruptible completion state."""

from dictate.app import AppController


class _Bubble:
    def __init__(self):
        self.states = []

    def set_state(self, state):
        self.states.append(state)


def _controller():
    return AppController({}, object(), object(), object(), _Bubble(), [], {}, "")


def test_press_during_success_starts_recording():
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    controller._set_state("success")

    controller.on_press()

    assert started == ["recording"]


def test_toggle_during_success_starts_locked_recording():
    controller = _controller()
    started = []
    controller._begin_recording = started.append
    controller._set_state("success")

    controller.on_toggle()

    assert started == ["locked"]


def test_old_success_timer_cannot_cancel_new_recording():
    controller = _controller()
    success_gen = controller._set_state("success")
    controller._set_state("recording")

    controller._finish_success(success_gen)

    assert controller.state == "recording"
    assert controller.bubble.states == ["success", "recording"]


def test_current_success_timer_returns_to_idle():
    controller = _controller()
    success_gen = controller._set_state("success")

    controller._finish_success(success_gen)

    assert controller.state == "idle"
    assert controller.bubble.states == ["success", "idle"]


if __name__ == "__main__":
    test_press_during_success_starts_recording()
    test_toggle_during_success_starts_locked_recording()
    test_old_success_timer_cannot_cancel_new_recording()
    test_current_success_timer_returns_to_idle()
    print("PASS: interruptible success-state handoff")
