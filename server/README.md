# file-tracer 서버

파일 지문을 등록·매칭하고 변조탐지 장부(해시체인)에 이벤트를 남기는 FastAPI 서버.
기준 파일(baseline)은 본문 업로드로 등록하고, 클라이언트가 보내는 이벤트는 지문(JSON)만
받아 baseline과 자동 매칭한다.

## 데이터 모델

4개 정규화 테이블(SQLite, `file_tracer.db`):

- `supervise_file` — 추적 대상 baseline(위험 파일)
- `update_history` — baseline 갱신 시 옛 버전 스냅샷
- `event` — 들어온 감시 이벤트(append-only + 해시체인)
- `trace_match` — event ↔ supervise_file 매칭 결과

## API

| 메서드 · 경로 | 설명 |
|---|---|
| `POST /api/fingerprints` (multipart) | **모드 a** — 파일 업로드로 baseline 등록/갱신 |
| `POST /api/fingerprints` (JSON) | **모드 b** — 지문만 전송, 이벤트 기록 + 자동 매칭 |
| `GET /api/supervise-files` | baseline 목록(버전이력 수 포함) |
| `GET /api/events` | 최근 이벤트 목록(최고 매칭 요약 포함) |
| `GET /api/supervise-files/{id}/events` | 특정 baseline에 매칭된 이벤트 목록 |
| `GET /` | 업로드 폼 + baseline·event 표 웹페이지 |

매칭 규칙: SHA-256 동일 → `exact`(100). 아니면 ssdeep 유사도 0~100을 계산해
**50 이상**만 `fuzzy`로 포함한다.

## 실행

```powershell
Set-Location server

# (최초 1회) 의존성 설치
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 서버 기동
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# 개발 중 자동 리로드: 끝에 --reload 추가
```

→ 브라우저에서 `http://127.0.0.1:8000/` 접속.

## 테스트

```powershell
Set-Location server
.\.venv\Scripts\python.exe -m pytest -v
```

## 구조

```
server/
  app/
    main.py          uvicorn 진입점(SqliteRepository 구성)
    api.py           FastAPI 라우트(모드 a/b + GET)
    repository.py    SqliteRepository(4 테이블)
    matching.py      baseline 대상 지문 매칭
    chain.py         event 해시체인(변조탐지)
    fingerprint.py   SHA-256 + ppdeep fuzzy
    models.py        도메인 모델(frozen dataclass)
    constants.py     매칭 임계치·event_type 상수
    errors.py        HttpError 등 커스텀 예외
    static/index.html  단일 웹페이지
  tests/             pytest
  file_tracer.db     런타임 SQLite (git 추적 안 함)
```

> 스키마를 바꾼 뒤엔 구 `file_tracer.db`를 지우고 다시 기동한다.
