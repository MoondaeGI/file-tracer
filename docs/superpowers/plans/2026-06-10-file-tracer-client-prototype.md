# file-tracer 클라이언트(에이전트) 프로토타입 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지정 폴더의 파일 이벤트(생성/수정/이동/삭제)를 감지해 지문(SHA-256 + ssdeep)을 찍어 구동 중인 서버의 `POST /api/fingerprints` 모드 b로 전송하는 백그라운드 에이전트를 만든다.

**Architecture:** watchdog가 폴더 이벤트를 잡아 → 임시파일 필터 → 경로별 디바운스로 쓰기 버스트를 합치고 → **단일 워커 큐**가 해싱·전송을 순차 처리한다. 삭제·이동은 로컬 SQLite '경로→지문' 캐시로 다룬다. 시작 시 초기 스캔으로 캐시를 채운다(전송 없음).

**Tech Stack:** Python 3.12, watchdog, httpx, ppdeep, tomllib(표준 라이브러리), sqlite3(표준), pytest.

> **사용자 규칙 주의:** 의존성 설치는 **사용자 확인 후** 실행한다(전역 CLAUDE.md). `python`은 PATH에 없으니 `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe`를 쓴다(서버 venv 공유 — httpx·ppdeep 이미 설치됨, watchdog만 추가). 명령은 PowerShell. 각 Task는 TDD. 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

**승인된 설계:** `docs/superpowers/specs/2026-06-10-file-tracer-client-prototype-design.md` (커밋 1313c49)

---

## File Structure

```
client/
  requirements.txt          watchdog, httpx, ppdeep
  config.toml               감시 설정(예시)
  pytest.ini                pythonpath = .
  agent/
    __init__.py
    errors.py               ConfigError 등 커스텀 예외
    models.py               Config / CachedFingerprint / Pending / Task (frozen dataclass)
    fingerprint.py          SHA-256 + ppdeep, raw bytes (서버와 동일 로직)
    events.py               should_ignore / source_hint_for (순수 함수)
    config.py               load_config: toml 로드·검증
    cache.py                FingerprintCache (SQLite, 스레드 안전)
    sender.py               Sender: httpx POST 모드 b, 재시도
    debouncer.py            Debouncer: 경로별 타이머(주입 가능)
    worker.py               Worker: 단일 큐 스레드, Task 처리
    scanner.py              initial_scan: 캐시만 채움(전송 없음)
    watcher.py              watchdog 핸들러 + 배선
    main.py                 진입점
  tests/
    __init__.py
    test_*.py
```

모든 파일 200줄 미만, 단일 책임.

---

## 공통 타입 계약 (모든 Task가 따른다)

```python
# models.py
@dataclass(frozen=True)
class Config:
    server_url: str
    debounce_seconds: float
    watch_paths: tuple[Path, ...]
    ignore_globs: tuple[str, ...]

@dataclass(frozen=True)
class CachedFingerprint:
    sha256: str
    fuzzy_hash: str | None
    size: int

@dataclass(frozen=True)
class Pending:
    event_type: str               # "created" | "modified" | "moved" | "deleted"
    moved_from: str | None = None

@dataclass(frozen=True)
class Task:
    path: str
    event_type: str
    moved_from: str | None = None
```

```python
# fingerprint.py
compute_sha256(data: bytes) -> str
compute_fuzzy(data: bytes) -> str | None
fingerprint_file(path: Path) -> CachedFingerprint        # read_bytes로 raw 읽어 계산

# events.py
should_ignore(path: str, ignore_globs: Sequence[str]) -> bool
source_hint_for(path: str) -> str | None

# config.py
load_config(path: Path) -> Config                         # 실패 시 ConfigError

# cache.py — FingerprintCache(db_path: Path)
.put(path: str, fp: CachedFingerprint) -> None
.get(path: str) -> CachedFingerprint | None
.pop(path: str) -> CachedFingerprint | None

# sender.py — Sender(server_url, host, user, client=None, retries=2)
.send(*, sha256, fuzzy_hash, size, name, event_type, source_hint) -> bool

# debouncer.py — Debouncer(seconds, on_fire, timer_factory=threading.Timer)
.schedule(path: str, pending: Pending) -> None
.cancel_all() -> None

# worker.py — Worker(cache, sender, fingerprint_file=fingerprint_file)
.submit(task: Task) -> None
.process(task: Task) -> None      # 동기 처리(테스트용 직접 호출 가능)
.start() -> None ; .stop() -> None

# scanner.py
initial_scan(watch_paths, ignore_globs, cache, fingerprint_file=fingerprint_file) -> int
```

상수: `EVENT_CREATED="created"`, `EVENT_MODIFIED="modified"`, `EVENT_MOVED="moved"`, `EVENT_DELETED="deleted"` (models.py).

---

## Task 1: 스캐폴드 + watchdog 설치

**Files:**
- Create: `client/requirements.txt`, `client/pytest.ini`, `client/config.toml`
- Create: `client/agent/__init__.py`, `client/tests/__init__.py`
- Test: `client/tests/test_smoke.py`

- [ ] **Step 1: 파일 작성**

`client/requirements.txt`:
```
watchdog
httpx
ppdeep
```

`client/pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
pythonpath = .
```

`client/config.toml`:
```toml
server_url = "http://127.0.0.1:8000"
debounce_seconds = 1.5
watch_paths = ["C:\\Secret"]
ignore_globs = ["~$*", "*.tmp", "*.crdownload", "*.part"]
```

`client/agent/__init__.py`: (빈 파일)
`client/tests/__init__.py`: (빈 파일)

- [ ] **Step 2: 스모크 테스트**

`client/tests/test_smoke.py`:
```python
"""패키지 임포트 스모크 테스트."""


def test_agent_package_imports() -> None:
    import agent  # noqa: F401
```

- [ ] **Step 3: watchdog 설치 (⚠ 사용자 확인 후)**

Run (PowerShell): `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pip install watchdog`
Expected: 설치 성공. **사용자 승인 후 실행.**

- [ ] **Step 4: 스모크 통과 확인**

Run (client 디렉터리에서): `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add client/requirements.txt client/pytest.ini client/config.toml client/agent/__init__.py client/tests/__init__.py client/tests/test_smoke.py
git commit -m "chore: file-tracer 클라이언트 스캐폴드"
```

---

## Task 2: 커스텀 예외 + 모델 (errors.py, models.py)

**Files:**
- Create: `client/agent/errors.py`, `client/agent/models.py`
- Test: `client/tests/test_models.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_models.py`:
```python
"""커스텀 예외와 도메인 모델 테스트."""

import dataclasses
from pathlib import Path

import pytest

from agent import models
from agent.errors import ConfigError
from agent.models import CachedFingerprint, Config, Pending, Task


def test_config_error_is_exception() -> None:
    with pytest.raises(ConfigError):
        raise ConfigError("bad")


def test_event_constants() -> None:
    assert models.EVENT_CREATED == "created"
    assert models.EVENT_MODIFIED == "modified"
    assert models.EVENT_MOVED == "moved"
    assert models.EVENT_DELETED == "deleted"


def test_config_is_frozen() -> None:
    cfg = Config(server_url="http://x", debounce_seconds=1.5,
                 watch_paths=(Path("C:/a"),), ignore_globs=("*.tmp",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.server_url = "y"  # type: ignore[misc]


def test_cached_fingerprint_and_pending_and_task() -> None:
    fp = CachedFingerprint(sha256="a" * 64, fuzzy_hash=None, size=10)
    assert fp.fuzzy_hash is None
    assert Pending(event_type="created").moved_from is None
    assert Task(path="p", event_type="moved", moved_from="q").moved_from == "q"
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.errors'`

- [ ] **Step 3: 구현**

`client/agent/errors.py`:
```python
"""클라이언트 에이전트 커스텀 예외."""


class ConfigError(Exception):
    """설정(config.toml) 로드·검증 실패."""
```

`client/agent/models.py`:
```python
"""클라이언트 도메인 모델과 이벤트 타입 상수. 모두 불변(frozen)."""

from dataclasses import dataclass
from pathlib import Path

EVENT_CREATED = "created"
EVENT_MODIFIED = "modified"
EVENT_MOVED = "moved"
EVENT_DELETED = "deleted"


@dataclass(frozen=True)
class Config:
    """검증된 에이전트 설정."""

    server_url: str
    debounce_seconds: float
    watch_paths: tuple[Path, ...]
    ignore_globs: tuple[str, ...]


@dataclass(frozen=True)
class CachedFingerprint:
    """캐시에 저장하는 파일 지문(삭제·이동 시 재사용)."""

    sha256: str
    fuzzy_hash: str | None
    size: int


@dataclass(frozen=True)
class Pending:
    """디바운스 대기 중인 경로의 최신 이벤트 정보."""

    event_type: str
    moved_from: str | None = None


@dataclass(frozen=True)
class Task:
    """워커 큐에 들어가는 처리 단위."""

    path: str
    event_type: str
    moved_from: str | None = None
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/errors.py client/agent/models.py client/tests/test_models.py
git commit -m "feat: 클라이언트 커스텀 예외와 도메인 모델"
```

---

## Task 3: 지문 계산 (fingerprint.py)

**Files:**
- Create: `client/agent/fingerprint.py`
- Test: `client/tests/test_fingerprint.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_fingerprint.py`:
```python
"""지문 계산 테스트 — 서버와 동일 값, raw bytes."""

import hashlib
import sys
from pathlib import Path

import ppdeep

from agent.fingerprint import compute_fuzzy, compute_sha256, fingerprint_file

# 서버 fingerprint 모듈을 직접 import해 동일성 비교
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app import fingerprint as server_fp  # noqa: E402


def test_sha256_matches_hashlib() -> None:
    data = b"hello world"
    assert compute_sha256(data) == hashlib.sha256(data).hexdigest()


def test_fuzzy_none_for_empty() -> None:
    assert compute_fuzzy(b"") is None


def test_matches_server_fingerprint() -> None:
    data = ("Confidential note. " * 50).encode()
    assert compute_sha256(data) == server_fp.compute_sha256(data)
    assert compute_fuzzy(data) == server_fp.compute_fuzzy(data)


def test_fingerprint_file_reads_raw_bytes(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    content = bytes(range(256)) * 10
    f.write_bytes(content)
    fp = fingerprint_file(f)
    assert fp.sha256 == hashlib.sha256(content).hexdigest()
    assert fp.size == len(content)
    assert fp.fuzzy_hash == ppdeep.hash(content)
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.fingerprint'`

- [ ] **Step 3: 구현**

`client/agent/fingerprint.py`:
```python
"""파일 지문(SHA-256 + ssdeep). 서버 server/app/fingerprint.py와 동일 로직.

지문 동일성 계약(설계 §5): 반드시 raw bytes(바이너리)에서 계산한다. 텍스트 모드·
줄바꿈 변환이 끼면 서버 baseline과 매칭되지 않는다.
"""

import hashlib
from pathlib import Path

import ppdeep

from agent.models import CachedFingerprint


def compute_sha256(data: bytes) -> str:
    """바이트의 SHA-256 16진 해시."""
    return hashlib.sha256(data).hexdigest()


def compute_fuzzy(data: bytes) -> str | None:
    """바이트의 ssdeep fuzzy 지문. 빈 입력이면 None."""
    if not data:
        return None
    return ppdeep.hash(data)


def fingerprint_file(path: Path) -> CachedFingerprint:
    """파일을 raw bytes로 읽어 지문을 계산한다.

    Args:
        path: 대상 파일 경로.

    Returns:
        sha256·fuzzy_hash·size를 담은 CachedFingerprint.

    Raises:
        OSError: 파일 열기·읽기 실패(잠김 등) 시.
    """
    data = path.read_bytes()
    return CachedFingerprint(
        sha256=compute_sha256(data),
        fuzzy_hash=compute_fuzzy(data),
        size=len(data),
    )
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_fingerprint.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/fingerprint.py client/tests/test_fingerprint.py
git commit -m "feat: 클라이언트 지문 계산(서버와 동일·raw bytes)"
```

---

## Task 4: 이벤트 헬퍼 (events.py)

**Files:**
- Create: `client/agent/events.py`
- Test: `client/tests/test_events.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_events.py`:
```python
"""임시파일 필터·source_hint 휴리스틱 테스트."""

from agent.events import should_ignore, source_hint_for

GLOBS = ["~$*", "*.tmp", "*.crdownload", "*.part"]


def test_ignores_temp_files() -> None:
    assert should_ignore("C:\\x\\~$report.docx", GLOBS)
    assert should_ignore("C:\\x\\data.tmp", GLOBS)
    assert should_ignore("C:\\x\\movie.crdownload", GLOBS)


def test_keeps_normal_files() -> None:
    assert not should_ignore("C:\\x\\secret.txt", GLOBS)
    assert not should_ignore("C:\\x\\design.dwg", GLOBS)


def test_source_hint_downloads() -> None:
    assert source_hint_for("C:\\Users\\me\\Downloads\\a.zip") == "downloads"


def test_source_hint_cloud() -> None:
    assert source_hint_for("C:\\Users\\me\\Google Drive\\a.txt") == "gdrive_sync"
    assert source_hint_for("C:\\Users\\me\\Dropbox\\a.txt") == "dropbox_sync"
    assert source_hint_for("C:\\Users\\me\\OneDrive\\a.txt") == "onedrive_sync"


def test_source_hint_none() -> None:
    assert source_hint_for("C:\\Secret\\a.txt") is None
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.events'`

- [ ] **Step 3: 구현**

`client/agent/events.py`:
```python
"""파일 이벤트 보조 함수: 임시파일 필터, 경로 기반 source_hint 추정."""

from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import PurePath

# 경로 폴더명(소문자) → source_hint 값
_HINT_FOLDERS = (
    ("downloads", "downloads"),
    ("google drive", "gdrive_sync"),
    ("googledrive", "gdrive_sync"),
    ("dropbox", "dropbox_sync"),
    ("onedrive", "onedrive_sync"),
)


def should_ignore(path: str, ignore_globs: Sequence[str]) -> bool:
    """파일명이 임시파일 glob 중 하나에 맞으면 True.

    Args:
        path: 파일 경로.
        ignore_globs: 무시할 파일명 glob 목록.

    Returns:
        무시 대상이면 True.
    """
    name = PurePath(path).name
    return any(fnmatch(name, pattern) for pattern in ignore_globs)


def source_hint_for(path: str) -> str | None:
    """경로의 폴더명으로 출처 힌트를 추정한다(없으면 None)."""
    lowered = path.lower()
    for needle, hint in _HINT_FOLDERS:
        if needle in lowered:
            return hint
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_events.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/events.py client/tests/test_events.py
git commit -m "feat: 임시파일 필터와 source_hint 휴리스틱"
```

---

## Task 5: 설정 로드·검증 (config.py)

**Files:**
- Create: `client/agent/config.py`
- Test: `client/tests/test_config.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_config.py`:
```python
"""config.toml 로드·검증 테스트."""

from pathlib import Path

import pytest

from agent.config import load_config
from agent.errors import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_valid_config(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cfg_path = _write(tmp_path, f'''
server_url = "http://127.0.0.1:8000"
debounce_seconds = 1.5
watch_paths = ["{watch.as_posix()}"]
ignore_globs = ["*.tmp"]
''')
    cfg = load_config(cfg_path)
    assert cfg.server_url == "http://127.0.0.1:8000"
    assert cfg.debounce_seconds == 1.5
    assert cfg.watch_paths == (watch,)
    assert cfg.ignore_globs == ("*.tmp",)


def test_missing_server_url_raises(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cfg_path = _write(tmp_path, f'''
debounce_seconds = 1.0
watch_paths = ["{watch.as_posix()}"]
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_nonexistent_watch_path_raises(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, '''
server_url = "http://x"
debounce_seconds = 1.0
watch_paths = ["C:\\\\does\\\\not\\\\exist_xyz"]
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_empty_watch_paths_raises(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, '''
server_url = "http://x"
debounce_seconds = 1.0
watch_paths = []
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_nonpositive_debounce_raises(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cfg_path = _write(tmp_path, f'''
server_url = "http://x"
debounce_seconds = 0
watch_paths = ["{watch.as_posix()}"]
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.config'`

- [ ] **Step 3: 구현**

`client/agent/config.py`:
```python
"""config.toml 로드·검증. 시스템 경계 입력 검증(설계 §8)."""

import tomllib
from pathlib import Path

from agent.errors import ConfigError
from agent.models import Config

_DEFAULT_IGNORE = ("~$*", "*.tmp", "*.crdownload", "*.part")


def load_config(path: Path) -> Config:
    """config.toml을 읽어 검증된 Config를 반환한다.

    Args:
        path: config.toml 경로.

    Returns:
        검증된 Config.

    Raises:
        ConfigError: 파일 없음·파싱 실패·필수값 누락·경로 부재·잘못된 값.
    """
    if not path.is_file():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config.toml 파싱 실패: {exc}") from exc

    server_url = raw.get("server_url")
    if not server_url or not isinstance(server_url, str):
        raise ConfigError("server_url 이 필요합니다")

    debounce = raw.get("debounce_seconds", 1.5)
    if not isinstance(debounce, (int, float)) or debounce <= 0:
        raise ConfigError("debounce_seconds 는 양수여야 합니다")

    raw_paths = raw.get("watch_paths") or []
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ConfigError("watch_paths 가 비어 있습니다")
    watch_paths: list[Path] = []
    for entry in raw_paths:
        p = Path(entry)
        if not p.is_dir():
            raise ConfigError(f"watch_paths 의 경로가 존재하는 디렉터리가 아닙니다: {p}")
        watch_paths.append(p)

    ignore = raw.get("ignore_globs") or list(_DEFAULT_IGNORE)
    return Config(
        server_url=server_url,
        debounce_seconds=float(debounce),
        watch_paths=tuple(watch_paths),
        ignore_globs=tuple(ignore),
    )
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/config.py client/tests/test_config.py
git commit -m "feat: config.toml 로드·검증(실패 시 ConfigError)"
```

---

## Task 6: 지문 캐시 (cache.py)

**Files:**
- Create: `client/agent/cache.py`
- Test: `client/tests/test_cache.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_cache.py`:
```python
"""SQLite 지문 캐시 테스트(get/put/pop)."""

from pathlib import Path

from agent.cache import FingerprintCache
from agent.models import CachedFingerprint


def _fp(tag: str) -> CachedFingerprint:
    return CachedFingerprint(sha256=tag * 64, fuzzy_hash="3:" + tag, size=10)


def test_put_then_get(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    cache.put("C:\\a.txt", _fp("a"))
    got = cache.get("C:\\a.txt")
    assert got == _fp("a")


def test_get_missing_returns_none(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    assert cache.get("C:\\nope.txt") is None


def test_pop_returns_and_removes(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    cache.put("C:\\a.txt", _fp("a"))
    assert cache.pop("C:\\a.txt") == _fp("a")
    assert cache.get("C:\\a.txt") is None


def test_pop_missing_returns_none(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    assert cache.pop("C:\\nope.txt") is None


def test_put_overwrites(tmp_path: Path) -> None:
    cache = FingerprintCache(tmp_path / "c.db")
    cache.put("C:\\a.txt", _fp("a"))
    cache.put("C:\\a.txt", _fp("b"))
    assert cache.get("C:\\a.txt") == _fp("b")
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.cache'`

- [ ] **Step 3: 구현**

`client/agent/cache.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_cache.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/cache.py client/tests/test_cache.py
git commit -m "feat: SQLite 지문 캐시(스레드 안전)"
```

---

## Task 7: 전송 (sender.py)

**Files:**
- Create: `client/agent/sender.py`
- Test: `client/tests/test_sender.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_sender.py`:
```python
"""서버 모드 b 전송 테스트(httpx MockTransport)."""

import httpx

from agent.sender import Sender

CAPTURED: list[dict] = []


def _ok_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        CAPTURED.append(json.loads(request.content))
        return httpx.Response(200, json={"matches": []})
    return httpx.MockTransport(handler)


def _fail_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)
    return httpx.MockTransport(handler)


def test_send_posts_mode_b_payload() -> None:
    CAPTURED.clear()
    client = httpx.Client(transport=_ok_transport())
    sender = Sender("http://srv", host="PC-1", user="kim", client=client)
    ok = sender.send(sha256="a" * 64, fuzzy_hash="3:x", size=12,
                     name="s.txt", event_type="created", source_hint="downloads")
    assert ok is True
    assert CAPTURED[-1] == {
        "sha256": "a" * 64, "fuzzy_hash": "3:x", "size": 12, "name": "s.txt",
        "event_type": "created", "host": "PC-1", "user": "kim",
        "source_hint": "downloads",
    }


def test_send_returns_false_on_server_error() -> None:
    client = httpx.Client(transport=_fail_transport())
    sender = Sender("http://srv", host="PC-1", user="kim", client=client, retries=1)
    ok = sender.send(sha256="a" * 64, fuzzy_hash=None, size=1,
                     name="x", event_type="deleted", source_hint=None)
    assert ok is False
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_sender.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.sender'`

- [ ] **Step 3: 구현**

`client/agent/sender.py`:
```python
"""서버 POST /api/fingerprints 모드 b 전송. 재시도 후 실패 시 로그(설계 §9)."""

import logging

import httpx

logger = logging.getLogger("agent.sender")


class Sender:
    """지문 이벤트를 서버 모드 b(JSON)로 전송한다."""

    def __init__(
        self,
        server_url: str,
        host: str,
        user: str,
        client: httpx.Client | None = None,
        retries: int = 2,
    ) -> None:
        self._url = server_url.rstrip("/") + "/api/fingerprints"
        self._host = host
        self._user = user
        self._client = client or httpx.Client(timeout=5.0)
        self._retries = retries

    def send(
        self,
        *,
        sha256: str,
        fuzzy_hash: str | None,
        size: int,
        name: str,
        event_type: str,
        source_hint: str | None,
    ) -> bool:
        """이벤트를 전송한다. 성공(200)이면 True, 재시도 후에도 실패면 False."""
        payload = {
            "sha256": sha256, "fuzzy_hash": fuzzy_hash, "size": size,
            "name": name, "event_type": event_type,
            "host": self._host, "user": self._user, "source_hint": source_hint,
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

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_sender.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/sender.py client/tests/test_sender.py
git commit -m "feat: 서버 모드 b 전송(재시도·로그)"
```

---

## Task 8: 디바운서 (debouncer.py)

**Files:**
- Create: `client/agent/debouncer.py`
- Test: `client/tests/test_debouncer.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_debouncer.py`:
```python
"""디바운서 테스트 — 타이머 주입으로 결정적."""

from agent.debouncer import Debouncer
from agent.models import Pending


class FakeTimer:
    """threading.Timer 대체: start/cancel 기록, fire()로 수동 발화."""

    instances: list["FakeTimer"] = []

    def __init__(self, seconds: float, callback) -> None:
        self.seconds = seconds
        self.callback = callback
        self.cancelled = False
        self.started = False
        FakeTimer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.callback()


def test_fire_calls_on_fire_with_latest_pending() -> None:
    FakeTimer.instances.clear()
    fired: list = []
    deb = Debouncer(0.1, lambda path, pending: fired.append((path, pending)),
                    timer_factory=FakeTimer)
    deb.schedule("C:\\a.txt", Pending(event_type="created"))
    FakeTimer.instances[-1].fire()
    assert fired == [("C:\\a.txt", Pending(event_type="created"))]


def test_reschedule_cancels_previous_and_keeps_latest() -> None:
    FakeTimer.instances.clear()
    fired: list = []
    deb = Debouncer(0.1, lambda path, pending: fired.append((path, pending)),
                    timer_factory=FakeTimer)
    deb.schedule("C:\\a.txt", Pending(event_type="created"))
    first = FakeTimer.instances[-1]
    deb.schedule("C:\\a.txt", Pending(event_type="modified"))
    assert first.cancelled is True
    FakeTimer.instances[-1].fire()
    assert fired == [("C:\\a.txt", Pending(event_type="modified"))]
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_debouncer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.debouncer'`

- [ ] **Step 3: 구현**

`client/agent/debouncer.py`:
```python
"""경로별 디바운스. 같은 경로의 연속 이벤트를 1건으로 합쳐 on_fire를 호출한다.

쓰기 버스트가 잦아들 때(seconds 동안 추가 이벤트 없음) 발화한다(설계 §6). 시간은
timer_factory로 주입 가능해 테스트가 결정적이다. 내부 dict는 락으로 보호한다.
"""

import threading
from collections.abc import Callable

from agent.models import Pending


class Debouncer:
    """경로별 타이머로 이벤트를 디바운스한다."""

    def __init__(
        self,
        seconds: float,
        on_fire: Callable[[str, Pending], None],
        timer_factory=threading.Timer,
    ) -> None:
        self._seconds = seconds
        self._on_fire = on_fire
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._timers: dict[str, object] = {}
        self._pending: dict[str, Pending] = {}

    def schedule(self, path: str, pending: Pending) -> None:
        """경로의 타이머를 (재)설정하고 최신 pending을 기억한다."""
        with self._lock:
            existing = self._timers.get(path)
            if existing is not None:
                existing.cancel()
            self._pending[path] = pending
            timer = self._timer_factory(self._seconds, lambda: self._fire(path))
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: str) -> None:
        with self._lock:
            pending = self._pending.pop(path, None)
            self._timers.pop(path, None)
        if pending is not None:
            self._on_fire(path, pending)

    def cancel_all(self) -> None:
        """대기 중인 모든 타이머를 취소한다."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._pending.clear()
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_debouncer.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/debouncer.py client/tests/test_debouncer.py
git commit -m "feat: 경로별 디바운서(타이머 주입·스레드 안전)"
```

---

## Task 9: 워커 (worker.py)

**Files:**
- Create: `client/agent/worker.py`
- Test: `client/tests/test_worker.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_worker.py`:
```python
"""단일 워커 처리 로직 테스트(존재→해싱·전송, 부재→캐시 deleted)."""

from pathlib import Path

from agent.cache import FingerprintCache
from agent.models import CachedFingerprint, Task
from agent.worker import Worker


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def _worker(tmp_path: Path) -> tuple[Worker, FakeSender, FingerprintCache]:
    cache = FingerprintCache(tmp_path / "c.db")
    sender = FakeSender()
    return Worker(cache, sender), sender, cache


def test_existing_file_hashes_caches_and_sends(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    f = tmp_path / "secret.txt"
    f.write_bytes(b"hello world data here")
    worker.process(Task(path=str(f), event_type="created"))
    assert sender.calls[-1]["event_type"] == "created"
    assert sender.calls[-1]["sha256"]
    assert cache.get(str(f)) is not None  # 캐시 갱신됨


def test_deleted_uses_cached_fingerprint(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    path = str(tmp_path / "gone.txt")
    cache.put(path, CachedFingerprint(sha256="a" * 64, fuzzy_hash="3:x", size=9))
    worker.process(Task(path=path, event_type="deleted"))  # 파일 실제로 없음
    assert sender.calls[-1]["event_type"] == "deleted"
    assert sender.calls[-1]["sha256"] == "a" * 64
    assert cache.get(path) is None  # 캐시에서 제거됨


def test_deleted_without_cache_skips(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    worker.process(Task(path=str(tmp_path / "never.txt"), event_type="deleted"))
    assert sender.calls == []


def test_moved_pops_source_and_processes_dest(tmp_path: Path) -> None:
    worker, sender, cache = _worker(tmp_path)
    src = str(tmp_path / "old.txt")
    cache.put(src, CachedFingerprint(sha256="b" * 64, fuzzy_hash=None, size=3))
    dst = tmp_path / "new.txt"
    dst.write_bytes(b"moved content here")
    worker.process(Task(path=str(dst), event_type="moved", moved_from=src))
    assert cache.get(src) is None             # src 캐시 제거
    assert cache.get(str(dst)) is not None     # dst 캐시 채움
    assert sender.calls[-1]["event_type"] == "moved"
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.worker'`

- [ ] **Step 3: 구현**

`client/agent/worker.py`:
```python
"""단일 워커 큐 — 해싱·전송을 순차 처리해 백프레셔를 제공한다(설계 §6).

발화 시점의 파일 존재 여부가 최종 심판이다: 존재하면 해싱·전송(created/modified/moved),
없으면 캐시의 기억된 지문으로 deleted 전송(캐시에 없으면 스킵).
"""

import logging
import queue
import threading
from pathlib import Path

from agent.cache import FingerprintCache
from agent.fingerprint import fingerprint_file
from agent.events import source_hint_for
from agent.models import EVENT_DELETED, EVENT_MODIFIED, Task

logger = logging.getLogger("agent.worker")


class Worker:
    """Task를 순차 처리하는 단일 워커 스레드."""

    def __init__(self, cache: FingerprintCache, sender, fingerprint_file=fingerprint_file) -> None:
        self._cache = cache
        self._sender = sender
        self._fingerprint_file = fingerprint_file
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """워커 스레드를 시작한다."""
        self._thread.start()

    def stop(self) -> None:
        """종료 신호를 넣고 스레드가 끝날 때까지 기다린다."""
        self._queue.put(None)
        self._thread.join()

    def submit(self, task: Task) -> None:
        """처리할 Task를 큐에 넣는다."""
        self._queue.put(task)

    def _run(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                self.process(task)
            except Exception as exc:  # 워커 루프는 어떤 예외에도 죽지 않는다
                logger.exception("워커 처리 실패: %s", exc)

    def process(self, task: Task) -> None:
        """Task 1건을 처리한다(테스트에서 직접 호출 가능)."""
        if task.moved_from:
            self._cache.pop(task.moved_from)

        path = Path(task.path)
        if path.exists():
            try:
                fp = self._fingerprint_file(path)
            except OSError as exc:
                logger.warning("해싱 실패(잠김?) %s: %s", task.path, exc)
                return
            self._cache.put(task.path, fp)
            event_type = task.event_type
            if event_type == EVENT_DELETED:  # 존재하는데 deleted로 기록됐으면 modified로 정정
                event_type = EVENT_MODIFIED
            self._sender.send(
                sha256=fp.sha256, fuzzy_hash=fp.fuzzy_hash, size=fp.size,
                name=path.name, event_type=event_type,
                source_hint=source_hint_for(task.path),
            )
            return

        cached = self._cache.pop(task.path)
        if cached is None:
            logger.info("삭제 이벤트지만 캐시에 지문 없음, 스킵: %s", task.path)
            return
        self._sender.send(
            sha256=cached.sha256, fuzzy_hash=cached.fuzzy_hash, size=cached.size,
            name=path.name, event_type=EVENT_DELETED,
            source_hint=source_hint_for(task.path),
        )
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_worker.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/worker.py client/tests/test_worker.py
git commit -m "feat: 단일 워커(존재→해싱·전송, 부재→캐시 deleted)"
```

---

## Task 10: 초기 스캔 (scanner.py)

**Files:**
- Create: `client/agent/scanner.py`
- Test: `client/tests/test_scanner.py`

- [ ] **Step 1: 실패 테스트**

`client/tests/test_scanner.py`:
```python
"""초기 스캔 테스트 — 캐시만 채우고 전송하지 않는다."""

from pathlib import Path

from agent.cache import FingerprintCache
from agent.scanner import initial_scan


def test_scan_fills_cache_no_send(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    (watch / "a.txt").write_bytes(b"alpha content here")
    (watch / "b.tmp").write_bytes(b"temp ignored")
    sub = watch / "sub"
    sub.mkdir()
    (sub / "c.txt").write_bytes(b"charlie content here")

    cache = FingerprintCache(tmp_path / "c.db")
    count = initial_scan((watch,), ("*.tmp",), cache)

    assert count == 2  # a.txt, sub/c.txt (b.tmp 무시)
    assert cache.get(str(watch / "a.txt")) is not None
    assert cache.get(str(sub / "c.txt")) is not None
    assert cache.get(str(watch / "b.tmp")) is None
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.scanner'`

- [ ] **Step 3: 구현**

`client/agent/scanner.py`:
```python
"""초기 스캔(콜드스타트 대응, 설계 §7): 감시 폴더를 1회 워크해 캐시만 채운다.

전송하지 않는다 — 시작마다 수천 건 POST하는 폭주를 피한다. observer 시작 전에
동기로 1회 호출한다.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from agent.cache import FingerprintCache
from agent.events import should_ignore
from agent.fingerprint import fingerprint_file as _default_fingerprint_file
from agent.models import CachedFingerprint

logger = logging.getLogger("agent.scanner")


def initial_scan(
    watch_paths: Sequence[Path],
    ignore_globs: Sequence[str],
    cache: FingerprintCache,
    fingerprint_file=_default_fingerprint_file,
) -> int:
    """감시 폴더를 워크해 각 파일 지문을 캐시에 채운다(전송 없음).

    Args:
        watch_paths: 감시 폴더 목록.
        ignore_globs: 무시할 임시파일 glob.
        cache: 채울 지문 캐시.
        fingerprint_file: 파일 지문 함수(테스트 주입용).

    Returns:
        캐시에 넣은 파일 수.
    """
    count = 0
    for root in watch_paths:
        for path in Path(root).rglob("*"):
            if not path.is_file():
                continue
            if should_ignore(str(path), ignore_globs):
                continue
            try:
                fp: CachedFingerprint = fingerprint_file(path)
            except OSError as exc:
                logger.warning("초기 스캔 해싱 실패 %s: %s", path, exc)
                continue
            cache.put(str(path), fp)
            count += 1
    logger.info("초기 스캔 완료: %s개 파일 캐시", count)
    return count
```

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_scanner.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 커밋**

```bash
git add client/agent/scanner.py client/tests/test_scanner.py
git commit -m "feat: 초기 스캔(캐시만 채움, 전송 없음)"
```

---

## Task 11: 와처 배선 + 진입점 (watcher.py, main.py)

**Files:**
- Create: `client/agent/watcher.py`, `client/agent/main.py`
- Test: `client/tests/test_watcher.py`

- [ ] **Step 1: 실패 테스트 (통합 — 실제 watchdog, 디바운스 짧게, 폴링 대기)**

`client/tests/test_watcher.py`:
```python
"""통합: 실제 watchdog watcher가 파일 이벤트를 올바른 Task로 전달하는지.

디바운스를 0.1초로 두고, FakeSender 호출을 폴링으로 기다려 flaky를 방지한다.
"""

import time
from pathlib import Path

from agent.cache import FingerprintCache
from agent.watcher import build_watcher


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_created_then_deleted_flow(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cache = FingerprintCache(tmp_path / "c.db")
    sender = FakeSender()
    watcher = build_watcher(
        watch_paths=(watch,), ignore_globs=("*.tmp",),
        cache=cache, sender=sender, debounce_seconds=0.1,
    )
    watcher.start()
    try:
        f = watch / "secret.txt"
        f.write_bytes(b"confidential bytes here for test")
        assert _wait_for(lambda: any(c["event_type"] in ("created", "modified")
                                     for c in sender.calls))
        f.unlink()
        assert _wait_for(lambda: any(c["event_type"] == "deleted" for c in sender.calls))
    finally:
        watcher.stop()
```

- [ ] **Step 2: 실패 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.watcher'`

- [ ] **Step 3: 구현**

`client/agent/watcher.py`:
```python
"""watchdog 핸들러와 파이프라인 배선. 이벤트 → 디바운스 → 워커 큐.

watchdog 콜백 스레드는 디바운서에 등록만 한다. 디바운스 발화 시 Task를 워커 큐에
넣고, 단일 워커가 해싱·전송한다.
"""

import logging

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent.cache import FingerprintCache
from agent.debouncer import Debouncer
from agent.events import should_ignore
from agent.models import (
    EVENT_CREATED,
    EVENT_DELETED,
    EVENT_MODIFIED,
    EVENT_MOVED,
    Pending,
    Task,
)
from agent.worker import Worker

logger = logging.getLogger("agent.watcher")


class _Handler(FileSystemEventHandler):
    """watchdog 이벤트를 필터링해 디바운서에 등록한다."""

    def __init__(self, debouncer: Debouncer, ignore_globs) -> None:
        self._debouncer = debouncer
        self._ignore_globs = ignore_globs

    def _filtered(self, path: str) -> bool:
        return should_ignore(path, self._ignore_globs)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.src_path):
            return
        self._debouncer.schedule(event.src_path, Pending(event_type=EVENT_CREATED))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.src_path):
            return
        self._debouncer.schedule(event.src_path, Pending(event_type=EVENT_MODIFIED))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.src_path):
            return
        self._debouncer.schedule(event.src_path, Pending(event_type=EVENT_DELETED))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory or self._filtered(event.dest_path):
            return
        self._debouncer.schedule(
            event.dest_path, Pending(event_type=EVENT_MOVED, moved_from=event.src_path)
        )


class Watcher:
    """observer + 워커 묶음. start/stop로 수명을 관리한다."""

    def __init__(self, observer: Observer, worker: Worker, debouncer: Debouncer) -> None:
        self._observer = observer
        self._worker = worker
        self._debouncer = debouncer

    def start(self) -> None:
        self._worker.start()
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
        self._debouncer.cancel_all()
        self._worker.stop()


def build_watcher(
    *,
    watch_paths,
    ignore_globs,
    cache: FingerprintCache,
    sender,
    debounce_seconds: float,
) -> Watcher:
    """파이프라인을 배선한 Watcher를 만든다."""
    worker = Worker(cache, sender)

    def on_fire(path: str, pending: Pending) -> None:
        worker.submit(Task(path=path, event_type=pending.event_type,
                           moved_from=pending.moved_from))

    debouncer = Debouncer(debounce_seconds, on_fire)
    handler = _Handler(debouncer, ignore_globs)
    observer = Observer()
    for root in watch_paths:
        observer.schedule(handler, str(root), recursive=True)
    return Watcher(observer, worker, debouncer)
```

`client/agent/main.py`:
```python
"""에이전트 진입점: 설정 로드·검증 → 초기 스캔 → 감시 상주.

실행(사용자 확인 후): .venv\\Scripts\\python.exe -m agent.main client\\config.toml
캐시·로그는 감시 폴더 밖(client/ 옆)에 둔다(자기 이벤트 루프 방지, 설계 §3).
"""

import getpass
import logging
import socket
import sys
import time
from pathlib import Path

from agent.cache import FingerprintCache
from agent.config import load_config
from agent.scanner import initial_scan
from agent.sender import Sender
from agent.watcher import build_watcher

logger = logging.getLogger("agent")

_STATE_DIR = Path(__file__).resolve().parent.parent / ".state"  # client/.state (감시 폴더 밖)


def main(config_path: str) -> None:
    """에이전트를 구동한다."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config(Path(config_path))

    _STATE_DIR.mkdir(exist_ok=True)
    cache = FingerprintCache(_STATE_DIR / "cache.db")

    logger.info("초기 스캔 시작...")
    initial_scan(config.watch_paths, config.ignore_globs, cache)

    sender = Sender(config.server_url, host=socket.gethostname(), user=getpass.getuser())
    watcher = build_watcher(
        watch_paths=config.watch_paths, ignore_globs=config.ignore_globs,
        cache=cache, sender=sender, debounce_seconds=config.debounce_seconds,
    )
    watcher.start()
    logger.info("감시 시작: %s", [str(p) for p in config.watch_paths])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("종료 중...")
    finally:
        watcher.stop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m agent.main <config.toml>")
        sys.exit(1)
    main(sys.argv[1])
```

> **상태 파일 격리(설계 §3):** 캐시는 `client/.state/cache.db`에 둔다 — 감시 폴더
> 밖이어야 자기 쓰기가 자기 이벤트를 일으키지 않는다. `client/.state/`는 .gitignore
> 대상(Task 12에서 추가).

- [ ] **Step 4: 통과 확인**

Run: `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest tests/test_watcher.py -v`
Expected: PASS (1 passed). watchdog OS 이벤트 지연으로 간헐 실패 시 `_wait_for` timeout을 늘린다.

- [ ] **Step 5: 커밋**

```bash
git add client/agent/watcher.py client/agent/main.py client/tests/test_watcher.py
git commit -m "feat: watchdog 배선과 에이전트 진입점"
```

---

## Task 12: .gitignore + 전체 테스트

**Files:**
- Modify: `file-tracer/.gitignore`
- Test: 전체

- [ ] **Step 1: .gitignore에 클라이언트 상태 추가**

`file-tracer/.gitignore`에 추가:
```
# 클라이언트 에이전트 상태(캐시 db·로그)
client/.state/
```

- [ ] **Step 2: 전체 테스트 실행**

Run (client 디렉터리에서): `D:\기타 프로그램\file-tracer\server\.venv\Scripts\python.exe -m pytest -v`
Expected: 전체 PASS

- [ ] **Step 3: 커밋**

```bash
git add file-tracer/.gitignore
git commit -m "chore: 클라이언트 상태 폴더 .gitignore 추가"
```

- [ ] **Step 4: (선택) 수동 E2E — ⚠ 사용자 확인 후**

1. 서버 기동(별도): `Set-Location server; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`
2. `client/config.toml`의 `watch_paths`를 실재 폴더(예: 임시 테스트 폴더)로 수정.
3. 에이전트 기동: `Set-Location client; ..\server\.venv\Scripts\python.exe -m agent.main config.toml`
4. 감시 폴더에 파일 생성·수정·삭제 → 서버 `http://127.0.0.1:8000/` 또는 `GET /api/fingerprints`에 event 레코드(host=내 PC)가 뜨면 성공.

---

## Self-Review (작성자 점검 결과)

**Spec 커버리지:**
- §3 모듈 분리 → Task 2~11이 모듈별로 1:1 매핑 ✔
- §4 서버 계약(모드 b 필드) → Task 7 sender 페이로드 ✔
- §5 raw bytes 지문 동일성 → Task 3 `fingerprint_file`(read_bytes) + 서버와 동일성 비교 테스트 ✔
- §6 파이프라인(필터·디바운스·단일 워커·deleted-승리·moved) → Task 8·9·11 ✔
- §6 동시성(단일 워커 큐·락·check_same_thread) → Task 9 Worker·Task 6 cache·Task 8 debouncer ✔
- §7 초기 스캔(캐시만, observer 전 동기) → Task 10·11 main ✔
- §8 config 검증(실패 시 종료) → Task 5 ✔
- §3 상태파일 격리 → Task 11 main `.state/` + Task 12 .gitignore ✔
- §9 에러 처리(커스텀 예외·재시도·로그) → Task 2·7·9 ✔
- §10 검증(단위·통합·E2E) → Task 2~11 단위 + Task 11 통합 + Task 12 E2E ✔
- §11 한계 → 구현 대상 아님(문서) ✔

**Placeholder 스캔:** 없음. 모든 코드 단계에 실제 코드 포함.

**타입 일관성:** `CachedFingerprint`·`Pending`·`Task`·`Config` 필드, `fingerprint_file`/`Sender.send`/`Debouncer.schedule`/`Worker.process`/`build_watcher` 시그니처가 Task 간 일치. sender는 키워드 인자(sha256/fuzzy_hash/size/name/event_type/source_hint)로 통일 — Task 7·9·11 FakeSender 동일.

**알려진 주의점:** Task 11 통합 테스트는 실제 watchdog OS 이벤트에 의존해 환경에 따라 지연될 수 있다 — `_wait_for` 폴링(기본 5초)으로 흡수하되, 매우 느린 환경에서 실패 시 timeout을 늘린다(코드가 아니라 테스트 파라미터).
