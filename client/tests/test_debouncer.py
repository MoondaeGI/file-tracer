"""디바운서 테스트 — 타이머 주입으로 결정적."""

from agent.debouncer import Debouncer
from agent.models import Pending


class FakeTimer:
    """threading.Timer 대체: start/cancel 기록, fire()로 수동 발화."""

    instances: list["FakeTimer"] = []

    def __init__(self, seconds: float, callback) -> None:
        self.seconds = seconds
        self.callback = callback
        self.cancelled = False
        self.started = False
        FakeTimer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.callback()


def test_fire_calls_on_fire_with_latest_pending() -> None:
    FakeTimer.instances.clear()
    fired: list = []
    deb = Debouncer(0.1, lambda path, pending: fired.append((path, pending)),
                    timer_factory=FakeTimer)
    deb.schedule("C:\\a.txt", Pending(event_type="created"))
    FakeTimer.instances[-1].fire()
    assert fired == [("C:\\a.txt", Pending(event_type="created"))]


def test_reschedule_cancels_previous_and_keeps_latest() -> None:
    FakeTimer.instances.clear()
    fired: list = []
    deb = Debouncer(0.1, lambda path, pending: fired.append((path, pending)),
                    timer_factory=FakeTimer)
    deb.schedule("C:\\a.txt", Pending(event_type="created"))
    first = FakeTimer.instances[-1]
    deb.schedule("C:\\a.txt", Pending(event_type="modified"))
    assert first.cancelled is True
    FakeTimer.instances[-1].fire()
    assert fired == [("C:\\a.txt", Pending(event_type="modified"))]
