"""watchdog 핸들러와 파이프라인 배선. 이벤트 → 디바운스 → 워커 큐.

watchdog 콜백 스레드는 디바운서에 등록만 한다. 디바운스 발화 시 Task를 워커 큐에
넣고, 단일 워커가 해싱·전송한다.
"""

import logging

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent.cache import FingerprintCache
from agent.debouncer import Debouncer
from agent.events import should_ignore
from agent.models import (
    EVENT_CREATED,
    EVENT_DELETED,
    EVENT_MODIFIED,
    EVENT_MOVED,
    Pending,
    Task,
)
from agent.worker import Worker

logger = logging.getLogger("agent.watcher")


class _Handler(FileSystemEventHandler):
    """watchdog 이벤트를 필터링해 디바운서에 등록한다."""

    def __init__(self, debouncer: Debouncer, ignore_globs) -> None:
        self._debouncer = debouncer
        self._ignore_globs = ignore_globs

    def _filtered(self, path: str) -> bool:
        return should_ignore(path, self._ignore_globs)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.src_path):
            return
        self._debouncer.schedule(event.src_path, Pending(event_type=EVENT_CREATED))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.src_path):
            return
        self._debouncer.schedule(event.src_path, Pending(event_type=EVENT_MODIFIED))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.src_path):
            return
        self._debouncer.schedule(event.src_path, Pending(event_type=EVENT_DELETED))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.dest_path):
            return
        self._debouncer.schedule(
            event.dest_path, Pending(event_type=EVENT_MOVED, moved_from=event.src_path)
        )


class Watcher:
    """observer + 워커 묶음. start/stop로 수명을 관리한다."""

    def __init__(self, observer: Observer, worker: Worker, debouncer: Debouncer) -> None:
        self._observer = observer
        self._worker = worker
        self._debouncer = debouncer

    def start(self) -> None:
        self._worker.start()
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        self._debouncer.cancel_all()
        self._worker.stop()


def build_watcher(
    *,
    watch_paths,
    ignore_globs,
    cache: FingerprintCache,
    sender,
    debounce_seconds: float,
) -> Watcher:
    """파이프라인을 배선한 Watcher를 만든다."""
    worker = Worker(cache, sender)

    def on_fire(path: str, pending: Pending) -> None:
        worker.submit(Task(path=path, event_type=pending.event_type,
                           moved_from=pending.moved_from))

    debouncer = Debouncer(debounce_seconds, on_fire)
    handler = _Handler(debouncer, ignore_globs)
    observer = Observer()
    for root in watch_paths:
        observer.schedule(handler, str(root), recursive=True)
    return Watcher(observer, worker, debouncer)
