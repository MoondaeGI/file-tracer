"""파일 지문(SHA-256 + ssdeep). 서버 server/app/fingerprint.py와 동일 로직(raw bytes)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import ppdeep


@dataclass(frozen=True)
class CachedFingerprint:
    """캐시·전송에 쓰는 파일 지문."""

    sha256: str
    fuzzy_hash: str | None
    size: int


def compute_sha256(data: bytes) -> str:
    """바이트의 SHA-256 16진 해시."""
    return hashlib.sha256(data).hexdigest()


def compute_fuzzy(data: bytes) -> str | None:
    """바이트의 ssdeep fuzzy 지문. 빈 입력이면 None."""
    if not data:
        return None
    return ppdeep.hash(data)


def fingerprint_file(path: Path) -> CachedFingerprint:
    """파일을 raw bytes로 읽어 지문을 계산한다."""
    data = path.read_bytes()
    return CachedFingerprint(
        sha256=compute_sha256(data),
        fuzzy_hash=compute_fuzzy(data),
        size=len(data),
    )
