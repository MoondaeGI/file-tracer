"""수집기들의 단일 서버 egress. TraceEvent를 받아 큐에 쌓고 Sender로 순차 전송한다.

채널·지문을 모른다 — 받은 TraceEvent를 모드 b로 직렬화해 보낼 뿐이다. 향후 outbox
버퍼·dedup·인증 토큰이 이 한 곳에 붙는다(현재는 큐 + Sender).
"""

import logging
import queue
import threading

from common.events import TraceEvent

logger = logging.getLogger("core.core")


class CollectorCore:
    """단일 워커 스레드로 TraceEvent를 서버에 전송한다."""

    def __init__(self, sender) -> None:
        self._sender = sender
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join()

    def submit(self, event: TraceEvent) -> None:
        """전송할 TraceEvent를 큐에 넣는다."""
        self._queue.put(event)

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                break
            try:
                self.process(event)
            except Exception as exc:  # 코어 루프는 어떤 예외에도 죽지 않는다
                logger.exception("코어 전송 실패: %s", exc)

    def process(self, event: TraceEvent) -> bool:
        """TraceEvent 1건을 서버로 전송한다(동기, 테스트에서 직접 호출 가능)."""
        return self._sender.send(
            sha256=event.sha256, fuzzy_hash=event.fuzzy_hash, size=event.size,
            name=event.name, event_type=event.event_type, source_hint=event.source_hint,
            user=event.user, metadata=event.metadata,
        )
