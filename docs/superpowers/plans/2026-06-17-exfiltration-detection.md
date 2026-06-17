# 외부 반출 탐지(브라우저 채널) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chrome Content Analysis Connector로 `upload`/`download`/`paste` 이벤트를 잡아 지문+메타(목적지 url)를 서버에 기록하고 대시보드에 띄운다.

**Architecture:** 2프로세스(Python 호스트 + C++ 브리지). 브리지는 Chrome 파이프에서 받아 즉시 ALLOW + loopback JSON 전달만. Python 측은 `connector`가 지문·매핑해 `TraceEvent`를 `core`로 보내고, 코어가 기존 `Sender`로 서버에 POST한다. 서버는 정규화된 `web_event_detail` 테이블에 url을 저장한다.

**Tech Stack:** Python 3.12, FastAPI, sqlite3(표준), ppdeep, httpx, pytest, stdlib http.server, (마지막) C++ content_analysis_sdk.

**승인된 설계:** `docs/superpowers/specs/2026-06-17-exfiltration-detection-design.md`

## Global Constraints

- `python`은 PATH에 없음 → 항상 `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe`(공유 venv). 명령은 PowerShell.
- 클라 테스트는 `client` 디렉터리에서(`pytest.ini`: `pythonpath = .`), 서버 테스트는 `server` 디렉터리에서.
- 각 Task는 TDD: 실패 테스트 → 실패 확인 → 최소 구현 → 통과 확인 → 커밋.
- **명령 실행(테스트·커밋 포함)·git 작업은 사용자 확인 후.** 새 의존성 설치 없음(전부 기존 스택).
- 본문(파일/텍스트)은 로컬에서 지문으로만 변환하고 폐기 — 서버로 본문 전송 금지(지문+메타만).
- 커밋 메시지 끝: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. 브랜치 `feat/exfiltration-detection`.
- 모든 파일 200줄 미만·단일 책임. 불변(frozen dataclass) 우선.

---

## File Structure

```
client/
  common/
    __init__.py
    fingerprint.py      ← agent/에서 이동 (SHA256+ssdeep)
    events.py           ← 신규: EVENT_* 상수 + TraceEvent
  core/
    __init__.py
    sender.py           ← agent/에서 이동 (+ user·metadata 인자)
    core.py             ← 신규: 큐 + Sender egress + 로컬 intake
    config.toml         ← 신규
  agent/                (기존, import 갱신 + Task 10에서 코어 경유로 이주)
  connector/
    __init__.py
    mapping.py          ← 신규: 요청 dict → TraceEvent (순수)
    agent.py            ← 신규: 지문+매핑+코어 전송, loopback intake
    config.toml         ← 신규
    README.md           ← 신규: Chrome 정책 셋업
    bridge/             ← 신규(C++, 마지막)
  tests/                (신규·갱신 테스트)

server/app/
  constants.py          EVENT_TYPES 갱신
  models.py             EventInput/Event에 metadata
  chain.py              event_payload에 metadata 포함
  repository.py         web_event_detail 테이블·메서드
  api.py                mode b metadata 라우팅·GET url
  static/index.html     url 표시
```

---

## 공통 타입 계약

```python
# client/common/events.py
EVENT_CREATED="created"; EVENT_MODIFIED="modified"; EVENT_MOVED="moved"; EVENT_DELETED="deleted"
EVENT_UPLOAD="upload"; EVENT_DOWNLOAD="download"; EVENT_PASTE="paste"

@dataclass(frozen=True)
class TraceEvent:
    sha256: str
    fuzzy_hash: str | None
    size: int
    name: str
    event_type: str
    host: str
    user: str | None
    source_hint: str | None
    metadata: dict | None

# client/core/sender.py — Sender.send 시그니처(갱신)
.send(*, sha256, fuzzy_hash, size, name, event_type, source_hint,
      user=None, metadata=None) -> bool

# client/core/core.py — CollectorCore(sender)
.submit(event: TraceEvent) -> None        # 큐에 넣음
.process(event: TraceEvent) -> bool       # 동기 처리(테스트용): sender.send 호출

# client/connector/mapping.py
to_trace_event(req: dict, fp: CachedFingerprint, host: str) -> TraceEvent
# 잘못된 입력(브라우저 event인데 url 없음 등) → MappingError

# server: models
EventInput(..., metadata: dict | None)
Event(..., metadata: dict | None)
# repository
.add_web_event_detail(event_id: int, url: str, dst_host: str|None, tab_title: str|None) -> None
.get_web_event_detail(event_id: int) -> dict | None
```

---

## Task 1: 공유 패키지 추출 (common/·core/) + Sender 확장

기존 `agent/fingerprint.py`·`agent/sender.py`를 공유 위치로 옮기고 import를 갱신한다. 기존 테스트 전부 그린 유지가 합격 기준. Sender엔 `user`·`metadata` 인자를 추가한다.

**Files:**
- Create: `client/common/__init__.py`(빈), `client/core/__init__.py`(빈)
- Create: `client/common/fingerprint.py`(=기존 `agent/fingerprint.py` 내용, import 경로만 `from common.models`가 아니라 `CachedFingerprint`는 `agent.models`에 있으므로 주의 — 아래 Step 참고)
- Create: `client/core/sender.py`(=기존 `agent/sender.py` + 인자 추가)
- Delete: `client/agent/fingerprint.py`, `client/agent/sender.py`
- Modify: `client/agent/worker.py`, `client/agent/scanner.py`(fingerprint import), `client/agent/main.py`(sender import)
- Modify: `client/tests/test_fingerprint.py`, `client/tests/test_sender.py`(import 경로)

> **주의 — `CachedFingerprint` 위치:** 기존 `fingerprint.py`는 `from agent.models import CachedFingerprint`를 쓴다. `CachedFingerprint`는 FS 캐시 전용이 아니라 지문 결과 모델이므로, **`common/fingerprint.py`는 `agent.models`에서 import**한다(이동 안 함). 이렇게 두면 common→agent 역의존이 생기므로, 깔끔하게 하려면 `CachedFingerprint`도 `common/`로 옮기는 게 맞다. **이 Task에선 `CachedFingerprint`를 `common/events.py`가 아닌 `common/fingerprint.py` 안에 함께 정의**하고(원래 models의 정의를 이쪽으로 이동), `agent/models.py`는 `from common.fingerprint import CachedFingerprint`로 재노출한다.

- [ ] **Step 1: 빈 패키지 생성**

`client/common/__init__.py`, `client/core/__init__.py` 빈 파일 생성.

- [ ] **Step 2: `common/fingerprint.py` 생성 (CachedFingerprint 포함)**

`client/common/fingerprint.py`:
```python
"""파일 지문(SHA-256 + ssdeep). 서버 server/app/fingerprint.py와 동일 로직(raw bytes)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import ppdeep


@dataclass(frozen=True)
class CachedFingerprint:
    """캐시·전송에 쓰는 파일 지문."""

    sha256: str
    fuzzy_hash: str | None
    size: int


def compute_sha256(data: bytes) -> str:
    """바이트의 SHA-256 16진 해시."""
    return hashlib.sha256(data).hexdigest()


def compute_fuzzy(data: bytes) -> str | None:
    """바이트의 ssdeep fuzzy 지문. 빈 입력이면 None."""
    if not data:
        return None
    return ppdeep.hash(data)


def fingerprint_file(path: Path) -> CachedFingerprint:
    """파일을 raw bytes로 읽어 지문을 계산한다."""
    data = path.read_bytes()
    return CachedFingerprint(
        sha256=compute_sha256(data),
        fuzzy_hash=compute_fuzzy(data),
        size=len(data),
    )
```

- [ ] **Step 3: `agent/models.py`에서 CachedFingerprint 재노출, 옛 정의 제거**

`client/agent/models.py`에서 `CachedFingerprint` dataclass 정의를 삭제하고 맨 위에 추가:
```python
from common.fingerprint import CachedFingerprint  # noqa: F401  (재노출, 하위호환)
```

- [ ] **Step 4: `core/sender.py` 생성 (user·metadata 인자 추가)**

`client/core/sender.py`:
```python
"""서버 POST /api/fingerprints 모드 b 전송. 재시도 후 실패 시 로그."""

import logging

import httpx

logger = logging.getLogger("core.sender")


class Sender:
    """지문 이벤트를 서버 모드 b(JSON)로 전송한다."""

    def __init__(self, server_url: str, host: str, user: str,
                 client: httpx.Client | None = None, retries: int = 2) -> None:
        self._url = server_url.rstrip("/") + "/api/fingerprints"
        self._host = host
        self._user = user
        self._client = client or httpx.Client(timeout=5.0)
        self._retries = retries

    def send(self, *, sha256: str, fuzzy_hash: str | None, size: int, name: str,
             event_type: str, source_hint: str | None,
             user: str | None = None, metadata: dict | None = None) -> bool:
        """이벤트를 전송한다. 성공(200)이면 True, 재시도 후에도 실패면 False."""
        payload = {
            "sha256": sha256, "fuzzy_hash": fuzzy_hash, "size": size, "name": name,
            "event_type": event_type, "host": self._host,
            "user": user if user is not None else self._user,
            "source_hint": source_hint, "metadata": metadata,
        }
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.post(self._url, json=payload)
                if resp.status_code == 200:
                    return True
                logger.warning("전송 실패 status=%s (시도 %s)", resp.status_code, attempt + 1)
            except httpx.HTTPError as exc:
                logger.warning("전송 예외 %s (시도 %s)", exc, attempt + 1)
        logger.error("전송 최종 실패: name=%s event=%s", name, event_type)
        return False
```

- [ ] **Step 5: 옛 파일 삭제 + agent import 갱신**

```bash
git rm client/agent/fingerprint.py client/agent/sender.py
```
`client/agent/worker.py`·`client/agent/scanner.py`: `from agent.fingerprint import ...` → `from common.fingerprint import ...`.
`client/agent/main.py`: `from agent.sender import Sender` → `from core.sender import Sender`.

- [ ] **Step 6: 테스트 import 갱신 + Sender 신규 인자 테스트 추가**

`client/tests/test_fingerprint.py`: `from agent.fingerprint import ...` → `from common.fingerprint import ...`.
`client/tests/test_sender.py`: `from agent.sender import Sender` → `from core.sender import Sender`. 그리고 아래 테스트 추가:
```python
def test_send_includes_user_override_and_metadata() -> None:
    CAPTURED.clear()
    client = httpx.Client(transport=_ok_transport())
    sender = Sender("http://srv", host="PC-1", user="default", client=client)
    sender.send(sha256="a" * 64, fuzzy_hash=None, size=1, name="x",
                event_type="upload", source_hint=None,
                user="kim@corp.com", metadata={"url": "https://drive.google.com"})
    assert CAPTURED[-1]["user"] == "kim@corp.com"
    assert CAPTURED[-1]["metadata"] == {"url": "https://drive.google.com"}
```

- [ ] **Step 7: 전체 클라 테스트 그린 확인**

Run (client에서): `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest -v`
Expected: 기존 + 신규 전부 PASS.

- [ ] **Step 8: 커밋**

```bash
git add client/common client/core client/agent client/tests
git commit -m "refactor: 지문·전송을 common/·core/로 추출, Sender에 user·metadata 인자 추가"
```

---

## Task 2: TraceEvent + event_type 상수 (common/events.py)

**Files:**
- Create: `client/common/events.py`
- Test: `client/tests/test_trace_event.py`

**Interfaces:**
- Produces: `TraceEvent`(frozen, 필드 §공통 타입 계약), `EVENT_UPLOAD/DOWNLOAD/PASTE` 등 상수.

- [ ] **Step 1: 실패 테스트**

`client/tests/test_trace_event.py`:
```python
"""TraceEvent·event_type 상수 테스트."""

import dataclasses

import pytest

from common import events
from common.events import TraceEvent


def test_event_type_constants() -> None:
    assert events.EVENT_UPLOAD == "upload"
    assert events.EVENT_DOWNLOAD == "download"
    assert events.EVENT_PASTE == "paste"
    assert events.EVENT_CREATED == "created"


def test_trace_event_frozen_and_fields() -> None:
    ev = TraceEvent(sha256="a" * 64, fuzzy_hash=None, size=1, name="f",
                    event_type="upload", host="PC", user="kim@corp.com",
                    source_hint=None, metadata={"url": "https://x"})
    assert ev.metadata["url"] == "https://x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.name = "y"  # type: ignore[misc]
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_trace_event.py -v` → FAIL (`No module named 'common.events'`)

- [ ] **Step 3: 구현**

`client/common/events.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_trace_event.py -v` → PASS (2)

- [ ] **Step 5: 커밋**

```bash
git add client/common/events.py client/tests/test_trace_event.py
git commit -m "feat: TraceEvent 공통 계약과 event_type 상수"
```

---

## Task 3: 서버 모델·상수에 metadata 추가 (models.py, constants.py)

**Files:**
- Modify: `server/app/models.py`(EventInput·Event에 `metadata: dict | None`)
- Modify: `server/app/constants.py`(EVENT_TYPES에 upload/download/paste)
- Modify: `server/tests/test_models.py`

**Interfaces:**
- Produces: `EventInput(..., metadata)`, `Event(..., metadata)`.

- [ ] **Step 1: 실패 테스트 추가**

`server/tests/test_models.py`에 추가:
```python
def test_event_has_metadata_field() -> None:
    from app.models import Event, EventInput
    ei = EventInput(sha256="a" * 64, fuzzy_hash=None, size=1, name="n",
                    event_type="upload", host="h", user="u", source_hint=None,
                    metadata={"url": "https://x"})
    assert ei.metadata == {"url": "https://x"}
    ev = Event(id=1, sha256="a" * 64, fuzzy_hash=None, size=1, name="n", host="h",
               user="u", event_type="upload", detected_at="t", source_hint=None,
               metadata={"url": "https://x"}, prev_hash=None, record_hash="h")
    assert ev.metadata == {"url": "https://x"}


def test_web_event_types_in_constants() -> None:
    from app import constants
    assert "upload" in constants.EVENT_TYPES
    assert "download" in constants.EVENT_TYPES
    assert "paste" in constants.EVENT_TYPES
```

- [ ] **Step 2: 실패 확인**

Run (server에서): `… -m pytest tests/test_models.py -v` → FAIL(`metadata` 인자 없음)

- [ ] **Step 3: 구현**

`server/app/constants.py`의 `EVENT_TYPES`를 교체:
```python
EVENT_TYPES = ("created", "modified", "moved", "deleted", "upload", "download", "paste")
RESERVED_EVENT_TYPES = ("copy",)  # upload/download는 승격됨
```

`server/app/models.py`의 `EventInput`·`Event`에 `metadata: dict | None` 필드 추가:
```python
@dataclass(frozen=True)
class EventInput:
    sha256: str
    fuzzy_hash: str | None
    size: int
    name: str
    event_type: str
    host: str | None
    user: str | None
    source_hint: str | None
    metadata: dict | None = None


@dataclass(frozen=True)
class Event:
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
    metadata: dict | None
    prev_hash: str | None
    record_hash: str
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_models.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/models.py server/app/constants.py server/tests/test_models.py
git commit -m "feat: 서버 이벤트 모델에 metadata, EVENT_TYPES에 upload/download/paste"
```

---

## Task 4: 해시체인에 metadata 포함 (chain.py)

**Files:**
- Modify: `server/app/chain.py`(`_PAYLOAD_FIELDS`에 `metadata`)
- Modify: `server/tests/test_chain.py`(_event 헬퍼 metadata, 변조 테스트)

- [ ] **Step 1: 실패 테스트**

`server/tests/test_chain.py`의 `_event` 헬퍼에 `metadata`를 추가하고(기존 Event 생성에 `metadata=None,` 삽입), 아래 테스트 추가:
```python
def test_metadata_tamper_detected() -> None:
    import dataclasses
    from app.chain import compute_record_hash, event_payload, verify_chain
    from app.models import Event

    def _ev(idx, prev, meta):
        base = Event(id=idx, sha256=f"{idx:064x}", fuzzy_hash=None, size=1, name="f",
                     host="PC", user="u", event_type="upload", detected_at="t",
                     source_hint=None, metadata=meta, prev_hash=prev, record_hash="")
        return dataclasses.replace(base, record_hash=compute_record_hash(event_payload(base), prev))

    e1 = _ev(1, None, {"url": "https://good"})
    tampered = dataclasses.replace(e1, metadata={"url": "https://evil"})
    assert verify_chain([tampered]) == 1
```

> 기존 test_chain의 다른 `_event`/테스트들도 `Event(...)` 호출에 `metadata=None,`을 넣어 갱신할 것(detected_at 다음, prev_hash 앞).

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_chain.py -v` → FAIL(metadata 인자 없음 또는 변조 미탐)

- [ ] **Step 3: 구현**

`server/app/chain.py`의 `_PAYLOAD_FIELDS`에 `metadata` 추가:
```python
_PAYLOAD_FIELDS = (
    "sha256", "fuzzy_hash", "size", "name", "host", "user",
    "event_type", "detected_at", "source_hint", "metadata",
)
```
(`event_payload`는 `getattr`로 동작하므로 dict인 metadata도 그대로 들어가고, `compute_record_hash`의 `json.dumps(sort_keys=True)`가 dict를 canonical 직렬화한다 — 변경 불필요.)

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_chain.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/chain.py server/tests/test_chain.py
git commit -m "feat: 해시체인에 metadata 포함(url 변조 탐지)"
```

---

## Task 5: web_event_detail 테이블·저장 (repository.py)

**Files:**
- Modify: `server/app/repository.py`(스키마에 테이블, `add_event` metadata 직렬화, `add_web_event_detail`/`get_web_event_detail`, `_event_from_row` metadata 파싱, list/all_events)
- Modify: `server/tests/test_repository.py`

**Interfaces:**
- Produces: `add_web_event_detail(event_id, url, dst_host, tab_title)`, `get_web_event_detail(event_id) -> dict|None`.

- [ ] **Step 1: 실패 테스트 추가**

`server/tests/test_repository.py`에 추가:
```python
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
```

> 기존 `test_repository.py`의 `_ev`/add_event 테스트가 `EventInput`을 만들 때 metadata 기본값(None)이 있으므로 그대로 통과한다(EventInput.metadata 기본값 None).

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_repository.py -v` → FAIL(`add_web_event_detail` 없음 등)

- [ ] **Step 3: 구현**

`server/app/repository.py` `_SCHEMA`에 테이블 추가:
```python
CREATE TABLE IF NOT EXISTS web_event_detail (
  event_id  INTEGER PRIMARY KEY REFERENCES event(id),
  url       TEXT NOT NULL,
  dst_host  TEXT,
  tab_title TEXT
);
```
`event` 테이블 정의에 `metadata TEXT` 컬럼 추가(`source_hint TEXT,` 다음):
```python
  source_hint TEXT, metadata TEXT, prev_hash TEXT, record_hash TEXT NOT NULL
```
파일 상단에 `import json` 추가. `add_event`에서 INSERT 컬럼·값에 metadata 직렬화 추가:
```python
metadata_json = json.dumps(ev.metadata, sort_keys=True, ensure_ascii=False) if ev.metadata else None
# draft Event 생성 시 metadata=ev.metadata 포함
# INSERT 문에 metadata 컬럼/플레이스홀더 추가, 값은 metadata_json
```
`draft = Event(...)` 생성에 `metadata=ev.metadata,`를 detected_at 이후·prev_hash 이전에 넣는다(체인 payload가 metadata를 보도록). `_event_from_row`에 metadata 파싱:
```python
metadata=json.loads(row["metadata"]) if row["metadata"] else None,
```
신규 메서드 추가:
```python
    def add_web_event_detail(self, event_id: int, url: str,
                             dst_host: str | None, tab_title: str | None) -> None:
        """브라우저 이벤트의 url 등 detail을 저장한다(event당 1행)."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO web_event_detail (event_id, url, dst_host, tab_title) "
                "VALUES (?, ?, ?, ?)",
                (event_id, url, dst_host, tab_title),
            )
            self._conn.commit()

    def get_web_event_detail(self, event_id: int) -> dict | None:
        """브라우저 이벤트 detail을 반환(없으면 None)."""
        cur = self._conn.execute(
            "SELECT url, dst_host, tab_title FROM web_event_detail WHERE event_id = ?",
            (event_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"url": row["url"], "dst_host": row["dst_host"], "tab_title": row["tab_title"]}
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_repository.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/repository.py server/tests/test_repository.py
git commit -m "feat: web_event_detail 테이블·metadata 영속화"
```

---

## Task 6: API mode b metadata 라우팅 + GET url (api.py)

**Files:**
- Modify: `server/app/api.py`(`_handle_mode_b`에서 metadata 수신·web_event_detail INSERT, `get_events`에 url 포함)
- Modify: `server/tests/test_api.py`

- [ ] **Step 1: 실패 테스트 추가**

`server/tests/test_api.py`에 추가:
```python
def test_mode_b_upload_stores_url(client) -> None:
    payload = {"sha256": "a" * 64, "fuzzy_hash": None, "size": 5, "name": "s.dwg",
               "event_type": "upload", "host": "PC", "user": "kim@corp.com",
               "metadata": {"url": "https://drive.google.com/x",
                            "dst_host": "drive.google.com", "tab_title": "Drive"}}
    r = client.post("/api/fingerprints", json=payload)
    assert r.status_code == 200
    events = client.get("/api/events").json()["events"]
    assert events[0]["event_type"] == "upload"
    assert events[0]["url"] == "https://drive.google.com/x"
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_api.py -v` → FAIL(응답에 url 없음)

- [ ] **Step 3: 구현**

`server/app/api.py` `_handle_mode_b`에서 EventInput 생성에 `metadata=payload.get("metadata")` 추가하고, add_event 후 라우팅:
```python
from app.constants import EVENT_TYPES  # 상단(필요시)

ev_input = EventInput(
    sha256=sha256, fuzzy_hash=payload.get("fuzzy_hash"),
    size=int(payload.get("size", 0)), name=payload.get("name", "unknown"),
    event_type=payload.get("event_type", "created"),
    host=payload.get("host"), user=payload.get("user"),
    source_hint=payload.get("source_hint"),
    metadata=payload.get("metadata"),
)
now = _now_iso()
event = repository.add_event(ev_input, now)
meta = ev_input.metadata or {}
if event.event_type in ("upload", "download", "paste"):
    url = meta.get("url")
    if url:
        repository.add_web_event_detail(event.id, url, meta.get("dst_host"), meta.get("tab_title"))
matches = find_matches(event.sha256, event.fuzzy_hash, repository.list_supervise_files())
repository.add_trace_matches(event.id, matches, now)
```
`get_events`의 각 event dict에 url 추가:
```python
detail = repository.get_web_event_detail(ev.id)
items.append({
    "id": ev.id, "sha256": ev.sha256, "name": ev.name,
    "event_type": ev.event_type, "host": ev.host, "user": ev.user,
    "detected_at": ev.detected_at, "best_match": best_dict,
    "url": detail["url"] if detail else None,
})
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_api.py -v` → PASS. 이어서 서버 전체 회귀: `… -m pytest -v` → 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add server/app/api.py server/tests/test_api.py
git commit -m "feat: mode b metadata를 web_event_detail로 라우팅, GET events에 url"
```

---

## Task 7: core — 큐 + Sender egress (core.py)

**Files:**
- Create: `client/core/core.py`
- Test: `client/tests/test_core.py`

**Interfaces:**
- Consumes: `Sender.send(...)`(Task 1), `TraceEvent`(Task 2)
- Produces: `CollectorCore(sender)`, `.submit(event)`, `.process(event)->bool`, `.start()/.stop()`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_core.py`:
```python
"""CollectorCore — TraceEvent를 받아 Sender로 전송."""

from core.core import CollectorCore
from common.events import TraceEvent


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def _ev() -> TraceEvent:
    return TraceEvent(sha256="a" * 64, fuzzy_hash="3:x", size=5, name="s.dwg",
                      event_type="upload", host="PC", user="kim@corp.com",
                      source_hint=None, metadata={"url": "https://drive.google.com"})


def test_process_forwards_to_sender_with_metadata() -> None:
    sender = FakeSender()
    core = CollectorCore(sender)
    assert core.process(_ev()) is True
    call = sender.calls[-1]
    assert call["event_type"] == "upload"
    assert call["user"] == "kim@corp.com"
    assert call["metadata"] == {"url": "https://drive.google.com"}
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_core.py -v` → FAIL(`No module named 'core.core'`)

- [ ] **Step 3: 구현**

`client/core/core.py`:
```python
"""수집기들의 단일 서버 egress. TraceEvent를 받아 큐에 쌓고 Sender로 순차 전송한다.

채널·지문을 모른다 — 받은 TraceEvent를 모드 b로 직렬화해 보낼 뿐이다. 향후 outbox
버퍼·dedup·인증 토큰이 이 한 곳에 붙는다(현재는 큐 + Sender).
"""

import logging
import queue
import threading

from common.events import TraceEvent

logger = logging.getLogger("core.core")


class CollectorCore:
    """단일 워커 스레드로 TraceEvent를 서버에 전송한다."""

    def __init__(self, sender) -> None:
        self._sender = sender
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join()

    def submit(self, event: TraceEvent) -> None:
        """전송할 TraceEvent를 큐에 넣는다."""
        self._queue.put(event)

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                break
            try:
                self.process(event)
            except Exception as exc:  # 코어 루프는 어떤 예외에도 죽지 않는다
                logger.exception("코어 전송 실패: %s", exc)

    def process(self, event: TraceEvent) -> bool:
        """TraceEvent 1건을 서버로 전송한다(동기, 테스트에서 직접 호출 가능)."""
        return self._sender.send(
            sha256=event.sha256, fuzzy_hash=event.fuzzy_hash, size=event.size,
            name=event.name, event_type=event.event_type, source_hint=event.source_hint,
            user=event.user, metadata=event.metadata,
        )
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_core.py -v` → PASS

- [ ] **Step 5: 커밋**

```bash
git add client/core/core.py client/tests/test_core.py
git commit -m "feat: core 단일 egress(큐+Sender)"
```

---

## Task 8: 커넥터 매핑 (connector/mapping.py)

**Files:**
- Create: `client/connector/__init__.py`(빈), `client/connector/mapping.py`, `client/connector/errors.py`
- Test: `client/tests/test_mapping.py`

**Interfaces:**
- Consumes: `CachedFingerprint`(common.fingerprint), `TraceEvent`(common.events)
- Produces: `to_trace_event(req: dict, fp: CachedFingerprint, host: str) -> TraceEvent`, `MappingError`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_mapping.py`:
```python
"""커넥터 요청 → TraceEvent 매핑(순수)."""

import pytest

from common.fingerprint import CachedFingerprint
from connector.errors import MappingError
from connector.mapping import to_trace_event

FP = CachedFingerprint(sha256="a" * 64, fuzzy_hash="3:x", size=12)


def _req(**over) -> dict:
    base = {"connector": "FILE_ATTACHED", "filename": "s.dwg",
            "url": "https://drive.google.com/x", "email": "kim@corp.com",
            "tab_title": "Drive", "text_content": None}
    base.update(over)
    return base


def test_upload_mapping() -> None:
    ev = to_trace_event(_req(), FP, host="PC-1")
    assert ev.event_type == "upload"
    assert ev.name == "s.dwg"
    assert ev.user == "kim@corp.com"
    assert ev.host == "PC-1"
    assert ev.metadata["url"] == "https://drive.google.com/x"
    assert ev.metadata["dst_host"] == "drive.google.com"
    assert ev.source_hint is None


def test_download_and_paste_event_types() -> None:
    assert to_trace_event(_req(connector="FILE_DOWNLOADED"), FP, "PC").event_type == "download"
    p = to_trace_event(_req(connector="BULK_DATA_ENTRY", filename=""), FP, "PC")
    assert p.event_type == "paste"
    assert p.name == "(pasted text)"


def test_missing_url_raises() -> None:
    with pytest.raises(MappingError):
        to_trace_event(_req(url=None), FP, "PC")


def test_unknown_connector_raises() -> None:
    with pytest.raises(MappingError):
        to_trace_event(_req(connector="PRINT"), FP, "PC")
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_mapping.py -v` → FAIL(`No module named 'connector.mapping'`)

- [ ] **Step 3: 구현**

`client/connector/errors.py`:
```python
"""커넥터 커스텀 예외."""


class MappingError(Exception):
    """커넥터 요청을 TraceEvent로 매핑할 수 없음(필수 필드 누락·미지원 종류)."""
```

`client/connector/mapping.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_mapping.py -v` → PASS (4)

- [ ] **Step 5: 커밋**

```bash
git add client/connector/__init__.py client/connector/mapping.py client/connector/errors.py client/tests/test_mapping.py
git commit -m "feat: 커넥터 요청→TraceEvent 매핑(url 경계 검증)"
```

---

## Task 9: 커넥터 에이전트 — 지문+매핑+코어 전송 (connector/agent.py)

**Files:**
- Create: `client/connector/agent.py`
- Test: `client/tests/test_connector_agent.py`

**Interfaces:**
- Consumes: `to_trace_event`(Task 8), `fingerprint_file`/`compute_*`(common.fingerprint), `CollectorCore.submit`(Task 7)
- Produces: `handle_request(req: dict, core, host: str) -> bool`(지문 계산 후 코어로 submit; 실패 시 False)

- [ ] **Step 1: 실패 테스트**

`client/tests/test_connector_agent.py`:
```python
"""커넥터 에이전트 — 브리지 요청을 지문·매핑해 코어로 보냄."""

from pathlib import Path

from connector.agent import handle_request


class FakeCore:
    def __init__(self) -> None:
        self.events: list = []

    def submit(self, event) -> None:
        self.events.append(event)


def test_file_upload_fingerprints_and_submits(tmp_path: Path) -> None:
    f = tmp_path / "secret.dwg"
    f.write_bytes(b"confidential bytes here for fingerprint")
    req = {"connector": "FILE_ATTACHED", "filename": "secret.dwg",
           "file_path": str(f), "url": "https://drive.google.com/x",
           "email": "kim@corp.com", "tab_title": "Drive", "text_content": None}
    core = FakeCore()
    assert handle_request(req, core, host="PC-1") is True
    ev = core.events[-1]
    assert ev.event_type == "upload"
    assert ev.sha256  # 실제 파일에서 계산됨
    assert ev.metadata["url"] == "https://drive.google.com/x"


def test_paste_fingerprints_text(tmp_path: Path) -> None:
    req = {"connector": "BULK_DATA_ENTRY", "filename": "",
           "file_path": None, "text_content": "secret source code " * 30,
           "url": "https://chat.openai.com", "email": "kim@corp.com", "tab_title": "ChatGPT"}
    core = FakeCore()
    assert handle_request(req, core, host="PC-1") is True
    ev = core.events[-1]
    assert ev.event_type == "paste"
    assert ev.name == "(pasted text)"
    assert ev.sha256


def test_missing_url_drops_event() -> None:
    req = {"connector": "FILE_ATTACHED", "filename": "x", "file_path": None,
           "text_content": None, "url": None, "email": "u"}
    core = FakeCore()
    assert handle_request(req, core, host="PC") is False
    assert core.events == []
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_connector_agent.py -v` → FAIL(`No module named 'connector.agent'`)

- [ ] **Step 3: 구현**

`client/connector/agent.py`:
```python
"""커넥터 에이전트: 브리지가 보낸 raw 요청을 지문·매핑해 코어로 보낸다.

본문(파일/텍스트)은 여기서 지문으로만 변환되고 폐기된다 — 서버로 본문이 가지 않는다.
파일 읽기 실패 시 Chrome digest로 폴백(fuzzy=null), 매핑 실패(url 없음 등)는 드롭+로그.
"""

import logging

from common.events import TraceEvent
from common.fingerprint import (
    CachedFingerprint,
    compute_fuzzy,
    compute_sha256,
    fingerprint_file,
)
from connector.errors import MappingError
from connector.mapping import to_trace_event

logger = logging.getLogger("connector.agent")


def _fingerprint(req: dict) -> CachedFingerprint | None:
    """요청 본문(파일 또는 텍스트)에서 지문을 만든다. 실패 시 digest 폴백/None."""
    text = req.get("text_content")
    if text is not None:
        data = text.encode("utf-8")
        return CachedFingerprint(compute_sha256(data), compute_fuzzy(data), len(data))

    file_path = req.get("file_path")
    if file_path:
        from pathlib import Path
        try:
            return fingerprint_file(Path(file_path))
        except OSError as exc:
            logger.warning("파일 지문 실패 %s: %s — digest 폴백", file_path, exc)
            digest = req.get("digest")
            if digest:
                return CachedFingerprint(digest, None, 0)
    logger.info("지문 불가(본문 없음): %s", req.get("filename"))
    return None


def handle_request(req: dict, core, host: str) -> bool:
    """브리지 요청 1건을 처리한다. 코어로 submit하면 True, 드롭하면 False."""
    fp = _fingerprint(req)
    if fp is None:
        return False
    try:
        event: TraceEvent = to_trace_event(req, fp, host)
    except MappingError as exc:
        logger.warning("매핑 실패, 이벤트 드롭: %s", exc)
        return False
    core.submit(event)
    return True
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_connector_agent.py -v` → PASS (3)

- [ ] **Step 5: 커밋**

```bash
git add client/connector/agent.py client/tests/test_connector_agent.py
git commit -m "feat: 커넥터 에이전트(지문+매핑+코어 전송, 본문 로컬 폐기)"
```

---

## Task 10: Python 내 E2E + loopback intake (connector/agent.py 진입점, core intake)

브리지 없이 "브리지 JSON → connector → core → 서버"를 stdlib http.server로 잇고, TestClient 서버로 통합 검증한다.

**Files:**
- Modify: `client/connector/agent.py`(loopback HTTP intake 진입점 `serve(core, host, port)` 추가)
- Create: `client/connector/config.toml`, `client/core/config.toml`
- Test: `client/tests/test_connector_e2e.py`

**Interfaces:**
- Produces: `serve(core, host, port)` — `POST /event`에 브리지 JSON을 받으면 `handle_request` 호출.

- [ ] **Step 1: 실패 테스트 (실 Chrome 비의존 통합)**

`client/tests/test_connector_e2e.py`:
```python
"""브리지 JSON → connector.handle_request → core → 서버(httpx)까지 한 흐름.

서버는 server 패키지를 import해 TestClient로 띄운다. 실 Chrome·실 브리지 없음.
"""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.api import build_app  # noqa: E402
from app.repository import SqliteRepository  # noqa: E402

from core.core import CollectorCore  # noqa: E402
from core.sender import Sender  # noqa: E402
from connector.agent import handle_request  # noqa: E402


def test_upload_event_reaches_server_with_url(tmp_path: Path) -> None:
    app = build_app(SqliteRepository(":memory:"))
    client = httpx.Client(transport=httpx.ASGITransport(app=app), base_url="http://srv")
    sender = Sender("http://srv", host="PC-1", user="default", client=client)
    core = CollectorCore(sender)

    f = tmp_path / "secret.dwg"
    f.write_bytes(b"confidential bytes for e2e fingerprint test")
    req = {"connector": "FILE_ATTACHED", "filename": "secret.dwg", "file_path": str(f),
           "text_content": None, "url": "https://drive.google.com/x",
           "email": "kim@corp.com", "tab_title": "Drive"}
    assert handle_request(req, core, host="PC-1") is True

    events = client.get("/api/events").json()["events"]
    assert events[0]["event_type"] == "upload"
    assert events[0]["url"] == "https://drive.google.com/x"
    assert events[0]["user"] == "kim@corp.com"
```

> `httpx.ASGITransport`로 FastAPI 앱에 직접 붙는다(별도 포트 불필요). `CollectorCore.process`는 동기 경로라 스레드 없이 `handle_request`→`core.submit`이 큐에 넣는다 — 이 테스트는 `core`를 start하지 않고 `handle_request`가 부른 `submit` 대신 **동기 검증**을 위해 `core.process`를 직접 부르는 형태가 더 결정적이다. 따라서 `handle_request`가 `core.submit`을 호출하되, 테스트용 FakeCore 대신 실제 core를 쓸 땐 아래처럼 process를 직접 검증한다:

```python
    # 결정적 검증: submit 대신 process 직접 호출 경로
    # (handle_request는 submit; 통합 테스트에선 core.start()로 워커를 돌리고 폴링)
```

실제로는 `core.start()` 후 `handle_request` → 큐 → 워커가 전송하므로, 전송 완료를 폴링으로 기다린다:
```python
    import time
    core.start()
    try:
        assert handle_request(req, core, host="PC-1") is True
        deadline = time.time() + 5
        events = []
        while time.time() < deadline:
            events = client.get("/api/events").json()["events"]
            if events:
                break
            time.sleep(0.05)
        assert events and events[0]["url"] == "https://drive.google.com/x"
    finally:
        core.stop()
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_connector_e2e.py -v` → FAIL(import 또는 url 누락)

- [ ] **Step 3: 구현 — loopback intake 진입점 + config**

`client/connector/agent.py`에 추가:
```python
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def serve(core, host: str, port: int) -> HTTPServer:
    """브리지가 POST /event로 보내는 요청을 받는 로컬 HTTP 서버를 만든다(start는 호출자)."""

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body)
                handle_request(req, core, host)
                self.send_response(200)
            except Exception:  # 브리지는 응답만 받으면 됨
                logger.exception("intake 처리 실패")
                self.send_response(500)
            self.end_headers()

        def log_message(self, *args) -> None:  # 기본 stderr 로깅 끔
            pass

    return HTTPServer(("127.0.0.1", port), _Handler)
```

`client/core/config.toml`:
```toml
server_url = "http://127.0.0.1:8000"
intake_port = 8765
```
`client/connector/config.toml`:
```toml
intake_port = 8765
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest tests/test_connector_e2e.py -v` → PASS. 이어 클라 전체: `… -m pytest -v` → PASS.

- [ ] **Step 5: 커밋**

```bash
git add client/connector/agent.py client/connector/config.toml client/core/config.toml client/tests/test_connector_e2e.py
git commit -m "feat: 커넥터 loopback intake + Python 내 E2E(실 Chrome 비의존)"
```

---

## Task 11: FS agent를 코어 경유로 이주 + 호스트 진입점

기존 FS agent가 직접 Sender로 보내던 것을 TraceEvent로 만들어 CollectorCore에 submit하게 바꾸고, Python 호스트 진입점(`client/main.py`)에서 코어·FS agent·커넥터 intake를 한 프로세스로 띄운다.

**Files:**
- Modify: `client/agent/worker.py`(Sender 직접 호출 → TraceEvent 생성 후 `core.submit`)
- Modify: `client/agent/watcher.py`(`build_watcher`가 sender 대신 core를 받음)
- Create: `client/main.py`(호스트 진입점)
- Modify: `client/tests/test_worker.py`, `client/tests/test_watcher.py`(FakeCore로 교체)

**Interfaces:**
- Consumes: `CollectorCore.submit(TraceEvent)`
- Produces: `Worker(cache, core, fingerprint_file=...)`(sender→core 교체), `build_watcher(..., core=...)`

- [ ] **Step 1: 실패 테스트 갱신**

`client/tests/test_worker.py`의 `FakeSender`를 `FakeCore`로 바꾸고 검증을 TraceEvent 기준으로:
```python
from common.events import TraceEvent

class FakeCore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
    def submit(self, event: TraceEvent) -> None:
        self.events.append(event)

# _worker 헬퍼: Worker(cache, FakeCore())
# test_existing_file…: worker.process(Task(...)); 마지막 이벤트 event_type/created 확인
#   assert core.events[-1].event_type == "created"
#   assert core.events[-1].sha256
# test_deleted_uses_cached_fingerprint: core.events[-1].event_type == "deleted"
```
(기존 4개 테스트의 `sender.calls[-1]["..."]` 접근을 `core.events[-1].<속성>`으로 바꾼다. source_hint는 TraceEvent.source_hint로 확인.)

`client/tests/test_watcher.py`의 FakeSender도 동일하게 FakeCore로 교체하고 `build_watcher(..., core=sender)` 인자명을 `core=`로 변경, 검증을 `core.events`로.

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_worker.py tests/test_watcher.py -v` → FAIL

- [ ] **Step 3: 구현**

`client/agent/worker.py`: 생성자 `Worker(cache, core, fingerprint_file=fingerprint_file)`로 바꾸고, `self._sender` → `self._core`. `process`에서 `self._sender.send(...)` 두 곳을 TraceEvent 생성 + `self._core.submit(...)`로 교체:
```python
from common.events import TraceEvent
# 존재 분기:
self._core.submit(TraceEvent(
    sha256=fp.sha256, fuzzy_hash=fp.fuzzy_hash, size=fp.size, name=path.name,
    event_type=event_type, host=self._host, user=None,
    source_hint=source_hint_for(task.path), metadata=None))
# 삭제 분기도 동일 형태(cached.* 사용, event_type=EVENT_DELETED)
```
`Worker.__init__`에 `host`가 필요하므로 `import socket`로 `self._host = socket.gethostname()` 추가(또는 인자 주입). 단순화를 위해 생성자에서 `self._host = socket.gethostname()`.

`client/agent/watcher.py`: `build_watcher(..., sender, ...)` → `build_watcher(..., core, ...)`, 내부 `Worker(cache, sender)` → `Worker(cache, core)`.

`client/main.py`:
```python
"""Python 에이전트 호스트 진입점: 한 프로세스에서 코어 + FS agent + 커넥터 intake를 띄운다.

실행(사용자 확인 후):
  Set-Location client
  ..\\server\\.venv\\Scripts\\python.exe -m main config.toml
"""

import getpass
import logging
import socket
import threading
import time
import tomllib
from pathlib import Path

from agent.cache import FingerprintCache
from agent.config import load_config
from agent.scanner import initial_scan
from agent.watcher import build_watcher
from core.core import CollectorCore
from core.sender import Sender
from connector.agent import serve as serve_connector

logger = logging.getLogger("host")
_STATE_DIR = Path(__file__).resolve().parent / ".state"


def main(config_path: str) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config(Path(config_path))
    _STATE_DIR.mkdir(exist_ok=True)
    cache = FingerprintCache(_STATE_DIR / "cache.db")

    sender = Sender(config.server_url, host=socket.gethostname(), user=getpass.getuser())
    core = CollectorCore(sender)
    core.start()

    initial_scan(config.watch_paths, config.ignore_globs, cache)
    watcher = build_watcher(
        watch_paths=config.watch_paths, ignore_globs=config.ignore_globs,
        cache=cache, core=core, debounce_seconds=config.debounce_seconds)
    watcher.start()

    intake_port = 8765
    httpd = serve_connector(core, host=socket.gethostname(), port=intake_port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("호스트 시작: FS 감시 + 커넥터 intake(:%s)", intake_port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("종료 중...")
    finally:
        httpd.shutdown()
        watcher.stop()
        core.stop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python -m main <config.toml>")
        sys.exit(1)
    main(sys.argv[1])
```
구 `client/agent/main.py`는 삭제(`git rm`) — 진입점이 `client/main.py`로 통합됨.

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest -v` (client 전체) → 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git rm client/agent/main.py
git add client/agent/worker.py client/agent/watcher.py client/main.py client/tests/test_worker.py client/tests/test_watcher.py
git commit -m "refactor: FS agent를 코어 경유로 이주, 단일 호스트 진입점"
```

---

## Task 12: 대시보드 url 표시 (static/index.html)

**Files:**
- Modify: `server/app/static/index.html`(event 표에 목적지 컬럼)
- Modify: `server/tests/test_static.py`

- [ ] **Step 1: 실패 테스트**

`server/tests/test_static.py`에 추가:
```python
def test_index_has_destination_column() -> None:
    from fastapi.testclient import TestClient
    from app.api import build_app
    from app.repository import SqliteRepository
    client = TestClient(build_app(SqliteRepository(":memory:")))
    text = client.get("/").text.lower()
    assert "목적지" in text or "destination" in text or "url" in text
```

- [ ] **Step 2: 실패 확인**

Run: `… -m pytest tests/test_static.py -v` → FAIL

- [ ] **Step 3: 구현**

`server/app/static/index.html`의 events 표 헤더에 `<th>목적지</th>` 추가(최고매칭 앞), 렌더 JS의 event 행에 url 셀 추가:
```javascript
// thead: <th>host</th><th>목적지</th><th>최고매칭</th>...
// 행 렌더:
return `<tr><td>${ev.id}</td><td>${ev.event_type}</td><td>${ev.name}</td>` +
       `<td>${ev.host || '-'}</td><td>${ev.url || '-'}</td><td>${bm}</td><td>${ev.detected_at}</td></tr>`;
```

- [ ] **Step 4: 통과 확인**

Run: `… -m pytest -v` (server 전체) → 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add server/app/static/index.html server/tests/test_static.py
git commit -m "feat: 대시보드 event 표에 목적지 url 컬럼"
```

---

## Task 13: C++ 브리지 + Chrome 정책 셋업 (수동 E2E — 자동 테스트 없음)

content_analysis_sdk 데모 에이전트를 fork해 "받으면 즉시 ALLOW + loopback POST"만 하도록 최소 개조한다. 자동 테스트 대상 아님(앞 Task들이 실 Chrome 없이 파이프라인을 이미 검증).

**Files:**
- Create: `client/connector/bridge/`(SDK clone 후 데모 기반 수정), `client/connector/README.md`

- [ ] **Step 1: SDK 가져오기 + 빌드 환경**

`client/connector/bridge/`에 `chromium/content_analysis_sdk`를 clone하고 README대로 CMake+MSVC로 데모 에이전트를 빌드해 동작 확인(`demo/agent`가 Chrome 없이도 빌드되는지).

- [ ] **Step 2: 데모 에이전트 최소 개조**

데모 에이전트의 요청 핸들러에서: (a) 응답을 **항상 ALLOW**(REPORT_ONLY)로 즉시 반환, (b) `ContentAnalysisRequest`에서 `analysis_connector`·`request_data.filename`·`url`·`digest`·`file_path`(또는 text_content)·`email`·`tab_title`을 뽑아 §5.1 JSON으로 `http://127.0.0.1:8765/event`에 비동기 POST(전달 실패는 로그만, Chrome 응답을 막지 않음).

- [ ] **Step 3: Chrome 정책 셋업 문서**

`client/connector/README.md`에 작성: `HKLM\SOFTWARE\Policies\Google\Chrome\`에 `OnFileAttachedEnterpriseConnector`·`OnFileDownloadedEnterpriseConnector`·`OnBulkDataEntryEnterpriseConnector` 정책 JSON 예시(`service_provider`=로컬 에이전트명, 파이프명 일치, `default_action=allow`), 브리지 실행법, 호스트(`client/main.py`)·서버 기동 순서.

- [ ] **Step 4: 수동 E2E (⚠ 사용자 확인 후)**

1. 서버 기동: `Set-Location server; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`
2. 호스트 기동: `Set-Location client; ..\server\.venv\Scripts\python.exe -m main <config.toml>`
3. 브리지 실행 + Chrome 정책 적용된 상태에서, 테스트 사이트(예: drive.google.com)에 파일 업로드.
4. `http://127.0.0.1:8000/` event 표에 `upload` + 목적지 url + (baseline 등록돼 있으면) 매칭이 뜨는지 확인.

- [ ] **Step 5: 커밋**

```bash
git add client/connector/bridge client/connector/README.md
git commit -m "feat: C++ 브리지(ALLOW+loopback)와 Chrome 정책 셋업 문서"
```

---

## Self-Review (작성자 점검)

**Spec 커버리지:**
- §3 2프로세스·데이터흐름 → Task 7·9·10·11(코어·커넥터·호스트) ✔
- §4 모듈 구조·공유 추출 → Task 1(common/·core/ 이동), Task 2(events) ✔
- §5 이벤트 구조화(홉1 raw·TraceEvent·매핑·metadata) → Task 2·8·9 ✔
- §5.3 paste name="(pasted text)" → Task 8 매핑 ✔
- §6 지문(파일/ paste/ 폴백) → Task 9 `_fingerprint` ✔
- §7 서버(web_event_detail·metadata·체인·GET) → Task 3·4·5·6 ✔
- §7.3 체인에 url 포함·변조탐지 → Task 4 ✔
- §8 에러 처리(파일 잠김 폴백·매핑 드롭·코어 예외·재시도) → Task 9·7·1 ✔
- §9 테스트(실 Chrome 비의존 E2E·정책 셋업) → Task 10·13 ✔
- §10 살아남은 우려 → 문서화(설계 §10), 무손실 아님은 Task 8·9 로깅으로 표면화 ✔
- §11 구현 순서 9단계 → Task 1~13으로 세분(공유추출·서버4분할·코어·매핑·에이전트·이주·대시보드·브리지) ✔

**Placeholder 스캔:** 없음. 모든 코드 단계에 실제 코드. Task 13(C++)만 SDK 의존이라 단계 서술형(자동 테스트 대상 아님 명시).

**타입 일관성:** `TraceEvent`(9필드) 정의(Task 2)와 사용처(Task 7·8·9·11) 일치. `Sender.send`(user·metadata 추가, Task 1)와 호출(core Task 7, sender 직접 안 씀) 일치. `to_trace_event(req, fp, host)`(Task 8)와 호출(Task 9) 일치. `EventInput.metadata`(Task 3)·`add_web_event_detail`(Task 5)·api 라우팅(Task 6) 필드명 일치. `CachedFingerprint`는 Task 1에서 `common/fingerprint.py`로 단일화(agent.models 재노출).

**알려진 주의점:** Task 10 통합 테스트는 `CollectorCore`를 start해 워커 스레드로 전송하므로 폴링으로 완료를 기다린다(결정성). Task 11은 FS agent의 직접 전송을 코어로 바꾸는 리팩터링이라 기존 worker/watcher 테스트를 FakeCore로 갱신(그린 유지가 합격 기준). Task 13 C++는 MSVC/CMake 필요 — 앞 Task들이 실 Chrome 없이 검증을 끝내 두므로 여기서 막혀도 Python 파이프라인은 완성·검증 상태.
```
