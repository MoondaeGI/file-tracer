"""유스케이스: 이벤트 기록 + 자동 매칭(mode b).

이벤트를 해시체인에 기록하고, 브라우저 채널이면 web detail을 저장한 뒤,
baseline 목록과 자동 매칭해 trace_match에 남긴다.
요청 파싱·응답 직렬화는 컨트롤러(api) 책임이고, 여기선 도메인 입력만 다룬다.
"""

from app.constants import WEB_EVENT_TYPES
from app.domain.matching import find_matches
from app.models import Event, EventInput, MatchResult
from app.repository import SqliteRepository


def record_event(
    repo: SqliteRepository, ev_input: EventInput, now: str
) -> tuple[Event, list[MatchResult]]:
    """이벤트 기록 + web detail 저장 + 자동 매칭 + trace 저장.

    Args:
        repo: 저장소.
        ev_input: 영속화 전 이벤트 입력.
        now: 서버 시각(ISO). 주입.

    Returns:
        (기록된 Event, 매칭 목록). 매칭이 없으면 빈 리스트.
    """
    event = repo.add_event(ev_input, now)
    meta = ev_input.metadata or {}
    if event.event_type in WEB_EVENT_TYPES:
        url = meta.get("url")
        if url:
            repo.add_web_event_detail(event.id, url, meta.get("dst_host"), meta.get("tab_title"))
    matches = find_matches(event.sha256, event.fuzzy_hash, repo.list_supervise_files())
    repo.add_trace_matches(event.id, matches, now)
    return event, matches
