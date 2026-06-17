# file-tracer 클라이언트 (감시 에이전트)

지정 폴더의 파일 이벤트(생성·수정·이동·삭제)를 watchdog로 감지해 지문(SHA-256 + ssdeep)을
찍고, 구동 중인 서버의 `POST /api/fingerprints`(모드 b, JSON)로 전송하는 백그라운드
에이전트.

## 동작

```
watchdog 이벤트 → 임시파일 필터(ignore_globs) → 경로별 디바운스(쓰기 버스트 합침)
   → 단일 워커 큐(순차 해싱·전송)
        · 발화 시 파일이 있으면  → 해싱 후 created/modified/moved 전송
        · 파일이 없으면         → 로컬 캐시의 기억된 지문으로 deleted 전송
```

- 삭제·이동은 본문을 읽을 수 없으므로 로컬 SQLite **'경로→지문' 캐시**로 다룬다.
- 시작 시 **초기 스캔**으로 감시 폴더를 1회 워크해 캐시만 채운다(전송 없음 —
  기동 때마다 수천 건 POST하는 폭주 방지).
- 캐시는 감시 폴더 **밖**인 `client/.state/cache.db`에 둔다(자기 쓰기가 자기 이벤트를
  일으키는 루프 방지).

## 설정 (`config.toml`)

```toml
server_url = "http://127.0.0.1:8000"
debounce_seconds = 1.5
watch_paths = ["C:\\Secret"]                 # 감시할 폴더(여러 개 가능)
ignore_globs = ["~$*", "*.tmp", "*.crdownload", "*.part"]
```

실행 전 `watch_paths`를 실재하는 폴더로 수정한다(존재하지 않으면 기동 시 오류).

## 실행

가상환경은 서버의 `server/.venv`를 공유한다(watchdog·httpx·ppdeep 설치 위치).

```powershell
Set-Location client

# (최초 1회, 서버 venv에 watchdog만 추가 설치)
..\server\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 에이전트 기동 (서버가 먼저 떠 있어야 함)
..\server\.venv\Scripts\python.exe -m agent.main config.toml
```

`Ctrl+C`로 종료. 감시 폴더에서 파일을 만들고/고치고/지우면 서버
`http://127.0.0.1:8000/` 의 event 표에 매칭과 함께 뜬다.

## 테스트

```powershell
Set-Location client
..\server\.venv\Scripts\python.exe -m pytest -v
```

> `test_watcher.py`는 실제 watchdog OS 이벤트에 의존해 환경에 따라 느릴 수 있다
> (폴링으로 흡수하나 매우 느린 환경에선 간헐 실패 가능).

## 구조

```
client/
  config.toml        감시 설정
  agent/
    main.py          진입점(설정 로드 → 초기 스캔 → 감시 상주)
    watcher.py       watchdog 핸들러 + 파이프라인 배선
    debouncer.py     경로별 디바운스
    worker.py        단일 워커 큐(해싱·전송)
    scanner.py       초기 스캔(캐시만 채움)
    cache.py         SQLite 지문 캐시(삭제·이동 대응)
    sender.py        서버 모드 b 전송(재시도·로그)
    fingerprint.py   SHA-256 + ppdeep (서버와 동일 로직, raw bytes)
    events.py        임시파일 필터·source_hint 추정
    config.py        config.toml 로드·검증
    models.py        도메인 모델(frozen dataclass)
    errors.py        ConfigError
  tests/             pytest
  .state/            런타임 캐시 db (git 추적 안 함)
```
