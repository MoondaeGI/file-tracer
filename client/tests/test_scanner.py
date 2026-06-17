"""초기 스캔 테스트 — 캐시만 채우고 전송하지 않는다."""

from pathlib import Path

from agent.cache import FingerprintCache
from agent.scanner import initial_scan


def test_scan_fills_cache_no_send(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    (watch / "a.txt").write_bytes(b"alpha content here")
    (watch / "b.tmp").write_bytes(b"temp ignored")
    sub = watch / "sub"
    sub.mkdir()
    (sub / "c.txt").write_bytes(b"charlie content here")

    cache = FingerprintCache(tmp_path / "c.db")
    count = initial_scan((watch,), ("*.tmp",), cache)

    assert count == 2  # a.txt, sub/c.txt (b.tmp 무시)
    assert cache.get(str(watch / "a.txt")) is not None
    assert cache.get(str(sub / "c.txt")) is not None
    assert cache.get(str(watch / "b.tmp")) is None
