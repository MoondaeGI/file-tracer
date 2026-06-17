"""SQLite 지문 캐시 테스트(get/put/pop)."""

from pathlib import Path

from agent.cache import FingerprintCache
from agent.models import CachedFingerprint


def _fp(tag: str) -> CachedFingerprint:
    return CachedFingerprint(sha256=tag * 64, fuzzy_hash="3:" + tag, size=10)


def test_put_then_get(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    cache.put("C:\\a.txt", _fp("a"))
    got = cache.get("C:\\a.txt")
    assert got == _fp("a")


def test_get_missing_returns_none(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    assert cache.get("C:\\nope.txt") is None


def test_pop_returns_and_removes(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    cache.put("C:\\a.txt", _fp("a"))
    assert cache.pop("C:\\a.txt") == _fp("a")
    assert cache.get("C:\\a.txt") is None


def test_pop_missing_returns_none(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    assert cache.pop("C:\\nope.txt") is None


def test_put_overwrites(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    cache.put("C:\\a.txt", _fp("a"))
    cache.put("C:\\a.txt", _fp("b"))
    assert cache.get("C:\\a.txt") == _fp("b")
