"""services.events 유스케이스 테스트(:memory:)."""

from app.models import EventInput, Fingerprint
from app.repository import SqliteRepository
from app.services import events

NOW = "2026-06-17T00:00:00+00:00"


def _ev(sha: str, **over) -> EventInput:
    base = dict(
        sha256=sha, fuzzy_hash=None, size=10, name="x.txt",
        event_type="created", host=None, user=None, source_hint=None,
    )
    base.update(over)
    return EventInput(**base)


def test_record_event_persists_event() -> None:
    repo = SqliteRepository(":memory:")
    event, matches = events.record_event(repo, _ev("a" * 64), NOW)
    assert event.id == 1
    assert event.detected_at == NOW
    assert matches == []               # baseline 없으니 매칭 없음
    assert repo.list_events(limit=10)[0].id == event.id


def test_record_event_auto_matches_baseline() -> None:
    repo = SqliteRepository(":memory:")
    sf, _ = repo.register_supervise_file("secret.dwg", Fingerprint("a" * 64, None, 10), NOW)
    event, matches = events.record_event(repo, _ev("a" * 64), NOW)
    assert len(matches) == 1           # SHA 동일 → exact 매칭
    assert matches[0].supervise_file_id == sf.id
    assert repo.best_trace_match(event.id).supervise_file_id == sf.id


def test_record_event_stores_web_detail_for_browser_event() -> None:
    repo = SqliteRepository(":memory:")
    event, _ = events.record_event(
        repo,
        _ev("b" * 64, event_type="upload",
            metadata={"url": "https://x.test/u", "dst_host": "x.test"}),
        NOW,
    )
    detail = repo.get_web_event_detail(event.id)
    assert detail is not None
    assert detail["url"] == "https://x.test/u"
    assert detail["dst_host"] == "x.test"


def test_record_event_no_web_detail_for_fs_event() -> None:
    repo = SqliteRepository(":memory:")
    event, _ = events.record_event(repo, _ev("c" * 64, metadata={"url": "ignored"}), NOW)
    # event_type=created 는 브라우저 채널이 아니므로 detail 미저장
    assert repo.get_web_event_detail(event.id) is None
