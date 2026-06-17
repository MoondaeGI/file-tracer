"""services.registration 유스케이스 테스트(:memory:)."""

from app.repository import SqliteRepository
from app.services import registration

NOW = "2026-06-17T00:00:00+00:00"


def test_register_computes_fingerprint_from_bytes() -> None:
    repo = SqliteRepository(":memory:")
    sf, was_update = registration.register(repo, "design.dwg", b"hello world", NOW)
    assert was_update is False
    assert sf.name == "design.dwg"
    assert len(sf.sha256) == 64          # 바이트에서 SHA-256 계산됨
    assert sf.size == len(b"hello world")
    # 실제로 저장됐는지 확인
    assert repo.get_supervise_file(sf.id).sha256 == sf.sha256


def test_register_same_name_updates_baseline() -> None:
    repo = SqliteRepository(":memory:")
    sf1, _ = registration.register(repo, "design.dwg", b"v1", NOW)
    sf2, was_update = registration.register(repo, "design.dwg", b"v2 content", NOW)
    assert was_update is True
    assert sf2.id == sf1.id
    assert sf2.sha256 != sf1.sha256
    assert repo.count_update_history(sf1.id) == 1


def test_register_empty_file_has_no_fuzzy() -> None:
    repo = SqliteRepository(":memory:")
    sf, _ = registration.register(repo, "empty.bin", b"", NOW)
    assert sf.fuzzy_hash is None       # 0바이트는 fuzzy 지문 없음
    assert sf.size == 0
