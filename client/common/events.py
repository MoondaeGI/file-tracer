"""채널 무관 이벤트 계약(TraceEvent)과 event_type 상수. 모든 수집기가 이걸 emit한다."""

from dataclasses import dataclass

EVENT_CREATED = "created"
EVENT_MODIFIED = "modified"
EVENT_MOVED = "moved"
EVENT_DELETED = "deleted"
EVENT_UPLOAD = "upload"
EVENT_DOWNLOAD = "download"
EVENT_PASTE = "paste"

# 브라우저 채널(목적지 url 필수)
WEB_EVENT_TYPES = (EVENT_UPLOAD, EVENT_DOWNLOAD, EVENT_PASTE)


@dataclass(frozen=True)
class TraceEvent:
    """수집기 → 코어로 흐르는 정규화 이벤트."""

    sha256: str
    fuzzy_hash: str | None
    size: int
    name: str
    event_type: str
    host: str
    user: str | None
    source_hint: str | None
    metadata: dict | None
