"""파일 지문(SHA-256 + ssdeep). 서버 server/app/fingerprint.py와 동일 로직.

지문 동일성 계약(설계 §5): 반드시 raw bytes(바이너리)에서 계산한다. 텍스트 모드·
줄바꿈 변환이 끼면 서버 baseline과 매칭되지 않는다.
"""

import hashlib
from pathlib import Path

import ppdeep

from agent.models import CachedFingerprint


def compute_sha256(data: bytes) -> str:
    """바이트의 SHA-256 16진 해시."""
    return hashlib.sha256(data).hexdigest()


def compute_fuzzy(data: bytes) -> str | None:
    """바이트의 ssdeep fuzzy 지문. 빈 입력이면 None."""
    if not data:
        return None
    return ppdeep.hash(data)


def fingerprint_file(path: Path) -> CachedFingerprint:
    """파일을 raw bytes로 읽어 지문을 계산한다.

    Args:
        path: 대상 파일 경로.

    Returns:
        sha256·fuzzy_hash·size를 담은 CachedFingerprint.

    Raises:
        OSError: 파일 열기·읽기 실패(잠김 등) 시.
    """
    data = path.read_bytes()
    return CachedFingerprint(
        sha256=compute_sha256(data),
        fuzzy_hash=compute_fuzzy(data),
        size=len(data),
    )
