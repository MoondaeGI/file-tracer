"""단일 워커 처리 로직 테스트(존재→해싱·전송, 부재→캐시 deleted)."""

from pathlib import Path

from agent.cache import FingerprintCache
from agent.models import CachedFingerprint, Task
from agent.worker import Worker


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def _worker(tmp_path: Path) -> tuple[Worker, FakeSender, FingerprintCache]:
    cache = FingerprintCache(tmp_path / "c.db")
    sender = FakeSender()
    return Worker(cache, sender), sender, cache


def test_existing_file_hashes_caches_and_sends(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    f = tmp_path / "secret.txt"
    f.write_bytes(b"hello world data here")
    worker.process(Task(path=str(f), event_type="created"))
    assert sender.calls[-1]["event_type"] == "created"
    assert sender.calls[-1]["sha256"]
    assert cache.get(str(f)) is not None  # 캐시 갱신됨


def test_deleted_uses_cached_fingerprint(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    path = str(tmp_path / "gone.txt")
    cache.put(path, CachedFingerprint(sha256="a" * 64, fuzzy_hash="3:x", size=9))
    worker.process(Task(path=path, event_type="deleted"))  # 파일 실제로 없음
    assert sender.calls[-1]["event_type"] == "deleted"
    assert sender.calls[-1]["sha256"] == "a" * 64
    assert cache.get(path) is None  # 캐시에서 제거됨


def test_deleted_without_cache_skips(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    worker.process(Task(path=str(tmp_path / "never.txt"), event_type="deleted"))
    assert sender.calls == []


def test_new_file_labeled_created_even_if_task_says_modified(tmp_path: Path) -> None:
    # watchdog가 created+modified를 쏴 task가 modified여도, 캐시에 없으면 진짜 created다.
    worker, sender, cache = _worker(tmp_path)
    f = tmp_path / "fresh.txt"
    f.write_bytes(b"brand new content here")
    worker.process(Task(path=str(f), event_type="modified"))
    assert sender.calls[-1]["event_type"] == "created"


def test_known_file_labeled_modified(tmp_path: Path) -> None:
    # 이미 캐시에 있던(=이전에 본) 파일이 다시 잡히면 modified다.
    worker, sender, cache = _worker(tmp_path)
    f = tmp_path / "known.txt"
    f.write_bytes(b"original content here")
    cache.put(str(f), CachedFingerprint(sha256="a" * 64, fuzzy_hash="3:x", size=5))
    worker.process(Task(path=str(f), event_type="created"))
    assert sender.calls[-1]["event_type"] == "modified"


def test_moved_pops_source_and_processes_dest(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    src = str(tmp_path / "old.txt")
    cache.put(src, CachedFingerprint(sha256="b" * 64, fuzzy_hash=None, size=3))
    dst = tmp_path / "new.txt"
    dst.write_bytes(b"moved content here")
    worker.process(Task(path=str(dst), event_type="moved", moved_from=src))
    assert cache.get(src) is None             # src 캐시 제거
    assert cache.get(str(dst)) is not None     # dst 캐시 채움
    assert sender.calls[-1]["event_type"] == "moved"
