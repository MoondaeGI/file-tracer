"""통합: 실제 watchdog watcher가 파일 이벤트를 올바른 Task로 전달하는지.

디바운스를 0.1초로 두고, FakeSender 호출을 폴링으로 기다려 flaky를 방지한다.
"""

import time
from pathlib import Path

from agent.cache import FingerprintCache
from agent.watcher import build_watcher


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


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
    sender = FakeSender()
    watcher = build_watcher(
        watch_paths=(watch,), ignore_globs=("*.tmp",),
        cache=cache, sender=sender, debounce_seconds=0.1,
    )
    watcher.start()
    try:
        f = watch / "secret.txt"
        f.write_bytes(b"confidential bytes here for test")
        assert _wait_for(lambda: any(c["event_type"] in ("created", "modified")
                                     for c in sender.calls))
        f.unlink()
        assert _wait_for(lambda: any(c["event_type"] == "deleted" for c in sender.calls))
    finally:
        watcher.stop()
