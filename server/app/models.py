"""file-tracer 서버 도메인 모델. 모두 불변(frozen) dataclass."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fingerprint:
    """파일 지문(영속화 전 계산 결과)."""

    sha256: str
    fuzzy_hash: str | None
    size: int


@dataclass(frozen=True)
class SuperviseFile:
    """추적 대상 baseline(위험파일)."""

    id: int
    name: str
    sha256: str
    fuzzy_hash: str | None
    size: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class UpdateHistory:
    """baseline 갱신 시 보관하는 옛 버전 스냅샷."""

    id: int
    supervise_file_id: int
    sha256: str
    fuzzy_hash: str | None
    size: int
    replaced_at: str


@dataclass(frozen=True)
class EventInput:
    """클라가 모드 b로 보낸 이벤트 입력(영속화 전)."""

    sha256: str
    fuzzy_hash: str | None
    size: int
    name: str
    event_type: str
    host: str | None
    user: str | None
    source_hint: str | None


@dataclass(frozen=True)
class Event:
    """저장된 감시 이벤트(append-only + 해시체인)."""

    id: int
    sha256: str
    fuzzy_hash: str | None
    size: int
    name: str
    host: str | None
    user: str | None
    event_type: str
    detected_at: str
    source_hint: str | None
    prev_hash: str | None
    record_hash: str


@dataclass(frozen=True)
class TraceMatch:
    """event ↔ supervise_file 매칭 결과."""

    id: int
    event_id: int
    supervise_file_id: int
    match_type: str
    similarity: int
    matched_at: str


@dataclass(frozen=True)
class MatchResult:
    """matching이 돌려주는 매칭 1건(저장 전)."""

    supervise_file_id: int
    name: str
    match_type: str
    similarity: int
