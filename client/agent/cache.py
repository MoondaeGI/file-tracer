"""파일 경로 → 마지막 지문 SQLite 캐시. 삭제·이동 시 지문 재사용.

스레드 안전(설계 §6): 서버 repository와 같은 check_same_thread=False + 락 패턴.
상태 파일이므로 감시 폴더 밖에 둔다(자기 이벤트 루프 방지).
"""

import sqlite3
import threading
from pathlib import Path

from agent.models import CachedFingerprint


class FingerprintCache:
    """경로 → CachedFingerprint 매핑을 SQLite에 저장한다."""

    def __init__(self, db_path: Path) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(Path(db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                path TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                fuzzy_hash TEXT,
                size INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def put(self, path: str, fp: CachedFingerprint) -> None:
        """경로의 지문을 저장(이미 있으면 덮어씀)한다."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (path, sha256, fuzzy_hash, size) "
                "VALUES (?, ?, ?, ?)",
                (path, fp.sha256, fp.fuzzy_hash, fp.size),
            )
            self._conn.commit()

    def get(self, path: str) -> CachedFingerprint | None:
        """경로의 지문을 반환(없으면 None)한다."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT sha256, fuzzy_hash, size FROM cache WHERE path = ?", (path,)
            )
            row = cur.fetchone()
        if row is None:
            return None
        return CachedFingerprint(sha256=row[0], fuzzy_hash=row[1], size=row[2])

    def pop(self, path: str) -> CachedFingerprint | None:
        """경로의 지문을 반환하고 삭제한다(없으면 None)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT sha256, fuzzy_hash, size FROM cache WHERE path = ?", (path,)
            )
            row = cur.fetchone()
            if row is not None:
                self._conn.execute("DELETE FROM cache WHERE path = ?", (path,))
                self._conn.commit()
        if row is None:
            return None
        return CachedFingerprint(sha256=row[0], fuzzy_hash=row[1], size=row[2])
