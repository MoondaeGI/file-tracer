"""클라이언트 도메인 모델과 이벤트 타입 상수. 모두 불변(frozen)."""

from dataclasses import dataclass
from pathlib import Path

EVENT_CREATED = "created"
EVENT_MODIFIED = "modified"
EVENT_MOVED = "moved"
EVENT_DELETED = "deleted"


@dataclass(frozen=True)
class Config:
    """검증된 에이전트 설정."""

    server_url: str
    debounce_seconds: float
    watch_paths: tuple[Path, ...]
    ignore_globs: tuple[str, ...]


@dataclass(frozen=True)
class CachedFingerprint:
    """캐시에 저장하는 파일 지문(삭제·이동 시 재사용)."""

    sha256: str
    fuzzy_hash: str | None
    size: int


@dataclass(frozen=True)
class Pending:
    """디바운스 대기 중인 경로의 최신 이벤트 정보."""

    event_type: str
    moved_from: str | None = None


@dataclass(frozen=True)
class Task:
    """워커 큐에 들어가는 처리 단위."""

    path: str
    event_type: str
    moved_from: str | None = None
