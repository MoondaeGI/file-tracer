"""통합: 실제 watchdog watcher가 파일 이벤트를 올바른 Task로 전달하는지.

디바운스를 0.1초로 두고, FakeCore 호출을 폴링으로 기다려 flaky를 방지한다.
"""

import time
from pathlib import Path

from agent.cache import FingerprintCache
from agent.watcher import build_watcher
from common.events import TraceEvent


class FakeCore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def submit(self, event: TraceEvent) -> None:
        self.events.append(event)


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_created_then_deleted_flow(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cache = FingerprintCache(tmp_path / "c.db")
    core = FakeCore()
    watcher = build_watcher(
        watch_paths=(watch,), ignore_globs=("*.tmp",),
        cache=cache, core=core, debounce_seconds=0.1,
    )
    watcher.start()
    try:
        f = watch / "secret.txt"
        f.write_bytes(b"confidential bytes here for test")
        assert _wait_for(lambda: any(e.event_type in ("created", "modified")
                                     for e in core.events))
        f.unlink()
        assert _wait_for(lambda: any(e.event_type == "deleted" for e in core.events))
    finally:
        watcher.stop()
