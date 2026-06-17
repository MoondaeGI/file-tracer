"""Chrome 커넥터 요청(dict) → TraceEvent 변환(순수 함수, IO 없음).

시스템 경계 검증: 브라우저 event는 목적지 url이 반드시 있어야 하며, 없으면 빠르게
실패해 불완전 이벤트가 서버로 가지 않게 한다.
"""

from urllib.parse import urlparse

from common.events import (
    EVENT_DOWNLOAD,
    EVENT_PASTE,
    EVENT_UPLOAD,
    TraceEvent,
)
from common.fingerprint import CachedFingerprint
from connector.errors import MappingError

_CONNECTOR_TO_EVENT = {
    "FILE_ATTACHED": EVENT_UPLOAD,
    "FILE_DOWNLOADED": EVENT_DOWNLOAD,
    "BULK_DATA_ENTRY": EVENT_PASTE,
}


def to_trace_event(req: dict, fp: CachedFingerprint, host: str) -> TraceEvent:
    """커넥터 요청을 정규화된 TraceEvent로 변환한다.

    Raises:
        MappingError: 미지원 connector 종류이거나 url이 없을 때.
    """
    connector = req.get("connector")
    event_type = _CONNECTOR_TO_EVENT.get(connector)
    if event_type is None:
        raise MappingError(f"미지원 connector 종류: {connector}")

    url = req.get("url")
    if not url:
        raise MappingError(f"브라우저 이벤트에 url이 필요합니다: {connector}")

    name = req.get("filename") or "(pasted text)"
    metadata = {
        "url": url,
        "dst_host": urlparse(url).hostname,
        "tab_title": req.get("tab_title"),
    }
    return TraceEvent(
        sha256=fp.sha256, fuzzy_hash=fp.fuzzy_hash, size=fp.size,
        name=name, event_type=event_type, host=host,
        user=req.get("email"), source_hint=None, metadata=metadata,
    )
