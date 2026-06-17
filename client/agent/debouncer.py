"""경로별 디바운스. 같은 경로의 연속 이벤트를 1건으로 합쳐 on_fire를 호출한다.

쓰기 버스트가 잦아들 때(seconds 동안 추가 이벤트 없음) 발화한다(설계 §6). 시간은
timer_factory로 주입 가능해 테스트가 결정적이다. 내부 dict는 락으로 보호한다.
"""

import threading
from collections.abc import Callable

from agent.models import Pending


class Debouncer:
    """경로별 타이머로 이벤트를 디바운스한다."""

    def __init__(
        self,
        seconds: float,
        on_fire: Callable[[str, Pending], None],
        timer_factory=threading.Timer,
    ) -> None:
        self._seconds = seconds
        self._on_fire = on_fire
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._timers: dict[str, object] = {}
        self._pending: dict[str, Pending] = {}

    def schedule(self, path: str, pending: Pending) -> None:
        """경로의 타이머를 (재)설정하고 최신 pending을 기억한다."""
        with self._lock:
            existing = self._timers.get(path)
            if existing is not None:
                existing.cancel()
            self._pending[path] = pending
            timer = self._timer_factory(self._seconds, lambda: self._fire(path))
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: str) -> None:
        with self._lock:
            pending = self._pending.pop(path, None)
            self._timers.pop(path, None)
        if pending is not None:
            self._on_fire(path, pending)

    def cancel_all(self) -> None:
        """대기 중인 모든 타이머를 취소한다."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._pending.clear()
