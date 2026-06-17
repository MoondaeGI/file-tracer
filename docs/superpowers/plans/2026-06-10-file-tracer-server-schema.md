# file-tracer 서버 스키마 정식화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로토타입의 단일 `records` 테이블을 `supervise_file`·`update_history`·`event`·`trace_match` 4개 정규화 테이블로 교체하고, 매칭 결과(trace_match)·baseline 버전 이력(update_history)을 자동 기록하도록 서버 로직을 재작성한다.

**Architecture:** SQLite 단일 `SqliteRepository`(테스트는 `:memory:`)가 4개 테이블을 관리한다. 모드 a(파일 업로드)는 baseline 등록·버전 스냅샷, 모드 b(클라 JSON)는 이벤트 기록(해시체인)+자동 매칭(trace_match). 클라 API 계약(`POST /api/fingerprints`)은 유지해 클라이언트는 변경하지 않는다.

**Tech Stack:** Python 3.12, FastAPI, sqlite3(표준), ppdeep, pytest, httpx(TestClient).

> **주의:** 기존 `server/app/` 코드를 재작성한다 — 각 Task는 "기존 모듈·테스트 폐기 → 새 것"이다. `python`은 PATH에 없으니 `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe`(PowerShell). 테스트는 `server` 디렉터리에서. 명령 실행 전 사용자 확인(설치는 없음 — 새 의존성 없음). 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. 현재 브랜치 `feat/client-prototype`.

**승인된 설계:** `docs/superpowers/specs/2026-06-10-file-tracer-server-schema-design.md`

---

## File Structure (server/app/)

| 파일 | 변경 | 책임 |
|---|---|---|
| `fingerprint.py` | **유지** | SHA-256·ppdeep, fuzzy_similarity (변경 없음) |
| `errors.py` | 유지 | HttpError·InvalidFingerprintRequestError |
| `constants.py` | 갱신 | match_type·fuzzy 임계치·event_type 상수·예약값 |
| `models.py` | **교체** | Fingerprint/SuperviseFile/UpdateHistory/EventInput/Event/TraceMatch/MatchResult |
| `matching.py` | **교체** | find_matches(sha, fuzzy, supervise_files) → MatchResult |
| `chain.py` | **교체** | event 대상 해시체인 |
| `repository.py` | **교체** | SqliteRepository 단일(4 테이블) |
| `api.py` | **교체** | 모드 a/b + GET 2개 |
| `main.py` | 갱신 | SqliteRepository 구성 |
| `static/index.html` | 갱신 | baseline·event 표 |

테스트: `test_models`·`test_matching`·`test_chain`·`test_repository`·`test_api`·`test_static` **교체**, `test_scenarios` 제거(새 통합 테스트로 대체), `test_fingerprint`·`test_smoke` 유지.

---

## 공통 타입 계약 (모든 Task가 따른다)

```python
# constants.py
MATCH_TYPE_EXACT = "exact"
MATCH_TYPE_FUZZY = "fuzzy"
FUZZY_MATCH_THRESHOLD = 50
EVENT_TYPES = ("created", "modified", "moved", "deleted")          # 로직 처리
RESERVED_EVENT_TYPES = ("copy", "upload", "download")              # 예약(로직 없음)

# models.py (frozen dataclass)
Fingerprint(sha256: str, fuzzy_hash: str | None, size: int)
SuperviseFile(id, name, sha256, fuzzy_hash, size, created_at, updated_at)
UpdateHistory(id, supervise_file_id, sha256, fuzzy_hash, size, replaced_at)
EventInput(sha256, fuzzy_hash, size, name, event_type, host, user, source_hint)
Event(id, sha256, fuzzy_hash, size, name, host, user, event_type, detected_at,
      source_hint, prev_hash, record_hash)
TraceMatch(id, event_id, supervise_file_id, match_type, similarity, matched_at)
MatchResult(supervise_file_id, name, match_type, similarity)       # matching 출력(미저장)

# matching.py
find_matches(sha256, fuzzy_hash, supervise_files: Sequence[SuperviseFile],
             threshold=FUZZY_MATCH_THRESHOLD) -> list[MatchResult]

# chain.py
event_payload(event: Event) -> dict
compute_record_hash(payload: dict, prev_hash: str | None) -> str
verify_chain(events: Sequence[Event]) -> int | None               # 깨진 event id

# repository.py — SqliteRepository(db_path: str | Path)
register_supervise_file(name: str, fp: Fingerprint, now: str) -> tuple[SuperviseFile, bool]
add_event(ev: EventInput, now: str) -> Event
add_trace_matches(event_id: int, matches: Sequence[MatchResult], now: str) -> list[TraceMatch]
list_supervise_files() -> tuple[SuperviseFile, ...]
count_update_history(supervise_file_id: int) -> int
list_update_history(supervise_file_id: int) -> tuple[UpdateHistory, ...]
list_events(limit: int) -> tuple[Event, ...]
all_events() -> tuple[Event, ...]
best_trace_match(event_id: int) -> TraceMatch | None
get_supervise_file(supervise_file_id: int) -> SuperviseFile | None

# api.py
build_app(repository: SqliteRepository) -> FastAPI
```

---

## Task 1: 상수·모델 교체 (constants.py, models.py)

**Files:**
- Modify: `server/app/constants.py`
- Replace: `server/app/models.py`
- Replace test: `server/tests/test_models.py`

- [ ] **Step 1: 실패 테스트 작성 (기존 test_models.py 전체 교체)**

`server/tests/test_models.py`:
```python
"""새 스키마 도메인 모델·상수 테스트."""

import dataclasses

import pytest

from app import constants
from app.models import (
    Event,
    EventInput,
    Fingerprint,
    MatchResult,
    SuperviseFile,
    TraceMatch,
    UpdateHistory,
)


def test_constants() -> None:
    assert constants.MATCH_TYPE_EXACT == "exact"
    assert constants.MATCH_TYPE_FUZZY == "fuzzy"
    assert constants.FUZZY_MATCH_THRESHOLD == 50
    assert constants.EVENT_TYPES == ("created", "modified", "moved", "deleted")
    assert constants.RESERVED_EVENT_TYPES == ("copy", "upload", "download")


def test_fingerprint() -> None:
    fp = Fingerprint(sha256="a" * 64, fuzzy_hash=None, size=0)
    assert fp.fuzzy_hash is None


def test_supervise_file_frozen() -> None:
    sf = SuperviseFile(id=1, name="s.txt", sha256="a" * 64, fuzzy_hash="3:x",
                       size=10, created_at="t", updated_at="t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        sf.name = "y"  # type: ignore[misc]


def test_other_models_construct() -> None:
    assert UpdateHistory(id=1, supervise_file_id=2, sha256="a" * 64,
                         fuzzy_hash=None, size=1, replaced_at="t").supervise_file_id == 2
    assert EventInput(sha256="a" * 64, fuzzy_hash=None, size=1, name="n",
                      event_type="created", host=None, user=None, source_hint=None).name == "n"
    assert Event(id=1, sha256="a" * 64, fuzzy_hash=None, size=1, name="n", host=None,
                 user=None, event_type="created", detected_at="t", source_hint=None,
                 prev_hash=None, record_hash="h").record_hash == "h"
    assert TraceMatch(id=1, event_id=2, supervise_file_id=3, match_type="exact",
                      similarity=100, matched_at="t").similarity == 100
    assert MatchResult(supervise_file_id=3, name="n", match_type="fuzzy",
                       similarity=87).similarity == 87
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_models.py -v` (server 디렉터리에서)
Expected: FAIL — `ImportError` (Event 등 없음)

- [ ] **Step 3: 구현 — constants.py 갱신, models.py 교체**

`server/app/constants.py` (전체 교체):
```python
"""매칭·이벤트 관련 상수."""

MATCH_TYPE_EXACT = "exact"
MATCH_TYPE_FUZZY = "fuzzy"

# ssdeep 유사도가 이 값 이상이면 fuzzy 매칭으로 포함한다.
FUZZY_MATCH_THRESHOLD = 50

# 클라이언트가 현재 생성하는 이벤트(로직 처리 대상).
EVENT_TYPES = ("created", "modified", "moved", "deleted")
# 향후 확장 예약(ETW·네트워크 필요, 현재 로직 없음).
RESERVED_EVENT_TYPES = ("copy", "upload", "download")
```

`server/app/models.py` (전체 교체):
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/constants.py server/app/models.py server/tests/test_models.py
git commit -m "feat: 새 스키마 도메인 모델·상수로 교체"
```

---

## Task 2: 매칭 교체 (matching.py)

**Files:**
- Replace: `server/app/matching.py`
- Replace test: `server/tests/test_matching.py`

- [ ] **Step 1: 실패 테스트 작성 (기존 교체)**

`server/tests/test_matching.py`:
```python
"""supervise_file 대상 매칭 테스트."""

from app.fingerprint import compute_fuzzy
from app.matching import find_matches
from app.models import SuperviseFile


def _sf(idx: int, sha: str, fuzzy: str | None) -> SuperviseFile:
    return SuperviseFile(id=idx, name=f"b{idx}.txt", sha256=sha, fuzzy_hash=fuzzy,
                         size=10, created_at="t", updated_at="t")


def test_exact_match() -> None:
    sha = "a" * 64
    matches = find_matches(sha, None, [_sf(1, sha, None)])
    assert len(matches) == 1
    assert matches[0].supervise_file_id == 1
    assert matches[0].match_type == "exact"
    assert matches[0].similarity == 100


def test_fuzzy_match_within_threshold() -> None:
    text = "Confidential design notes. " * 40
    fa = compute_fuzzy(text.encode())
    fb = compute_fuzzy((text + "a small edit.").encode())
    matches = find_matches("e" * 64, fb, [_sf(1, "f" * 64, fa)], threshold=50)
    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].similarity >= 50


def test_no_match_when_below_threshold() -> None:
    fa = compute_fuzzy(("alpha beta gamma. " * 40).encode())
    fb = compute_fuzzy(("zulu yankee xray. " * 40).encode())
    matches = find_matches("e" * 64, fb, [_sf(1, "f" * 64, fa)], threshold=101)
    assert matches == []


def test_null_fuzzy_skips() -> None:
    matches = find_matches("e" * 64, None, [_sf(1, "f" * 64, "3:x")])
    assert matches == []


def test_sorted_desc() -> None:
    sha = "a" * 64
    matches = find_matches(sha, None, [_sf(1, "z" * 64, None), _sf(2, sha, None)])
    assert [m.supervise_file_id for m in matches] == [2]
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_matching.py -v`
Expected: FAIL — `ImportError`/시그니처 불일치

- [ ] **Step 3: 구현 (전체 교체)**

`server/app/matching.py`:
```python
"""들어온 지문을 supervise_file(baseline) 목록과 비교해 매칭을 만든다.

SHA 동일은 exact(100). 아니면 양쪽 fuzzy_hash가 모두 있을 때 ssdeep 유사도(0~100)를
계산해 임계치 이상만 fuzzy로 포함한다.
"""

from collections.abc import Sequence

from app.constants import FUZZY_MATCH_THRESHOLD, MATCH_TYPE_EXACT, MATCH_TYPE_FUZZY
from app.fingerprint import fuzzy_similarity
from app.models import MatchResult, SuperviseFile


def find_matches(
    sha256: str,
    fuzzy_hash: str | None,
    supervise_files: Sequence[SuperviseFile],
    threshold: int = FUZZY_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """지문에 대한 매칭 목록을 유사도 내림차순으로 반환한다.

    Args:
        sha256: 들어온 SHA-256.
        fuzzy_hash: 들어온 ssdeep 지문(없으면 None).
        supervise_files: 비교 대상 baseline 목록.
        threshold: 이 이상 유사도만 fuzzy로 포함.

    Returns:
        MatchResult 리스트(similarity 내림차순, 동률은 supervise_file_id 오름차순).
    """
    matches: list[MatchResult] = []
    for sf in supervise_files:
        if sf.sha256 == sha256:
            matches.append(MatchResult(supervise_file_id=sf.id, name=sf.name,
                                       match_type=MATCH_TYPE_EXACT, similarity=100))
            continue
        if fuzzy_hash is None or sf.fuzzy_hash is None:
            continue
        similarity = fuzzy_similarity(fuzzy_hash, sf.fuzzy_hash)
        if similarity >= threshold:
            matches.append(MatchResult(supervise_file_id=sf.id, name=sf.name,
                                       match_type=MATCH_TYPE_FUZZY, similarity=similarity))
    matches.sort(key=lambda m: (-m.similarity, m.supervise_file_id))
    return matches
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_matching.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/matching.py server/tests/test_matching.py
git commit -m "feat: supervise_file 대상 매칭으로 교체"
```

---

## Task 3: 해시체인 교체 (chain.py)

**Files:**
- Replace: `server/app/chain.py`
- Replace test: `server/tests/test_chain.py`

- [ ] **Step 1: 실패 테스트 작성 (기존 교체)**

`server/tests/test_chain.py`:
```python
"""event 대상 해시체인 테스트."""

import dataclasses

from app.chain import compute_record_hash, event_payload, verify_chain
from app.models import Event


def _event(idx: int, prev_hash: str | None) -> Event:
    base = Event(id=idx, sha256=f"{idx:064x}", fuzzy_hash=None, size=1, name=f"f{idx}",
                 host="PC", user="u", event_type="created", detected_at="t",
                 source_hint=None, prev_hash=prev_hash, record_hash="")
    digest = compute_record_hash(event_payload(base), prev_hash)
    return dataclasses.replace(base, record_hash=digest)


def test_payload_excludes_id_and_hashes() -> None:
    payload = event_payload(_event(1, None))
    assert "id" not in payload
    assert "record_hash" not in payload
    assert "prev_hash" not in payload
    assert payload["sha256"] == f"{1:064x}"


def test_clean_chain_verifies() -> None:
    e1 = _event(1, None)
    e2 = _event(2, e1.record_hash)
    e3 = _event(3, e2.record_hash)
    assert verify_chain([e1, e2, e3]) is None


def test_tamper_detected() -> None:
    e1 = _event(1, None)
    e2 = _event(2, e1.record_hash)
    tampered = dataclasses.replace(e2, name="HACKED")
    assert verify_chain([e1, tampered]) == 2


def test_broken_prev_link_detected() -> None:
    e1 = _event(1, None)
    e2 = _event(2, "wrong")
    assert verify_chain([e1, e2]) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_chain.py -v`
Expected: FAIL — `ImportError` (event_payload 없음)

- [ ] **Step 3: 구현 (전체 교체)**

`server/app/chain.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_chain.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/chain.py server/tests/test_chain.py
git commit -m "feat: 해시체인을 event 대상으로 교체"
```

---

## Task 4: 저장소 — supervise_file·update_history (repository.py 1부)

**Files:**
- Replace: `server/app/repository.py`
- Replace test: `server/tests/test_repository.py`

- [ ] **Step 1: 실패 테스트 작성 (기존 교체)**

`server/tests/test_repository.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v`
Expected: FAIL — `ImportError`/`SqliteRepository` 시그니처 없음

- [ ] **Step 3: 구현 (전체 교체 — 이 Task에서 supervise_file·update_history 부분만, event/trace_match는 Task 5에서 추가)**

`server/app/repository.py`:
```python
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
```

> **Task 5에서** 같은 클래스에 `add_event`/`add_trace_matches`/`list_events`/`all_events`/
> `best_trace_match`를 추가한다. 이 Task의 import에 Event·EventInput·MatchResult·TraceMatch·
> compute_record_hash·event_payload·replace·Sequence가 이미 있으나 Task 4 메서드에선 미사용
> — Task 5에서 사용하므로 그대로 둔다(린트 경고 무시 가능).

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/repository.py server/tests/test_repository.py
git commit -m "feat: SqliteRepository supervise_file·update_history"
```

---

## Task 5: 저장소 — event·trace_match (repository.py 2부)

**Files:**
- Modify: `server/app/repository.py` (메서드 추가)
- Modify test: `server/tests/test_repository.py` (테스트 추가)

- [ ] **Step 1: 실패 테스트 추가 (test_repository.py 끝에 append)**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v`
Expected: FAIL — `add_event` 없음

- [ ] **Step 3: 구현 — repository.py 클래스에 메서드 추가 (Task 4 마지막 메서드 뒤에)**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/repository.py server/tests/test_repository.py
git commit -m "feat: SqliteRepository event·trace_match(체인·매칭저장)"
```

---

## Task 6: API 교체 (api.py, main.py)

**Files:**
- Replace: `server/app/api.py`
- Modify: `server/app/main.py`
- Replace test: `server/tests/test_api.py`
- Delete: `server/tests/test_scenarios.py` (구 스키마 시나리오 — 새 통합 테스트로 대체)

- [ ] **Step 1: 실패 테스트 작성 (test_api.py 교체) + 구 test_scenarios.py 삭제**

`server/tests/test_api.py`:
```python
"""API 통합 테스트(TestClient + SqliteRepository(:memory:))."""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import build_app
from app.repository import SqliteRepository

BIG = ("Confidential design dossier. " * 40).encode()


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(SqliteRepository(":memory:")))


def _upload(client, content: bytes, name: str):
    return client.post("/api/fingerprints",
                       files={"file": (name, io.BytesIO(content), "application/octet-stream")})


def test_mode_a_new_baseline(client) -> None:
    r = _upload(client, BIG, "secret.dwg")
    assert r.status_code == 200
    body = r.json()
    assert body["was_update"] is False
    assert body["supervise_file"]["name"] == "secret.dwg"
    # supervise-files 목록에 1건, history 0
    files = client.get("/api/supervise-files").json()["supervise_files"]
    assert len(files) == 1
    assert files[0]["update_history_count"] == 0


def test_mode_a_reupload_snapshots(client) -> None:
    _upload(client, BIG, "secret.dwg")
    r = _upload(client, BIG + b"changed", "secret.dwg")
    assert r.json()["was_update"] is True
    files = client.get("/api/supervise-files").json()["supervise_files"]
    assert len(files) == 1
    assert files[0]["update_history_count"] == 1


def test_mode_b_event_creates_trace_match(client) -> None:
    _upload(client, BIG, "secret.dwg")             # baseline 등록
    import hashlib
    import ppdeep
    payload = {"sha256": hashlib.sha256(BIG).hexdigest(), "fuzzy_hash": ppdeep.hash(BIG),
               "size": len(BIG), "name": "copy_on_pc.dwg", "event_type": "created",
               "host": "PC-9", "user": "lee"}
    r = client.post("/api/fingerprints", json=payload)
    assert r.status_code == 200
    matches = r.json()["matches"]
    assert any(m["match_type"] == "exact" for m in matches)
    # events 목록에 trace_match 요약
    events = client.get("/api/events").json()["events"]
    assert events[0]["name"] == "copy_on_pc.dwg"
    assert events[0]["best_match"]["similarity"] == 100


def test_mode_b_missing_sha_400(client) -> None:
    assert client.post("/api/fingerprints", json={"size": 1}).status_code == 400
```

(구 `server/tests/test_scenarios.py`는 삭제한다 — `git rm`.)

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_api.py -v`
Expected: FAIL — 새 응답 형태 없음

- [ ] **Step 3: 구현 (api.py 전체 교체, main.py 갱신)**

`server/app/api.py`:
```python
"""FastAPI 라우트. 모드 a=baseline 등록, 모드 b=이벤트+자동 매칭, GET 2개."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.errors import HttpError, InvalidFingerprintRequestError
from app.fingerprint import compute_fuzzy, compute_sha256
from app.matching import find_matches
from app.models import EventInput, Fingerprint
from app.repository import SqliteRepository

_STATIC_DIR = Path(__file__).parent / "static"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_app(repository: SqliteRepository) -> FastAPI:
    """저장소를 주입받아 FastAPI 앱을 구성한다."""
    app = FastAPI(title="file-tracer")

    @app.exception_handler(HttpError)
    async def _http_error_handler(_: Request, exc: HttpError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    @app.post("/api/fingerprints")
    async def post_fingerprints(request: Request) -> dict:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            return await _handle_mode_a(request, repository)
        if content_type.startswith("application/json"):
            return await _handle_mode_b(request, repository)
        raise InvalidFingerprintRequestError("multipart 또는 JSON 요청이어야 합니다")

    @app.get("/api/supervise-files")
    async def get_supervise_files() -> dict:
        items = []
        for sf in repository.list_supervise_files():
            items.append({
                "id": sf.id, "name": sf.name, "sha256": sf.sha256,
                "fuzzy_hash": sf.fuzzy_hash, "size": sf.size,
                "created_at": sf.created_at, "updated_at": sf.updated_at,
                "update_history_count": repository.count_update_history(sf.id),
            })
        return {"supervise_files": items}

    @app.get("/api/events")
    async def get_events() -> dict:
        items = []
        for ev in repository.list_events(limit=100):
            best = repository.best_trace_match(ev.id)
            best_dict = None
            if best is not None:
                sf = repository.get_supervise_file(best.supervise_file_id)
                best_dict = {"supervise_file_id": best.supervise_file_id,
                             "name": sf.name if sf else None,
                             "match_type": best.match_type, "similarity": best.similarity}
            items.append({
                "id": ev.id, "sha256": ev.sha256, "name": ev.name,
                "event_type": ev.event_type, "host": ev.host, "user": ev.user,
                "detected_at": ev.detected_at, "best_match": best_dict,
            })
        return {"events": items}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app


async def _handle_mode_a(request: Request, repository: SqliteRepository) -> dict:
    """모드 a: 파일 업로드 → baseline 등록/갱신."""
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        raise InvalidFingerprintRequestError("file 필드가 필요합니다")
    data = await upload.read()
    fp = Fingerprint(sha256=compute_sha256(data), fuzzy_hash=compute_fuzzy(data), size=len(data))
    sf, was_update = repository.register_supervise_file(upload.filename or "unknown", fp, _now_iso())
    return {
        "was_update": was_update,
        "supervise_file": {"id": sf.id, "name": sf.name, "sha256": sf.sha256,
                           "fuzzy_hash": sf.fuzzy_hash, "size": sf.size,
                           "created_at": sf.created_at, "updated_at": sf.updated_at},
    }


async def _handle_mode_b(request: Request, repository: SqliteRepository) -> dict:
    """모드 b: 클라 지문 JSON → 이벤트 기록 + 자동 매칭."""
    payload = await request.json()
    sha256 = payload.get("sha256")
    if not sha256:
        raise InvalidFingerprintRequestError("sha256 필드가 필요합니다")
    ev_input = EventInput(
        sha256=sha256, fuzzy_hash=payload.get("fuzzy_hash"),
        size=int(payload.get("size", 0)), name=payload.get("name", "unknown"),
        event_type=payload.get("event_type", "created"),
        host=payload.get("host"), user=payload.get("user"),
        source_hint=payload.get("source_hint"),
    )
    now = _now_iso()
    event = repository.add_event(ev_input, now)
    matches = find_matches(event.sha256, event.fuzzy_hash, repository.list_supervise_files())
    repository.add_trace_matches(event.id, matches, now)
    return {
        "event_id": event.id,
        "matches": [{"supervise_file_id": m.supervise_file_id, "name": m.name,
                     "match_type": m.match_type, "similarity": m.similarity} for m in matches],
    }
```

`server/app/main.py` (전체 교체):
```python
"""uvicorn 진입점. SqliteRepository로 앱을 구성한다.

실행(사용자 확인 후): python -m uvicorn app.main:app --reload --port 8000
"""

from pathlib import Path

from app.api import build_app
from app.repository import SqliteRepository

_DB_PATH = Path(__file__).parent.parent / "file_tracer.db"

app = build_app(SqliteRepository(_DB_PATH))
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git rm server/tests/test_scenarios.py
git add server/app/api.py server/app/main.py server/tests/test_api.py
git commit -m "feat: API를 새 스키마(모드 a/b·GET 2개)로 교체"
```

---

## Task 7: 웹페이지 갱신 + 전체 회귀 (static/index.html)

**Files:**
- Replace: `server/app/static/index.html`
- Replace test: `server/tests/test_static.py`

- [ ] **Step 1: 실패 테스트 (test_static.py 교체)**

`server/tests/test_static.py`:
```python
"""정적 웹페이지 서빙·내용 테스트."""

from fastapi.testclient import TestClient

from app.api import build_app
from app.repository import SqliteRepository


def test_index_served_with_tables() -> None:
    client = TestClient(build_app(SqliteRepository(":memory:")))
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text.lower()
    assert "file-tracer" in text
    assert "supervise" in text          # baseline 표
    assert "event" in text              # 이벤트 표
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_static.py -v`
Expected: FAIL (기존 페이지엔 supervise/event 표 없음)

- [ ] **Step 3: 구현 (index.html 전체 교체)**

`server/app/static/index.html`:
```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>file-tracer</title>
  <style>
    body { font-family: sans-serif; max-width: 1000px; margin: 2rem auto; }
    table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.5rem; }
    th, td { border: 1px solid #ccc; padding: 4px 8px; font-size: 13px; }
    th { background: #f3f3f3; }
  </style>
</head>
<body>
  <h1>file-tracer</h1>

  <h2>위험파일 등록 (baseline 업로드)</h2>
  <form id="upload-form">
    <input type="file" id="file-input" required />
    <button type="submit">등록</button>
  </form>

  <h2>감시 대상 (supervise_file)</h2>
  <table id="files">
    <thead><tr><th>id</th><th>name</th><th>sha256</th><th>버전이력</th><th>updated</th></tr></thead>
    <tbody></tbody>
  </table>

  <h2>이벤트 (event + 매칭)</h2>
  <table id="events">
    <thead><tr><th>id</th><th>event</th><th>name</th><th>host</th><th>최고매칭</th><th>time</th></tr></thead>
    <tbody></tbody>
  </table>

  <script>
    const form = document.getElementById('upload-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData();
      fd.append('file', document.getElementById('file-input').files[0]);
      await fetch('/api/fingerprints', { method: 'POST', body: fd });
      await refresh();
    });

    async function refresh() {
      const files = (await (await fetch('/api/supervise-files')).json()).supervise_files;
      document.querySelector('#files tbody').innerHTML = files.map(f =>
        `<tr><td>${f.id}</td><td>${f.name}</td><td>${f.sha256.slice(0,12)}…</td>` +
        `<td>${f.update_history_count}</td><td>${f.updated_at}</td></tr>`).join('');

      const events = (await (await fetch('/api/events')).json()).events;
      document.querySelector('#events tbody').innerHTML = events.map(ev => {
        const bm = ev.best_match
          ? `${ev.best_match.name} (${ev.best_match.match_type} ${ev.best_match.similarity})`
          : '-';
        return `<tr><td>${ev.id}</td><td>${ev.event_type}</td><td>${ev.name}</td>` +
               `<td>${ev.host || '-'}</td><td>${bm}</td><td>${ev.detected_at}</td></tr>`;
      }).join('');
    }
    refresh();
  </script>
</body>
</html>
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest -v`
Expected: 전체 PASS (test_fingerprint·test_smoke 유지 + 새 테스트들). 0 실패.

- [ ] **Step 5: 커밋**

```bash
git add server/app/static/index.html server/tests/test_static.py
git commit -m "feat: 웹페이지를 baseline·event 표로 갱신"
```

- [ ] **Step 6: (선택) 수동 E2E — ⚠ 사용자 확인 후**

기존 `server/file_tracer.db` 삭제(구 스키마) 후 서버 기동:
`Set-Location server; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`
→ 파일 업로드(baseline 등록)·재업로드(버전이력 +1)·클라 에이전트 이벤트가 매칭과 함께 표에 뜨는지 확인.

---

## Self-Review (작성자 점검 결과)

**Spec 커버리지:**
- §3 테이블 4개 → Task 4·5 `_SCHEMA` ✔
- §4.1 모드 a(신규/재업로드 스냅샷) → Task 4 `register_supervise_file` + Task 6 `_handle_mode_a` ✔
- §4.2 모드 b(event 체인 + trace_match 자동) → Task 5 `add_event`/`add_trace_matches` + Task 6 `_handle_mode_b` ✔
- §5 GET 2개(history 수·best match) → Task 6 ✔
- §6 코드 변경(models·repository 단일·matching·chain·api) → Task 1~6 ✔
- §6 chain은 event만 → Task 3·5 ✔
- §7 테스트(단위·통합·체인·GET) → 각 Task ✔
- §2 마이그레이션(records 버림) → 구 스키마 코드/테스트 전부 교체, 수동 E2E 전 db 삭제 안내 ✔
- 범위 밖(클라 로그·copy/upload/download 로직·인증) → 미구현 ✔

**Placeholder 스캔:** 없음. 모든 코드 단계에 실제 코드.

**타입 일관성:** `Fingerprint`/`SuperviseFile`/`Event`/`EventInput`/`TraceMatch`/`MatchResult` 필드와 `register_supervise_file`(→tuple[SuperviseFile,bool])·`add_event`·`add_trace_matches`·`find_matches`(sha,fuzzy,supervise_files)·`event_payload`/`verify_chain`(events) 시그니처가 Task 간 일치. `MatchResult.supervise_file_id`를 matching·repository·api에서 동일 사용.

**알려진 주의점:** Task 4에서 repository.py가 Task 5용 import(Event·EventInput 등)를 미리 갖되 Task 4 메서드에선 일부 미사용 — Task 5에서 사용하므로 의도적. 통합 테스트의 fuzzy 매칭은 충분한 크기 텍스트(BIG, 비반복) 사용으로 ssdeep 블록 민감성 회피.
