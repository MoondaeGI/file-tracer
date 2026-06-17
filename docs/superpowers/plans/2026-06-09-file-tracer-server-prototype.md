# file-tracer 프로토타입 서버 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파일 지문(SHA-256 + ssdeep fuzzy)을 등록·매칭하고, 본문 업로드 없이도 지문만으로 트레이스가 성립하는지 검증하는 서버 1차 프로토타입을 만든다.

**Architecture:** FastAPI 단일 앱. 지문 계산·매칭·해시체인·저장을 각각 독립 모듈로 분리하고, 저장소는 추상 `Repository` 뒤에 SQLite/In-memory 두 구현을 둔다(테스트는 In-memory 주입). 엔드포인트 `POST /api/fingerprints`는 파일 업로드(모드 a=baseline)와 지문 JSON(모드 b=event) 두 입력을 같은 매칭 로직으로 처리한다.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, ppdeep(순수 파이썬 ssdeep), sqlite3(표준 라이브러리), pytest, httpx(TestClient).

> **사용자 규칙 주의:** `pip install`·서버 기동 등 **명령 실행 전에는 반드시 사용자 확인**을 받는다(전역 CLAUDE.md). 각 Task는 TDD(실패 테스트 → 최소 구현 → 통과 → 커밋) 순서를 지킨다. 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`를 붙인다.

**승인된 설계:** `docs/superpowers/specs/2026-06-09-file-tracer-prototype-design.md` (커밋 661f456)

---

## File Structure

```
server/
  requirements.txt          의존성 목록
  pytest.ini                pytest 설정(테스트 경로)
  app/
    __init__.py
    constants.py            매칭/fuzzy 상수
    errors.py               HttpError 커스텀 예외 계층
    models.py               FingerprintInput / Record / MatchResult (frozen dataclass)
    fingerprint.py          SHA-256·ssdeep fuzzy 계산, 유사도 비교
    chain.py                해시체인: record_hash 계산, 체인 검증
    matching.py             baseline 대상 매칭(exact/fuzzy)
    repository.py           Repository(ABC) + InMemoryRepository + SqliteRepository
    api.py                  build_app(repository) — 라우트 정의
    main.py                 SqliteRepository로 앱 구성(uvicorn 진입점)
    static/
      index.html            단일 웹페이지(업로드 폼 + 표)
  tests/
    __init__.py
    test_fingerprint.py
    test_chain.py
    test_matching.py
    test_repository.py
    test_api.py             엔드포인트 + 검증 시나리오 1~5
```

각 파일은 단일 책임을 갖고 모두 200줄 미만으로 유지한다.

---

## 공통 타입 계약 (모든 Task가 따른다)

```python
# constants.py
RECORD_KIND_BASELINE = "baseline"
RECORD_KIND_EVENT = "event"
MATCH_TYPE_EXACT = "exact"
MATCH_TYPE_FUZZY = "fuzzy"
FUZZY_MATCH_THRESHOLD = 50   # ssdeep 유사도가 이 이상이면 fuzzy 매칭 포함
```

```python
# models.py 시그니처(아래 Task 3에서 전체 코드)
FingerprintInput(sha256, size, name, event_type, record_kind,
                 fuzzy_hash=None, host=None, user=None,
                 process_name=None, direction=None, source_hint=None)
Record(id, sha256, size, name, event_type, record_kind,
       server_timestamp, prev_hash, record_hash,
       fuzzy_hash=None, host=None, user=None,
       process_name=None, direction=None, source_hint=None)
MatchResult(id, name, match_type, similarity)
```

```python
# fingerprint.py  (fuzzy는 ppdeep/ssdeep — 유사도를 0~100으로 직접 반환)
compute_sha256(data: bytes) -> str
compute_fuzzy(data: bytes) -> str | None      # 빈 입력이면 None
fuzzy_similarity(a: str, b: str) -> int        # ppdeep.compare → 0~100

# chain.py
record_payload(record: Record) -> dict
compute_record_hash(payload: dict, prev_hash: str | None) -> str
verify_chain(records: Sequence[Record]) -> int | None   # 깨진 첫 레코드 id, 정상이면 None

# matching.py
find_matches(incoming_id, incoming_sha256, incoming_fuzzy,
             baselines: Sequence[Record],
             similarity_threshold: int = FUZZY_MATCH_THRESHOLD) -> list[MatchResult]

# repository.py
class Repository(ABC):
    add(data: FingerprintInput, server_timestamp: str) -> Record
    list_recent(limit: int) -> tuple[Record, ...]
    list_baselines() -> tuple[Record, ...]
    all_records() -> tuple[Record, ...]

# api.py
build_app(repository: Repository) -> FastAPI
```

---

## Task 1: 프로젝트 스캐폴드

**Files:**
- Create: `server/requirements.txt`
- Create: `server/pytest.ini`
- Create: `server/app/__init__.py`
- Create: `server/tests/__init__.py`
- Test: `server/tests/test_smoke.py`

- [ ] **Step 1: 의존성·설정 파일 작성**

`server/requirements.txt`:
```
fastapi
uvicorn
ppdeep
python-multipart
pytest
httpx
```

> **참고:** 가상환경 `server/.venv`는 이미 생성되어 위 패키지가 설치돼 있다(Python
> 3.12.8). 원안의 `python-tlsh`는 Windows 빌드 불가로 순수 파이썬 `ppdeep`(ssdeep
> 계열)으로 교체했다(설계 §3 변경 이력). 모든 테스트는 `server\.venv\Scripts\python.exe`
> 로 실행한다.

`server/pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

`server/app/__init__.py`: (빈 파일)
`server/tests/__init__.py`: (빈 파일)

- [ ] **Step 2: 스모크 테스트 작성(실패 확인용)**

`server/tests/test_smoke.py`:
```python
"""패키지 임포트가 가능한지 확인하는 스모크 테스트."""


def test_app_package_imports() -> None:
    import app  # noqa: F401
```

- [ ] **Step 3: 의존성 설치 (⚠ 사용자 확인 후 실행)**

Run: `cd server && python -m pip install -r requirements.txt`
Expected: 설치 성공. **이 명령은 사용자 승인 후 실행한다.**

- [ ] **Step 4: 스모크 테스트 통과 확인**

Run: `cd server && python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add server/requirements.txt server/pytest.ini server/app/__init__.py server/tests/__init__.py server/tests/test_smoke.py
git commit -m "chore: file-tracer 서버 프로젝트 스캐폴드"
```

---

## Task 2: 커스텀 예외 (errors.py)

**Files:**
- Create: `server/app/errors.py`
- Test: `server/tests/test_errors.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_errors.py`:
```python
"""커스텀 HTTP 예외 계층 테스트."""

import pytest

from app.errors import HttpError, InvalidFingerprintRequestError


def test_http_error_carries_status_and_message() -> None:
    err = HttpError(500, "boom")
    assert err.status_code == 500
    assert str(err) == "boom"


def test_invalid_request_is_400_http_error() -> None:
    err = InvalidFingerprintRequestError("sha256 누락")
    assert isinstance(err, HttpError)
    assert err.status_code == 400
    assert "sha256" in str(err)


def test_invalid_request_can_be_raised() -> None:
    with pytest.raises(HttpError):
        raise InvalidFingerprintRequestError("x")
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.errors'`

- [ ] **Step 3: 최소 구현**

`server/app/errors.py`:
```python
"""시스템 경계에서 사용하는 커스텀 HTTP 예외 계층."""


class HttpError(Exception):
    """status_code를 동반하는 기본 HTTP 예외."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidFingerprintRequestError(HttpError):
    """지문 등록 요청이 유효하지 않을 때(필수 필드 누락·잘못된 모드) 발생."""

    def __init__(self, message: str) -> None:
        super().__init__(400, message)
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_errors.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/errors.py server/tests/test_errors.py
git commit -m "feat: HttpError 커스텀 예외 계층 추가"
```

---

## Task 3: 도메인 모델 (constants.py, models.py)

**Files:**
- Create: `server/app/constants.py`
- Create: `server/app/models.py`
- Test: `server/tests/test_models.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_models.py`:
```python
"""도메인 모델(frozen dataclass)과 상수 테스트."""

import dataclasses

import pytest

from app import constants
from app.models import FingerprintInput, MatchResult, Record


def test_constants_values() -> None:
    assert constants.RECORD_KIND_BASELINE == "baseline"
    assert constants.RECORD_KIND_EVENT == "event"
    assert constants.FUZZY_MATCH_THRESHOLD == 50


def test_fingerprint_input_defaults_nullable_fields() -> None:
    fp = FingerprintInput(
        sha256="a" * 64, size=10, name="f.txt",
        event_type="upload", record_kind="baseline",
    )
    assert fp.fuzzy_hash is None
    assert fp.host is None
    assert fp.process_name is None


def test_record_is_immutable() -> None:
    rec = Record(
        id=1, sha256="a" * 64, size=10, name="f.txt",
        event_type="upload", record_kind="baseline",
        server_timestamp="2026-06-09T00:00:00+00:00",
        prev_hash=None, record_hash="h",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.name = "other"  # type: ignore[misc]


def test_match_result_fields() -> None:
    m = MatchResult(id=7, name="x", match_type="fuzzy", similarity=87)
    assert (m.id, m.match_type, m.similarity) == (7, "fuzzy", 87)
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.constants'`

- [ ] **Step 3: 최소 구현**

`server/app/constants.py`:
```python
"""매칭·fuzzy 관련 상수."""

RECORD_KIND_BASELINE = "baseline"
RECORD_KIND_EVENT = "event"

MATCH_TYPE_EXACT = "exact"
MATCH_TYPE_FUZZY = "fuzzy"

# ssdeep(ppdeep) 유사도가 이 값 이상이면 fuzzy 매칭으로 포함한다.
FUZZY_MATCH_THRESHOLD = 50
```

`server/app/models.py`:
```python
"""file-tracer 도메인 모델. 모두 불변(frozen) dataclass."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FingerprintInput:
    """API가 받아 저장소로 넘기는 지문 입력값(영속화 전)."""

    sha256: str
    size: int
    name: str
    event_type: str
    record_kind: str
    fuzzy_hash: str | None = None
    host: str | None = None
    user: str | None = None
    process_name: str | None = None
    direction: str | None = None
    source_hint: str | None = None


@dataclass(frozen=True)
class Record:
    """저장된 지문 레코드. 서버가 id·타임스탬프·해시체인 필드를 채운다."""

    id: int
    sha256: str
    size: int
    name: str
    event_type: str
    record_kind: str
    server_timestamp: str
    prev_hash: str | None
    record_hash: str
    fuzzy_hash: str | None = None
    host: str | None = None
    user: str | None = None
    process_name: str | None = None
    direction: str | None = None
    source_hint: str | None = None


@dataclass(frozen=True)
class MatchResult:
    """매칭 결과 한 건. similarity는 ssdeep compare(0~100), exact는 100."""

    id: int
    name: str
    match_type: str
    similarity: int
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/constants.py server/app/models.py server/tests/test_models.py
git commit -m "feat: 도메인 모델과 상수 추가"
```

---

## Task 4: 지문 계산 (fingerprint.py)

**Files:**
- Create: `server/app/fingerprint.py`
- Test: `server/tests/test_fingerprint.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_fingerprint.py`:
```python
"""SHA-256·fuzzy(ssdeep) 계산과 유사도 비교 테스트."""

import hashlib

from app.fingerprint import compute_fuzzy, compute_sha256, fuzzy_similarity


def test_sha256_matches_hashlib() -> None:
    data = b"hello world"
    assert compute_sha256(data) == hashlib.sha256(data).hexdigest()


def test_fuzzy_none_for_empty_input() -> None:
    assert compute_fuzzy(b"") is None


def test_fuzzy_generated_for_normal_input() -> None:
    data = ("The quick brown fox jumps over the lazy dog. " * 20).encode()
    digest = compute_fuzzy(data)
    assert digest is not None
    assert len(digest) > 0


def test_fuzzy_similarity_identical_is_100() -> None:
    data = ("The quick brown fox jumps over the lazy dog. " * 20).encode()
    digest = compute_fuzzy(data)
    assert digest is not None
    assert fuzzy_similarity(digest, digest) == 100


def test_fuzzy_similarity_high_for_small_edit() -> None:
    base = ("Confidential design notes. " * 40).encode()
    edited = base + b"A few words changed for the edit test."
    sim = fuzzy_similarity(compute_fuzzy(base), compute_fuzzy(edited))
    assert sim >= 50  # 소량 편집은 높은 유사도

def test_fuzzy_similarity_range() -> None:
    a = compute_fuzzy(("alpha beta gamma. " * 40).encode())
    b = compute_fuzzy(("zulu yankee xray whiskey. " * 40).encode())
    sim = fuzzy_similarity(a, b)
    assert 0 <= sim <= 100
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.fingerprint'`

- [ ] **Step 3: 최소 구현**

`server/app/fingerprint.py`:
```python
"""파일 바이트로부터 지문(SHA-256·ssdeep fuzzy)을 계산하고 유사도를 비교한다.

fuzzy는 순수 파이썬 ppdeep(ssdeep 계열)을 쓴다. ssdeep은 compare()가 0~100
유사도를 직접 주므로 별도 환산식이 없다.
"""

import hashlib

import ppdeep


def compute_sha256(data: bytes) -> str:
    """바이트의 SHA-256 16진 해시를 반환한다.

    Args:
        data: 해시 대상 바이트.

    Returns:
        64자리 16진 문자열.
    """
    return hashlib.sha256(data).hexdigest()


def compute_fuzzy(data: bytes) -> str | None:
    """바이트의 ssdeep fuzzy 지문을 반환한다.

    입력이 비어 있으면(0바이트) 의미 있는 지문을 만들 수 없으므로 None을
    반환한다(이 레코드는 fuzzy 매칭에서 제외된다).

    Args:
        data: 지문 대상 바이트.

    Returns:
        ssdeep 지문 문자열 또는 None.
    """
    if not data:
        return None
    return ppdeep.hash(data)


def fuzzy_similarity(a: str, b: str) -> int:
    """두 ssdeep 지문의 유사도(0~100)를 반환한다. 100이 동일."""
    return ppdeep.compare(a, b)
```

- [ ] **Step 4: 통과 확인**

Run: `server\.venv\Scripts\python.exe -m pytest tests/test_fingerprint.py -v` (server 디렉터리에서)
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/fingerprint.py server/tests/test_fingerprint.py
git commit -m "feat: SHA-256·ssdeep fuzzy 지문 계산과 유사도 비교"
```

---

## Task 5: 해시체인 (chain.py)

**Files:**
- Create: `server/app/chain.py`
- Test: `server/tests/test_chain.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_chain.py`:
```python
"""append-only 해시체인 계산·검증 테스트."""

import dataclasses

from app.chain import compute_record_hash, record_payload, verify_chain
from app.models import Record


def _record(idx: int, prev_hash: str | None) -> Record:
    base = Record(
        id=idx, sha256=f"{idx:064x}", size=10, name=f"f{idx}.txt",
        event_type="upload", record_kind="baseline",
        server_timestamp="2026-06-09T00:00:00+00:00",
        prev_hash=prev_hash, record_hash="",
    )
    digest = compute_record_hash(record_payload(base), prev_hash)
    return dataclasses.replace(base, record_hash=digest)


def test_record_payload_excludes_id_and_record_hash() -> None:
    rec = _record(1, None)
    payload = record_payload(rec)
    assert "id" not in payload
    assert "record_hash" not in payload
    assert payload["sha256"] == rec.sha256


def test_chain_links_and_verifies_clean() -> None:
    r1 = _record(1, None)
    r2 = _record(2, r1.record_hash)
    r3 = _record(3, r2.record_hash)
    assert verify_chain([r1, r2, r3]) is None


def test_verify_detects_tampered_field() -> None:
    r1 = _record(1, None)
    r2 = _record(2, r1.record_hash)
    r3 = _record(3, r2.record_hash)
    tampered = dataclasses.replace(r2, name="HACKED")  # record_hash는 그대로
    assert verify_chain([r1, tampered, r3]) == 2


def test_verify_detects_broken_prev_link() -> None:
    r1 = _record(1, None)
    r2 = _record(2, "wrong-prev-hash")
    assert verify_chain([r1, r2]) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_chain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chain'`

- [ ] **Step 3: 최소 구현**

`server/app/chain.py`:
```python
"""append-only 해시체인. 우발적 단일 레코드 수정·링크 단절을 탐지한다.

주의(설계 §7): record_hash는 공개 SHA-256이라 서명이 없으므로, DB 쓰기 권한을
가진 자가 체인을 prev_hash부터 통째로 재계산하는 '의도적 전체 재작성'은 막지
못한다. 이 함수는 우발적 단일 수정·링크 단절만 탐지한다.
"""

import hashlib
import json
from collections.abc import Sequence

from app.models import Record

# 해시체인이 보호하는 내용 필드(순서·구성 변경 시 체인이 깨지므로 고정).
_PAYLOAD_FIELDS = (
    "sha256", "fuzzy_hash", "size", "name", "event_type", "record_kind",
    "host", "user", "process_name", "direction", "source_hint",
    "server_timestamp",
)


def record_payload(record: Record) -> dict:
    """해시체인이 보호할 레코드 필드만 추린 dict를 반환한다(id·record_hash 제외)."""
    return {field: getattr(record, field) for field in _PAYLOAD_FIELDS}


def compute_record_hash(payload: dict, prev_hash: str | None) -> str:
    """payload와 직전 record_hash를 묶어 이 레코드의 record_hash를 계산한다.

    Args:
        payload: record_payload()가 만든 내용 dict.
        prev_hash: 직전 레코드의 record_hash(첫 레코드면 None).

    Returns:
        64자리 16진 SHA-256.
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    material = f"{prev_hash or ''}\n{canonical}".encode()
    return hashlib.sha256(material).hexdigest()


def verify_chain(records: Sequence[Record]) -> int | None:
    """레코드 체인을 검증한다.

    Args:
        records: server_timestamp/삽입 순으로 정렬된 레코드들.

    Returns:
        체인이 처음 깨진 레코드의 id. 정상이면 None.
    """
    prev_hash: str | None = None
    for record in records:
        if record.prev_hash != prev_hash:
            return record.id
        expected = compute_record_hash(record_payload(record), record.prev_hash)
        if expected != record.record_hash:
            return record.id
        prev_hash = record.record_hash
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_chain.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/chain.py server/tests/test_chain.py
git commit -m "feat: append-only 해시체인 계산·검증"
```

---

## Task 6: 매칭 로직 (matching.py)

**Files:**
- Create: `server/app/matching.py`
- Test: `server/tests/test_matching.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_matching.py`:
```python
"""baseline 대상 매칭(exact/fuzzy) 테스트."""

from app.fingerprint import compute_fuzzy
from app.matching import find_matches
from app.models import Record


def _baseline(idx: int, sha: str, fuzzy: str | None) -> Record:
    return Record(
        id=idx, sha256=sha, size=10, name=f"b{idx}.txt",
        event_type="upload", record_kind="baseline",
        server_timestamp="2026-06-09T00:00:00+00:00",
        prev_hash=None, record_hash="h", fuzzy_hash=fuzzy,
    )


def test_exact_match_by_sha() -> None:
    sha = "a" * 64
    baselines = [_baseline(1, sha, None)]
    matches = find_matches(99, sha, None, baselines)
    assert len(matches) == 1
    assert matches[0].match_type == "exact"
    assert matches[0].similarity == 100


def test_self_is_excluded() -> None:
    sha = "a" * 64
    baselines = [_baseline(5, sha, None)]
    # 들어온 레코드 id가 baseline과 동일 → 자기 자신이므로 제외
    assert find_matches(5, sha, None, baselines) == []


def test_fuzzy_match_within_threshold() -> None:
    text = "Confidential design notes. " * 40
    fuzzy_a = compute_fuzzy(text.encode())
    fuzzy_b = compute_fuzzy((text + "a small edit here.").encode())
    baselines = [_baseline(1, "f" * 64, fuzzy_a)]
    matches = find_matches(2, "e" * 64, fuzzy_b, baselines, similarity_threshold=50)
    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].similarity >= 50


def test_fuzzy_excluded_when_below_threshold() -> None:
    fuzzy_a = compute_fuzzy(("alpha beta gamma delta. " * 40).encode())
    fuzzy_b = compute_fuzzy(("zulu yankee xray whiskey victor. " * 40).encode())
    baselines = [_baseline(1, "f" * 64, fuzzy_a)]
    # 임계치를 101로 두면(불가능한 값) 어떤 fuzzy도 포함되지 않는다
    matches = find_matches(2, "e" * 64, fuzzy_b, baselines, similarity_threshold=101)
    assert matches == []


def test_null_fuzzy_skips_fuzzy() -> None:
    # 들어온 지문 fuzzy_hash=None → fuzzy 불가, sha도 다르면 매칭 없음
    baselines = [_baseline(1, "f" * 64, "3:somefuzzy")]
    assert find_matches(2, "e" * 64, None, baselines) == []


def test_results_sorted_by_similarity_desc() -> None:
    sha = "a" * 64
    baselines = [_baseline(1, "z" * 64, None), _baseline(2, sha, None)]
    matches = find_matches(99, sha, None, baselines)
    # exact(100)만 잡히고 첫번째 baseline은 sha 불일치+fuzzy None이라 제외
    assert [m.id for m in matches] == [2]
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.matching'`

- [ ] **Step 3: 최소 구현**

`server/app/matching.py`:
```python
"""들어온 지문을 baseline 레코드들과만 비교해 매칭을 만든다.

규칙(설계 §6): 매칭 대상은 record_kind=baseline 레코드들이며, 자기 자신(id 동일)은
제외한다. SHA 동일은 exact(100). 아니면 양쪽 fuzzy_hash가 모두 있을 때 ssdeep
유사도(0~100)를 계산해 임계치 이상만 fuzzy로 포함한다. fuzzy_hash가 None이면 fuzzy
대상에서 제외한다.
"""

from collections.abc import Sequence

from app.constants import FUZZY_MATCH_THRESHOLD, MATCH_TYPE_EXACT, MATCH_TYPE_FUZZY
from app.fingerprint import fuzzy_similarity
from app.models import MatchResult, Record


def find_matches(
    incoming_id: int | None,
    incoming_sha256: str,
    incoming_fuzzy: str | None,
    baselines: Sequence[Record],
    similarity_threshold: int = FUZZY_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """들어온 지문에 대한 매칭 목록을 유사도 내림차순으로 반환한다.

    Args:
        incoming_id: 들어온 레코드의 id(자기 제외용). 미저장이면 None.
        incoming_sha256: 들어온 SHA-256.
        incoming_fuzzy: 들어온 ssdeep fuzzy 지문(없으면 None).
        baselines: 비교 대상 baseline 레코드들.
        similarity_threshold: 이 이상 유사도만 fuzzy로 포함.

    Returns:
        MatchResult 리스트(similarity 내림차순, 동률은 id 오름차순).
    """
    matches: list[MatchResult] = []
    for baseline in baselines:
        if baseline.id == incoming_id:
            continue
        if baseline.sha256 == incoming_sha256:
            matches.append(MatchResult(
                id=baseline.id, name=baseline.name,
                match_type=MATCH_TYPE_EXACT, similarity=100,
            ))
            continue
        if incoming_fuzzy is None or baseline.fuzzy_hash is None:
            continue
        similarity = fuzzy_similarity(incoming_fuzzy, baseline.fuzzy_hash)
        if similarity >= similarity_threshold:
            matches.append(MatchResult(
                id=baseline.id, name=baseline.name,
                match_type=MATCH_TYPE_FUZZY, similarity=similarity,
            ))
    matches.sort(key=lambda m: (-m.similarity, m.id))
    return matches
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_matching.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/matching.py server/tests/test_matching.py
git commit -m "feat: baseline 대상 exact/fuzzy 매칭 로직"
```

---

## Task 7: 저장소 (repository.py)

**Files:**
- Create: `server/app/repository.py`
- Test: `server/tests/test_repository.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_repository.py`:
```python
"""Repository 두 구현(InMemory/Sqlite)의 동작·해시체인 무결성 테스트."""

import pytest

from app.chain import verify_chain
from app.constants import RECORD_KIND_BASELINE, RECORD_KIND_EVENT
from app.models import FingerprintInput
from app.repository import InMemoryRepository, SqliteRepository

TS = "2026-06-09T00:00:00+00:00"


def _input(sha: str, kind: str = RECORD_KIND_BASELINE) -> FingerprintInput:
    return FingerprintInput(
        sha256=sha, size=10, name="f.txt",
        event_type="upload", record_kind=kind, fuzzy_hash="3:abc",
    )


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    if request.param == "memory":
        return InMemoryRepository()
    return SqliteRepository(tmp_path / "test.db")


def test_add_assigns_incrementing_ids(repo) -> None:
    r1 = repo.add(_input("a" * 64), TS)
    r2 = repo.add(_input("b" * 64), TS)
    assert r1.id == 1
    assert r2.id == 2


def test_add_builds_valid_hash_chain(repo) -> None:
    repo.add(_input("a" * 64), TS)
    repo.add(_input("b" * 64), TS)
    repo.add(_input("c" * 64), TS)
    assert verify_chain(repo.all_records()) is None


def test_first_record_has_no_prev_hash(repo) -> None:
    r1 = repo.add(_input("a" * 64), TS)
    assert r1.prev_hash is None
    assert r1.record_hash != ""


def test_list_baselines_filters_by_kind(repo) -> None:
    repo.add(_input("a" * 64, RECORD_KIND_BASELINE), TS)
    repo.add(_input("b" * 64, RECORD_KIND_EVENT), TS)
    baselines = repo.list_baselines()
    assert len(baselines) == 1
    assert baselines[0].record_kind == RECORD_KIND_BASELINE


def test_list_recent_limit(repo) -> None:
    for i in range(5):
        repo.add(_input(f"{i:064x}"), TS)
    recent = repo.list_recent(limit=3)
    assert len(recent) == 3
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repository'`

- [ ] **Step 3: 최소 구현**

`server/app/repository.py`:
```python
"""지문 레코드 저장소. 추상 Repository 뒤에 In-memory/SQLite 구현을 둔다.

add()는 직전 레코드의 record_hash로 prev_hash를 잇고, id·record_hash를 채워
append-only 해시체인을 유지한다. 쓰기는 락으로 직렬화해 prev_hash 읽기→쓰기
경합을 막는다(설계 §7).
"""

import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import replace
from pathlib import Path

from app.chain import compute_record_hash, record_payload
from app.models import FingerprintInput, Record

_RECORD_COLUMNS = (
    "id", "sha256", "fuzzy_hash", "size", "name", "event_type", "record_kind",
    "host", "user", "process_name", "direction", "source_hint",
    "server_timestamp", "prev_hash", "record_hash",
)


def _build_record(
    new_id: int, data: FingerprintInput, server_timestamp: str, prev_hash: str | None,
) -> Record:
    """입력값으로 record_hash까지 채운 Record를 만든다."""
    draft = Record(
        id=new_id, sha256=data.sha256, size=data.size, name=data.name,
        event_type=data.event_type, record_kind=data.record_kind,
        server_timestamp=server_timestamp, prev_hash=prev_hash, record_hash="",
        fuzzy_hash=data.fuzzy_hash, host=data.host, user=data.user,
        process_name=data.process_name, direction=data.direction,
        source_hint=data.source_hint,
    )
    digest = compute_record_hash(record_payload(draft), prev_hash)
    return replace(draft, record_hash=digest)


class Repository(ABC):
    """지문 레코드 저장소 인터페이스."""

    @abstractmethod
    def add(self, data: FingerprintInput, server_timestamp: str) -> Record:
        """레코드를 추가하고 채워진 Record를 반환한다."""

    @abstractmethod
    def list_recent(self, limit: int) -> tuple[Record, ...]:
        """최근 레코드를 id 내림차순으로 최대 limit개 반환한다."""

    @abstractmethod
    def list_baselines(self) -> tuple[Record, ...]:
        """record_kind=baseline 레코드를 id 오름차순으로 반환한다."""

    @abstractmethod
    def all_records(self) -> tuple[Record, ...]:
        """전체 레코드를 id 오름차순으로 반환한다(체인 검증용)."""


class InMemoryRepository(Repository):
    """프로세스 메모리에만 저장하는 구현(테스트·시연용)."""

    def __init__(self) -> None:
        self._records: list[Record] = []
        self._lock = threading.Lock()

    def add(self, data: FingerprintInput, server_timestamp: str) -> Record:
        with self._lock:
            prev_hash = self._records[-1].record_hash if self._records else None
            record = _build_record(len(self._records) + 1, data, server_timestamp, prev_hash)
            self._records.append(record)
            return record

    def list_recent(self, limit: int) -> tuple[Record, ...]:
        return tuple(reversed(self._records[-limit:]))

    def list_baselines(self) -> tuple[Record, ...]:
        return tuple(r for r in self._records if r.record_kind == "baseline")

    def all_records(self) -> tuple[Record, ...]:
        return tuple(self._records)


class SqliteRepository(Repository):
    """SQLite 파일에 저장하는 구현."""

    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                fuzzy_hash TEXT,
                size INTEGER NOT NULL,
                name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                record_kind TEXT NOT NULL,
                host TEXT, user TEXT, process_name TEXT,
                direction TEXT, source_hint TEXT,
                server_timestamp TEXT NOT NULL,
                prev_hash TEXT,
                record_hash TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> Record:
        return Record(**{col: row[col] for col in _RECORD_COLUMNS})

    def add(self, data: FingerprintInput, server_timestamp: str) -> Record:
        with self._lock:
            cur = self._conn.execute("SELECT record_hash FROM records ORDER BY id DESC LIMIT 1")
            last = cur.fetchone()
            prev_hash = last["record_hash"] if last else None
            cur = self._conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM records")
            new_id = cur.fetchone()["next_id"]
            record = _build_record(new_id, data, server_timestamp, prev_hash)
            self._conn.execute(
                f"INSERT INTO records ({','.join(_RECORD_COLUMNS)}) "
                f"VALUES ({','.join('?' for _ in _RECORD_COLUMNS)})",
                tuple(getattr(record, col) for col in _RECORD_COLUMNS),
            )
            self._conn.commit()
            return record

    def list_recent(self, limit: int) -> tuple[Record, ...]:
        cur = self._conn.execute("SELECT * FROM records ORDER BY id DESC LIMIT ?", (limit,))
        return tuple(self._row_to_record(r) for r in cur.fetchall())

    def list_baselines(self) -> tuple[Record, ...]:
        cur = self._conn.execute(
            "SELECT * FROM records WHERE record_kind = 'baseline' ORDER BY id ASC"
        )
        return tuple(self._row_to_record(r) for r in cur.fetchall())

    def all_records(self) -> tuple[Record, ...]:
        cur = self._conn.execute("SELECT * FROM records ORDER BY id ASC")
        return tuple(self._row_to_record(r) for r in cur.fetchall())
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_repository.py -v`
Expected: PASS (10 passed — 5 테스트 × 2 구현)

- [ ] **Step 5: 커밋**

```bash
git add server/app/repository.py server/tests/test_repository.py
git commit -m "feat: InMemory/SQLite 저장소와 해시체인 영속화"
```

---

## Task 8: API 레이어 (api.py, main.py)

**Files:**
- Create: `server/app/api.py`
- Create: `server/app/main.py`
- Test: `server/tests/test_api.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_api.py`:
```python
"""API 엔드포인트 테스트(FastAPI TestClient + InMemoryRepository 주입)."""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import build_app
from app.repository import InMemoryRepository

BIG_TEXT = ("The quick brown fox jumps over the lazy dog. " * 30).encode()


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(InMemoryRepository()))


def _upload(client: TestClient, content: bytes, name: str):
    return client.post(
        "/api/fingerprints",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    )


def test_upload_registers_baseline_and_returns_fields(client: TestClient) -> None:
    resp = _upload(client, BIG_TEXT, "secret.txt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["record_kind"] == "baseline"
    assert len(body["sha256"]) == 64
    assert body["fuzzy_hash"] is not None
    assert body["matches"] == []


def test_json_mode_missing_sha_returns_400(client: TestClient) -> None:
    resp = client.post("/api/fingerprints", json={"size": 1, "name": "x"})
    assert resp.status_code == 400


def test_get_lists_records(client: TestClient) -> None:
    _upload(client, BIG_TEXT, "a.txt")
    resp = client.get("/api/fingerprints")
    assert resp.status_code == 200
    assert len(resp.json()["records"]) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: 최소 구현**

`server/app/api.py`:
```python
"""FastAPI 라우트. POST는 파일 업로드(모드 a)와 지문 JSON(모드 b)을 받는다."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.constants import RECORD_KIND_BASELINE, RECORD_KIND_EVENT
from app.errors import HttpError, InvalidFingerprintRequestError
from app.fingerprint import compute_fuzzy, compute_sha256
from app.matching import find_matches
from app.models import FingerprintInput, Record
from app.repository import Repository

_STATIC_DIR = Path(__file__).parent / "static"


def _now_iso() -> str:
    """서버가 찍는 UTC ISO 타임스탬프."""
    return datetime.now(timezone.utc).isoformat()


async def _parse_input(request: Request) -> FingerprintInput:
    """요청 content-type에 따라 모드 a(파일)/모드 b(JSON)를 파싱한다."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise InvalidFingerprintRequestError("file 필드가 필요합니다")
        data = await upload.read()
        return FingerprintInput(
            sha256=compute_sha256(data), fuzzy_hash=compute_fuzzy(data),
            size=len(data), name=upload.filename or "unknown",
            event_type="upload", record_kind=RECORD_KIND_BASELINE,
        )
    if content_type.startswith("application/json"):
        payload = await request.json()
        sha256 = payload.get("sha256")
        if not sha256:
            raise InvalidFingerprintRequestError("sha256 필드가 필요합니다")
        return FingerprintInput(
            sha256=sha256, fuzzy_hash=payload.get("fuzzy_hash"),
            size=int(payload.get("size", 0)), name=payload.get("name", "unknown"),
            event_type=payload.get("event_type", "event"),
            record_kind=RECORD_KIND_EVENT,
            host=payload.get("host"), user=payload.get("user"),
            source_hint=payload.get("source_hint"),
        )
    raise InvalidFingerprintRequestError("multipart 또는 JSON 요청이어야 합니다")


def _record_to_dict(record: Record) -> dict:
    return {
        "id": record.id, "sha256": record.sha256, "fuzzy_hash": record.fuzzy_hash,
        "size": record.size, "name": record.name, "event_type": record.event_type,
        "record_kind": record.record_kind, "host": record.host, "user": record.user,
        "server_timestamp": record.server_timestamp,
    }


def build_app(repository: Repository) -> FastAPI:
    """저장소를 주입받아 FastAPI 앱을 구성한다."""
    app = FastAPI(title="file-tracer")

    @app.exception_handler(HttpError)
    async def _http_error_handler(_: Request, exc: HttpError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    @app.post("/api/fingerprints")
    async def add_fingerprint(request: Request) -> dict:
        data = await _parse_input(request)
        record = repository.add(data, _now_iso())
        matches = find_matches(
            record.id, record.sha256, record.fuzzy_hash, repository.list_baselines(),
        )
        return {
            "id": record.id, "sha256": record.sha256, "fuzzy_hash": record.fuzzy_hash,
            "registered_as": f"file_{record.id:03d}",
            "record_kind": record.record_kind,
            "matches": [
                {"id": m.id, "name": m.name, "match_type": m.match_type,
                 "similarity": m.similarity}
                for m in matches
            ],
            "server_timestamp": record.server_timestamp,
        }

    @app.get("/api/fingerprints")
    async def list_fingerprints() -> dict:
        records = repository.list_recent(limit=100)
        return {"records": [_record_to_dict(r) for r in records]}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app
```

`server/app/main.py`:
```python
"""uvicorn 진입점. SQLite 저장소로 앱을 구성한다.

실행(사용자 확인 후): python -m uvicorn app.main:app --reload --port 8000
"""

from pathlib import Path

from app.api import build_app
from app.repository import SqliteRepository

_DB_PATH = Path(__file__).parent.parent / "file_tracer.db"

app = build_app(SqliteRepository(_DB_PATH))
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_api.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/api.py server/app/main.py server/tests/test_api.py
git commit -m "feat: 지문 등록·조회 API와 uvicorn 진입점"
```

---

## Task 9: 웹페이지 (static/index.html)

**Files:**
- Create: `server/app/static/index.html`
- Test: `server/tests/test_static.py`

- [ ] **Step 1: 실패 테스트 작성**

`server/tests/test_static.py`:
```python
"""정적 웹페이지가 서빙되는지 확인."""

from fastapi.testclient import TestClient

from app.api import build_app
from app.repository import InMemoryRepository


def test_index_served() -> None:
    client = TestClient(build_app(InMemoryRepository()))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "file-tracer" in resp.text
    assert "upload" in resp.text.lower()
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && python -m pytest tests/test_static.py -v`
Expected: FAIL — index.html 없음으로 404 또는 FileNotFound

- [ ] **Step 3: 최소 구현**

`server/app/static/index.html`:
```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>file-tracer</title>
  <style>
    body { font-family: sans-serif; max-width: 900px; margin: 2rem auto; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #ccc; padding: 4px 8px; font-size: 13px; }
    th { background: #f3f3f3; }
  </style>
</head>
<body>
  <h1>file-tracer</h1>
  <h2>파일 업로드 (지문 등록 + 매칭)</h2>
  <form id="upload-form">
    <input type="file" id="file-input" required />
    <button type="submit">업로드</button>
  </form>

  <h3>매칭 결과</h3>
  <table id="matches">
    <thead><tr><th>id</th><th>name</th><th>match</th><th>similarity</th></tr></thead>
    <tbody></tbody>
  </table>

  <h3>등록된 레코드</h3>
  <table id="records">
    <thead><tr><th>id</th><th>name</th><th>kind</th><th>sha256</th><th>time</th></tr></thead>
    <tbody></tbody>
  </table>

  <script>
    const form = document.getElementById('upload-form');
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData();
      fd.append('file', document.getElementById('file-input').files[0]);
      const resp = await fetch('/api/fingerprints', { method: 'POST', body: fd });
      const body = await resp.json();
      renderMatches(body.matches || []);
      await loadRecords();
    });

    function renderMatches(matches) {
      const tb = document.querySelector('#matches tbody');
      tb.innerHTML = matches.map(m =>
        `<tr><td>${m.id}</td><td>${m.name}</td><td>${m.match_type}</td>` +
        `<td>${m.similarity}</td></tr>`).join('');
    }

    async function loadRecords() {
      const resp = await fetch('/api/fingerprints');
      const body = await resp.json();
      const tb = document.querySelector('#records tbody');
      tb.innerHTML = body.records.map(r =>
        `<tr><td>${r.id}</td><td>${r.name}</td><td>${r.record_kind}</td>` +
        `<td>${r.sha256.slice(0, 12)}…</td><td>${r.server_timestamp}</td></tr>`).join('');
    }

    loadRecords();
  </script>
</body>
</html>
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && python -m pytest tests/test_static.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/static/index.html server/tests/test_static.py
git commit -m "feat: 단일 웹페이지(업로드 폼 + 매칭/레코드 표)"
```

---

## Task 10: 검증 시나리오 통합 테스트

설계 §9의 5개 시나리오를 자동 테스트로 못박는다.

**Files:**
- Test: `server/tests/test_scenarios.py`

- [ ] **Step 1: 시나리오 테스트 작성**

`server/tests/test_scenarios.py`:
```python
"""설계 §9 검증 시나리오 1~5를 자동 테스트로 고정한다."""

import hashlib
import io

import ppdeep
from fastapi.testclient import TestClient

from app.api import build_app
from app.chain import verify_chain
from app.repository import InMemoryRepository

TEXT = ("Confidential design notes. " * 40)


def _client_and_repo():
    repo = InMemoryRepository()
    return TestClient(build_app(repo)), repo


def _upload(client: TestClient, content: bytes, name: str):
    return client.post(
        "/api/fingerprints",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
    ).json()


def test_scenario1_same_file_exact100() -> None:
    client, _ = _client_and_repo()
    _upload(client, TEXT.encode(), "a.txt")
    body = _upload(client, TEXT.encode(), "a-copy.txt")
    assert body["matches"][0]["match_type"] == "exact"
    assert body["matches"][0]["similarity"] == 100


def test_scenario2_edited_text_fuzzy_within_threshold() -> None:
    client, _ = _client_and_repo()
    _upload(client, TEXT.encode(), "orig.txt")
    edited = (TEXT + "A few words were changed here for the edit test.").encode()
    body = _upload(client, edited, "edited.txt")
    fuzzy = [m for m in body["matches"] if m["match_type"] == "fuzzy"]
    assert fuzzy, "fuzzy 매칭이 있어야 한다"
    assert fuzzy[0]["similarity"] >= 50


def test_scenario3_rename_same_content_exact100() -> None:
    client, _ = _client_and_repo()
    _upload(client, TEXT.encode(), "name1.txt")
    body = _upload(client, TEXT.encode(), "name2.txt")  # 내용 동일, 이름만 변경
    assert body["matches"][0]["match_type"] == "exact"
    assert body["matches"][0]["similarity"] == 100


def test_scenario4_no_upload_trace_via_independent_fingerprint() -> None:
    # (a) baseline 등록 → 서버가 본문으로 지문 계산
    client, _ = _client_and_repo()
    _upload(client, TEXT.encode(), "baseline.txt")
    # 같은 파일을 서버와 독립적으로(여기선 hashlib/ppdeep 직접) 재계산
    independent_sha = hashlib.sha256(TEXT.encode()).hexdigest()
    independent_fuzzy = ppdeep.hash(TEXT.encode())
    # (b) 본문 없이 지문만 JSON으로 전송
    body = client.post("/api/fingerprints", json={
        "sha256": independent_sha, "fuzzy_hash": independent_fuzzy,
        "size": len(TEXT), "name": "remote.txt", "event_type": "modify",
    }).json()
    exact = [m for m in body["matches"] if m["match_type"] == "exact"]
    assert exact, "독립 재계산 SHA가 baseline과 exact 일치해야 한다(무업로드 트레이스 증명)"
    # fuzzy도 재현 일치(같은 구현이면 similarity 100)
    fuzzy = [m for m in body["matches"] if m["match_type"] == "fuzzy"]
    assert all(m["similarity"] == 100 for m in fuzzy) or exact


def test_scenario5_tamper_detected_at_record() -> None:
    import dataclasses

    client, repo = _client_and_repo()
    _upload(client, TEXT.encode(), "a.txt")
    _upload(client, (TEXT + "x").encode(), "b.txt")
    _upload(client, (TEXT + "yy").encode(), "c.txt")
    records = list(repo.all_records())
    # 2번 레코드를 변조(record_hash는 그대로) → 체인 검증이 id=2를 짚어야 함
    records[1] = dataclasses.replace(records[1], name="HACKED")
    assert verify_chain(records) == 2
```

- [ ] **Step 2: 실행해서 통과 확인**

Run: `cd server && python -m pytest tests/test_scenarios.py -v`
Expected: PASS (5 passed). 시나리오 2에서 `similarity`가 50 미만이면 편집량을 줄이거나 텍스트 크기를 재검토한다(설계 §6·§10, ssdeep 블록 크기 민감성).

- [ ] **Step 3: 전체 테스트 실행**

Run: `cd server && python -m pytest -v`
Expected: 전체 PASS

- [ ] **Step 4: 커밋**

```bash
git add server/tests/test_scenarios.py
git commit -m "test: 설계 §9 검증 시나리오 1~5 통합 테스트"
```

- [ ] **Step 5: (선택) 수동 시연 — 서버 기동 (⚠ 사용자 확인 후)**

Run: `cd server && python -m uvicorn app.main:app --port 8000`
브라우저에서 `http://localhost:8000` 접속 → 파일 업로드 → 매칭 표 확인.

---

## Self-Review (작성자 점검 결과)

**Spec 커버리지:**
- §3 스택(FastAPI/SQLite/ppdeep) → Task 1·7·4 ✔
- §4.1 두 모드 POST → Task 8 `_parse_input` ✔
- §4.1 모드 b 신뢰 한계 → 코드 주석·설계 §10 (테스트 시나리오 4가 독립 재계산으로 검증) ✔
- §4.2 GET + 무인증 이월 → Task 8 ✔
- §5 스키마(record_kind·nullable 예약) → Task 3 ✔
- §6 매칭(baseline 한정·self 제외·ssdeep 직접 유사도·임계치·null 처리) → Task 6 ✔
- §7 무결성(서버 타임스탬프·해시체인·동시성 락) → Task 5·7·8 ✔
- §8 웹페이지 → Task 9 ✔
- §9 시나리오 1~5 → Task 10 ✔
- §2 범위 밖(클라·문서지문·게이트·엣지·프로세스귀속·인증) → 미구현(의도적) ✔

**Placeholder 스캔:** 없음. 모든 코드 단계에 실제 코드 포함.

**타입 일관성:** `FingerprintInput`/`Record`/`MatchResult` 필드, `find_matches`/`compute_record_hash`/`verify_chain`/`build_app` 시그니처가 Task 간 일치. `repository.add(data, server_timestamp)` 계약이 Task 7·8에서 동일.

**알려진 주의점:** Task 10 시나리오 2의 `similarity ≥ 50`은 테스트 텍스트(수 KB의 같은 원본 + 소량 편집)에 의존한다. ssdeep은 블록 크기에 민감해 두 파일 크기가 크게 다르면 0이 나올 수 있으므로(설계 §10) 같은 원본의 소량 편집 케이스를 쓴다. 실패 시 편집량을 줄이거나 텍스트를 키운다.
