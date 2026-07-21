from dictate.app import CoalescedLevelBridge


class FakeBubble:
    def __init__(self):
        self.values = []

    def push_level(self, value):
        self.values.append(value)


def test_level_bridge_coalesces_backlog_to_latest_value():
    bubble = FakeBubble()
    queue = []
    bridge = CoalescedLevelBridge(bubble, queue.append)

    bridge.submit(0.1)
    bridge.submit(0.2)
    bridge.submit(0.9)

    assert len(queue) == 1
    queue.pop()()
    assert bubble.values == [0.9]


def test_level_bridge_schedules_next_value_after_drain():
    bubble = FakeBubble()
    queue = []
    bridge = CoalescedLevelBridge(bubble, queue.append)

    bridge.submit(0.1)
    queue.pop()()
    bridge.submit(0.2)

    assert len(queue) == 1
    queue.pop()()
    assert bubble.values == [0.1, 0.2]
