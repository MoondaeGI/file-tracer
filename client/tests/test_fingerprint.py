"""지문 계산 테스트 — 서버와 동일 값, raw bytes."""

import hashlib
import sys
from pathlib import Path

import ppdeep

from common.fingerprint import compute_fuzzy, compute_sha256, fingerprint_file

# 서버 fingerprint 모듈을 직접 import해 동일성 비교
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app import fingerprint as server_fp  # noqa: E402


def test_sha256_matches_hashlib() -> None:
    data = b"hello world"
    assert compute_sha256(data) == hashlib.sha256(data).hexdigest()


def test_fuzzy_none_for_empty() -> None:
    assert compute_fuzzy(b"") is None


def test_matches_server_fingerprint() -> None:
    data = ("Confidential note. " * 50).encode()
    assert compute_sha256(data) == server_fp.compute_sha256(data)
    assert compute_fuzzy(data) == server_fp.compute_fuzzy(data)


def test_fingerprint_file_reads_raw_bytes(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    content = bytes(range(256)) * 10
    f.write_bytes(content)
    fp = fingerprint_file(f)
    assert fp.sha256 == hashlib.sha256(content).hexdigest()
    assert fp.size == len(content)
    assert fp.fuzzy_hash == ppdeep.hash(content)
