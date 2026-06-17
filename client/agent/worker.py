"""단일 워커 큐 — 해싱·전송을 순차 처리해 백프레셔를 제공한다(설계 §6).

발화 시점의 파일 존재 여부가 최종 심판이다: 존재하면 해싱·전송(created/modified/moved),
없으면 캐시의 기억된 지문으로 deleted 전송(캐시에 없으면 스킵).
"""

import logging
import queue
import threading
from pathlib import Path

from agent.cache import FingerprintCache
from agent.events import source_hint_for
from common.fingerprint import fingerprint_file
from agent.models import EVENT_CREATED, EVENT_DELETED, EVENT_MODIFIED, EVENT_MOVED, Task

logger = logging.getLogger("agent.worker")


class Worker:
    """Task를 순차 처리하는 단일 워커 스레드."""

    def __init__(self, cache: FingerprintCache, sender, fingerprint_file=fingerprint_file) -> None:
        self._cache = cache
        self._sender = sender
        self._fingerprint_file = fingerprint_file
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """워커 스레드를 시작한다."""
        self._thread.start()

    def stop(self) -> None:
        """종료 신호를 넣고 스레드가 끝날 때까지 기다린다."""
        self._queue.put(None)
        self._thread.join()

    def submit(self, task: Task) -> None:
        """처리할 Task를 큐에 넣는다."""
        self._queue.put(task)

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                self.process(task)
            except Exception as exc:  # 워커 루프는 어떤 예외에도 죽지 않는다
                logger.exception("워커 처리 실패: %s", exc)

    def process(self, task: Task) -> None:
        """Task 1건을 처리한다(테스트에서 직접 호출 가능)."""
        if task.moved_from:
            self._cache.pop(task.moved_from)

        path = Path(task.path)
        if path.exists():
            # 캐시에 이미 있던 경로면 modified, 처음 보는 경로면 created로 정한다.
            # watchdog가 새 파일에 created+modified를 쏴 task 라벨이 흔들려도 캐시가 진실의
            # 기준이다(이동은 moved_from으로 판별).
            was_known = self._cache.get(task.path) is not None
            try:
                fp = self._fingerprint_file(path)
            except OSError as exc:
                logger.warning("해싱 실패(잠김?) %s: %s", task.path, exc)
                return
            self._cache.put(task.path, fp)
            if task.moved_from:
                event_type = EVENT_MOVED
            elif was_known:
                event_type = EVENT_MODIFIED
            else:
                event_type = EVENT_CREATED
            self._sender.send(
                sha256=fp.sha256, fuzzy_hash=fp.fuzzy_hash, size=fp.size,
                name=path.name, event_type=event_type,
                source_hint=source_hint_for(task.path),
            )
            return

        cached = self._cache.pop(task.path)
        if cached is None:
            logger.info("삭제 이벤트지만 캐시에 지문 없음, 스킵: %s", task.path)
            return
        self._sender.send(
            sha256=cached.sha256, fuzzy_hash=cached.fuzzy_hash, size=cached.size,
            name=path.name, event_type=EVENT_DELETED,
            source_hint=source_hint_for(task.path),
        )
