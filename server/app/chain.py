"""event 테이블 append-only 해시체인. 우발적 단일 수정·링크 단절을 탐지한다.

보장 한계: record_hash는 공개 SHA-256(무서명)이라 DB 쓰기 권한자의 의도적 전체
재작성은 막지 못한다. 우발적 단일 수정만 탐지한다.
"""

import hashlib
import json
from collections.abc import Sequence

from app.models import Event

# 체인이 보호하는 event 내용 필드(순서 고정).
_PAYLOAD_FIELDS = (
    "sha256", "fuzzy_hash", "size", "name", "host", "user",
    "event_type", "detected_at", "source_hint",
)


def event_payload(event: Event) -> dict:
    """체인이 보호할 event 필드만 추린 dict(id·prev_hash·record_hash 제외)."""
    return {field: getattr(event, field) for field in _PAYLOAD_FIELDS}


def compute_record_hash(payload: dict, prev_hash: str | None) -> str:
    """payload와 직전 record_hash를 묶어 record_hash를 계산한다."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    material = f"{prev_hash or ''}\n{canonical}".encode()
    return hashlib.sha256(material).hexdigest()


def verify_chain(events: Sequence[Event]) -> int | None:
    """event 체인을 검증한다. 깨진 첫 event의 id, 정상이면 None."""
    prev_hash: str | None = None
    for event in events:
        if event.prev_hash != prev_hash:
            return event.id
        expected = compute_record_hash(event_payload(event), event.prev_hash)
        if expected != event.record_hash:
            return event.id
        prev_hash = event.record_hash
    return None
