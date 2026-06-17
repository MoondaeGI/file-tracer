"""SqliteRepository — 4개 테이블 단일 SQLite 저장소.

쓰기는 락으로 직렬화(서버가 멀티스레드여도 event 해시체인 경합 방지).
db_path에 ":memory:"를 주면 인메모리(테스트용).
"""

import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from app.chain import compute_record_hash, event_payload
from app.models import (
    Event,
    EventInput,
    Fingerprint,
    MatchResult,
    SuperviseFile,
    TraceMatch,
    UpdateHistory,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS supervise_file (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, sha256 TEXT NOT NULL, fuzzy_hash TEXT,
  size INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS update_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supervise_file_id INTEGER NOT NULL REFERENCES supervise_file(id),
  sha256 TEXT NOT NULL, fuzzy_hash TEXT, size INTEGER NOT NULL, replaced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT NOT NULL, fuzzy_hash TEXT, size INTEGER NOT NULL, name TEXT NOT NULL,
  host TEXT, user TEXT, event_type TEXT NOT NULL, detected_at TEXT NOT NULL,
  source_hint TEXT, prev_hash TEXT, record_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_match (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES event(id),
  supervise_file_id INTEGER NOT NULL REFERENCES supervise_file(id),
  match_type TEXT NOT NULL, similarity INTEGER NOT NULL, matched_at TEXT NOT NULL
);
"""

_SF_COLS = ("id", "name", "sha256", "fuzzy_hash", "size", "created_at", "updated_at")


class SqliteRepository:
    """4개 테이블을 관리하는 SQLite 저장소."""

    def __init__(self, db_path: str | Path) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _sf_from_row(self, row: sqlite3.Row) -> SuperviseFile:
        return SuperviseFile(**{c: row[c] for c in _SF_COLS})

    def register_supervise_file(
        self, name: str, fp: Fingerprint, now: str
    ) -> tuple[SuperviseFile, bool]:
        """baseline 등록. 같은 name이 있으면 옛 버전을 update_history에 스냅샷 후 갱신.

        Returns:
            (등록/갱신된 SuperviseFile, was_update). 신규면 was_update=False.
        """
        with self._lock:
            cur = self._conn.execute("SELECT * FROM supervise_file WHERE name = ?", (name,))
            existing = cur.fetchone()
            if existing is None:
                cur = self._conn.execute(
                    "INSERT INTO supervise_file (name, sha256, fuzzy_hash, size, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (name, fp.sha256, fp.fuzzy_hash, fp.size, now, now),
                )
                self._conn.commit()
                new_id = cur.lastrowid
                return SuperviseFile(id=new_id, name=name, sha256=fp.sha256,
                                     fuzzy_hash=fp.fuzzy_hash, size=fp.size,
                                     created_at=now, updated_at=now), False
            # 기존 baseline 갱신: 옛 버전 스냅샷
            self._conn.execute(
                "INSERT INTO update_history (supervise_file_id, sha256, fuzzy_hash, size, replaced_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (existing["id"], existing["sha256"], existing["fuzzy_hash"], existing["size"], now),
            )
            self._conn.execute(
                "UPDATE supervise_file SET sha256 = ?, fuzzy_hash = ?, size = ?, updated_at = ? WHERE id = ?",
                (fp.sha256, fp.fuzzy_hash, fp.size, now, existing["id"]),
            )
            self._conn.commit()
            return SuperviseFile(id=existing["id"], name=name, sha256=fp.sha256,
                                 fuzzy_hash=fp.fuzzy_hash, size=fp.size,
                                 created_at=existing["created_at"], updated_at=now), True

    def get_supervise_file(self, supervise_file_id: int) -> SuperviseFile | None:
        """id로 baseline을 조회한다(없으면 None)."""
        cur = self._conn.execute("SELECT * FROM supervise_file WHERE id = ?", (supervise_file_id,))
        row = cur.fetchone()
        return self._sf_from_row(row) if row else None

    def list_supervise_files(self) -> tuple[SuperviseFile, ...]:
        """모든 baseline을 id 오름차순으로 반환한다."""
        cur = self._conn.execute("SELECT * FROM supervise_file ORDER BY id ASC")
        return tuple(self._sf_from_row(r) for r in cur.fetchall())

    def count_update_history(self, supervise_file_id: int) -> int:
        """baseline의 update_history 건수."""
        cur = self._conn.execute(
            "SELECT COUNT(*) AS c FROM update_history WHERE supervise_file_id = ?",
            (supervise_file_id,),
        )
        return cur.fetchone()["c"]

    def list_update_history(self, supervise_file_id: int) -> tuple[UpdateHistory, ...]:
        """baseline의 옛 버전 스냅샷 목록(오래된 순)."""
        cur = self._conn.execute(
            "SELECT * FROM update_history WHERE supervise_file_id = ? ORDER BY id ASC",
            (supervise_file_id,),
        )
        return tuple(
            UpdateHistory(id=r["id"], supervise_file_id=r["supervise_file_id"],
                          sha256=r["sha256"], fuzzy_hash=r["fuzzy_hash"],
                          size=r["size"], replaced_at=r["replaced_at"])
            for r in cur.fetchall()
        )

    def add_event(self, ev: EventInput, now: str) -> Event:
        """이벤트를 추가한다(detected_at=서버 now, 해시체인 이어붙임)."""
        with self._lock:
            cur = self._conn.execute("SELECT record_hash FROM event ORDER BY id DESC LIMIT 1")
            last = cur.fetchone()
            prev_hash = last["record_hash"] if last else None
            draft = Event(id=0, sha256=ev.sha256, fuzzy_hash=ev.fuzzy_hash, size=ev.size,
                          name=ev.name, host=ev.host, user=ev.user, event_type=ev.event_type,
                          detected_at=now, source_hint=ev.source_hint,
                          prev_hash=prev_hash, record_hash="")
            record_hash = compute_record_hash(event_payload(draft), prev_hash)
            cur = self._conn.execute(
                "INSERT INTO event (sha256, fuzzy_hash, size, name, host, user, event_type, "
                "detected_at, source_hint, prev_hash, record_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ev.sha256, ev.fuzzy_hash, ev.size, ev.name, ev.host, ev.user,
                 ev.event_type, now, ev.source_hint, prev_hash, record_hash),
            )
            self._conn.commit()
            return replace(draft, id=cur.lastrowid, record_hash=record_hash)

    def _event_from_row(self, row: sqlite3.Row) -> Event:
        return Event(id=row["id"], sha256=row["sha256"], fuzzy_hash=row["fuzzy_hash"],
                     size=row["size"], name=row["name"], host=row["host"], user=row["user"],
                     event_type=row["event_type"], detected_at=row["detected_at"],
                     source_hint=row["source_hint"], prev_hash=row["prev_hash"],
                     record_hash=row["record_hash"])

    def list_events(self, limit: int) -> tuple[Event, ...]:
        """최근 이벤트를 id 내림차순으로 최대 limit개 반환한다."""
        cur = self._conn.execute("SELECT * FROM event ORDER BY id DESC LIMIT ?", (limit,))
        return tuple(self._event_from_row(r) for r in cur.fetchall())

    def all_events(self) -> tuple[Event, ...]:
        """전체 이벤트를 id 오름차순으로 반환한다(체인 검증용)."""
        cur = self._conn.execute("SELECT * FROM event ORDER BY id ASC")
        return tuple(self._event_from_row(r) for r in cur.fetchall())

    def add_trace_matches(
        self, event_id: int, matches: Sequence[MatchResult], now: str
    ) -> list[TraceMatch]:
        """이벤트의 매칭 결과를 trace_match에 저장한다."""
        saved: list[TraceMatch] = []
        with self._lock:
            for m in matches:
                cur = self._conn.execute(
                    "INSERT INTO trace_match (event_id, supervise_file_id, match_type, similarity, matched_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event_id, m.supervise_file_id, m.match_type, m.similarity, now),
                )
                saved.append(TraceMatch(id=cur.lastrowid, event_id=event_id,
                                        supervise_file_id=m.supervise_file_id,
                                        match_type=m.match_type, similarity=m.similarity,
                                        matched_at=now))
            self._conn.commit()
        return saved

    def best_trace_match(self, event_id: int) -> TraceMatch | None:
        """이벤트의 최고 유사도 매칭 1건(없으면 None)."""
        cur = self._conn.execute(
            "SELECT * FROM trace_match WHERE event_id = ? ORDER BY similarity DESC, id ASC LIMIT 1",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return TraceMatch(id=row["id"], event_id=row["event_id"],
                          supervise_file_id=row["supervise_file_id"],
                          match_type=row["match_type"], similarity=row["similarity"],
                          matched_at=row["matched_at"])

    def events_matching_supervise_file(
        self, supervise_file_id: int
    ) -> list[tuple[Event, TraceMatch]]:
        """이 baseline과 매칭된 이벤트들을 (Event, TraceMatch) 쌍으로 반환한다.

        해당 supervise_file을 가리키는 trace_match를 event와 JOIN한다. 최신순(event id 내림차순).

        Args:
            supervise_file_id: 조회할 baseline의 id.

        Returns:
            (Event, TraceMatch) 튜플 리스트. 매칭이 없으면 빈 리스트.
        """
        cur = self._conn.execute(
            "SELECT e.*, "
            "tm.id AS tm_id, tm.event_id AS tm_event_id, tm.supervise_file_id AS tm_sf_id, "
            "tm.match_type AS tm_match_type, tm.similarity AS tm_similarity, tm.matched_at AS tm_matched_at "
            "FROM trace_match tm JOIN event e ON e.id = tm.event_id "
            "WHERE tm.supervise_file_id = ? ORDER BY e.id DESC",
            (supervise_file_id,),
        )
        result: list[tuple[Event, TraceMatch]] = []
        for row in cur.fetchall():
            event = self._event_from_row(row)
            match = TraceMatch(id=row["tm_id"], event_id=row["tm_event_id"],
                               supervise_file_id=row["tm_sf_id"], match_type=row["tm_match_type"],
                               similarity=row["tm_similarity"], matched_at=row["tm_matched_at"])
            result.append((event, match))
        return result
