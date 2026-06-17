"""SqliteRepository — supervise_file·update_history 테스트(:memory:)."""

from app.models import Fingerprint
from app.repository import SqliteRepository

NOW = "2026-06-10T00:00:00+00:00"


def _fp(tag: str) -> Fingerprint:
    return Fingerprint(sha256=tag * 64, fuzzy_hash="3:" + tag, size=10)


def test_register_new_supervise_file() -> None:
    repo = SqliteRepository(":memory:")
    sf, was_update = repo.register_supervise_file("design.dwg", _fp("a"), NOW)
    assert sf.id == 1
    assert sf.name == "design.dwg"
    assert sf.sha256 == "a" * 64
    assert was_update is False
    assert repo.count_update_history(sf.id) == 0


def test_reupload_same_name_snapshots_old() -> None:
    repo = SqliteRepository(":memory:")
    sf1, _ = repo.register_supervise_file("design.dwg", _fp("a"), NOW)
    sf2, was_update = repo.register_supervise_file("design.dwg", _fp("b"), "2026-06-10T01:00:00+00:00")
    assert was_update is True
    assert sf2.id == sf1.id                 # 같은 baseline, id 유지
    assert sf2.sha256 == "b" * 64           # 새 지문으로 갱신
    history = repo.list_update_history(sf1.id)
    assert len(history) == 1
    assert history[0].sha256 == "a" * 64    # 옛 지문 스냅샷
    assert repo.count_update_history(sf1.id) == 1


def test_different_name_is_new_baseline() -> None:
    repo = SqliteRepository(":memory:")
    repo.register_supervise_file("a.txt", _fp("a"), NOW)
    sf2, was_update = repo.register_supervise_file("b.txt", _fp("b"), NOW)
    assert was_update is False
    assert sf2.id == 2
    assert len(repo.list_supervise_files()) == 2


def test_get_supervise_file() -> None:
    repo = SqliteRepository(":memory:")
    sf, _ = repo.register_supervise_file("a.txt", _fp("a"), NOW)
    assert repo.get_supervise_file(sf.id).name == "a.txt"
    assert repo.get_supervise_file(999) is None


from app.chain import verify_chain
from app.models import EventInput, MatchResult


def _ev(sha: str, etype: str = "created") -> EventInput:
    return EventInput(sha256=sha * 64, fuzzy_hash="3:" + sha, size=5, name="f.txt",
                      event_type=etype, host="PC", user="u", source_hint=None)


def test_add_event_builds_chain() -> None:
    repo = SqliteRepository(":memory:")
    e1 = repo.add_event(_ev("a"), NOW)
    e2 = repo.add_event(_ev("b"), NOW)
    assert e1.id == 1 and e1.prev_hash is None
    assert e2.prev_hash == e1.record_hash
    assert verify_chain(repo.all_events()) is None


def test_list_events_recent() -> None:
    repo = SqliteRepository(":memory:")
    for i in range(5):
        repo.add_event(_ev(f"{i}"), NOW)
    assert len(repo.list_events(limit=3)) == 3


def test_add_trace_matches_and_best() -> None:
    repo = SqliteRepository(":memory:")
    ev = repo.add_event(_ev("a"), NOW)
    matches = [MatchResult(supervise_file_id=7, name="x", match_type="fuzzy", similarity=80),
               MatchResult(supervise_file_id=8, name="y", match_type="exact", similarity=100)]
    saved = repo.add_trace_matches(ev.id, matches, NOW)
    assert len(saved) == 2
    best = repo.best_trace_match(ev.id)
    assert best.similarity == 100
    assert best.supervise_file_id == 8


def test_best_trace_match_none_when_empty() -> None:
    repo = SqliteRepository(":memory:")
    ev = repo.add_event(_ev("a"), NOW)
    assert repo.best_trace_match(ev.id) is None


def test_events_matching_supervise_file() -> None:
    repo = SqliteRepository(":memory:")
    sf, _ = repo.register_supervise_file("d.txt", _fp("a"), NOW)
    # sf와 매칭되는 이벤트
    ev = repo.add_event(_ev("a"), NOW)
    repo.add_trace_matches(
        ev.id,
        [MatchResult(supervise_file_id=sf.id, name=sf.name, match_type="exact", similarity=100)],
        NOW,
    )
    # sf와 매칭되지 않는 이벤트
    other = repo.add_event(_ev("z"), NOW)
    repo.add_trace_matches(
        other.id,
        [MatchResult(supervise_file_id=999, name="other", match_type="fuzzy", similarity=70)],
        NOW,
    )

    result = repo.events_matching_supervise_file(sf.id)
    assert len(result) == 1
    event, match = result[0]
    assert event.id == ev.id
    assert match.match_type == "exact"
    assert match.similarity == 100


def test_events_matching_supervise_file_empty() -> None:
    repo = SqliteRepository(":memory:")
    sf, _ = repo.register_supervise_file("d.txt", _fp("a"), NOW)
    assert repo.events_matching_supervise_file(sf.id) == []


def test_add_event_persists_metadata() -> None:
    from app.repository import SqliteRepository
    from app.models import EventInput
    repo = SqliteRepository(":memory:")
    ei = EventInput(sha256="a" * 64, fuzzy_hash=None, size=1, name="n",
                    event_type="upload", host="h", user="u", source_hint=None,
                    metadata={"url": "https://x"})
    ev = repo.add_event(ei, "2026-06-17T00:00:00+00:00")
    assert ev.metadata == {"url": "https://x"}
    assert repo.all_events()[0].metadata == {"url": "https://x"}


def test_web_event_detail_roundtrip() -> None:
    from app.repository import SqliteRepository
    repo = SqliteRepository(":memory:")
    repo.add_web_event_detail(1, "https://drive.google.com/x", "drive.google.com", "Drive")
    got = repo.get_web_event_detail(1)
    assert got == {"url": "https://drive.google.com/x",
                   "dst_host": "drive.google.com", "tab_title": "Drive"}
    assert repo.get_web_event_detail(999) is None
