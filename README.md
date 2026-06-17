# file-tracer

사내 "위험 파일"을 **파일 본문 업로드 없이 지문(SHA-256 + ssdeep fuzzy)만으로** 추적하는
프로토타입. 지정 폴더의 파일 이벤트(생성·수정·이동·삭제)를 클라이언트 에이전트가 감지해
지문을 찍어 서버로 보내고, 서버는 등록된 기준 파일(baseline)과 매칭해 누가·언제·어떤
위험 파일을 만졌는지 기록한다.

> 포지셔닝은 "법적 증거 시스템"이 아니라 **억지·감사 도구**다. 서버 타임스탬프 +
> append-only 해시체인으로 우발적 변조는 탐지하지만, 의도적 전체 위조나 우회 채널
> (스크린샷·촬영 등)에는 구조적으로 무력하다. 자세한 배경은
> `docs/superpowers/specs/2026-06-09-file-tracer-prototype-design.md` 참고.

## 구성

| 폴더 | 설명 | README |
|---|---|---|
| `server/` | FastAPI + SQLite 지문 등록·매칭 API + 단일 웹페이지 | [server/README.md](server/README.md) |
| `client/` | watchdog 기반 폴더 감시 에이전트(서버로 지문 전송) | [client/README.md](client/README.md) |
| `docs/` | 설계 스펙·구현 계획 문서 |  |

## 동작 흐름

```
[감시 폴더] --파일 이벤트--> client(watchdog)
   → 임시파일 필터 → 경로별 디바운스 → 단일 워커 큐 → 지문 계산
   → POST /api/fingerprints (모드 b, JSON) --> server
        → event 기록(해시체인) + baseline과 자동 매칭(trace_match)
        → 웹페이지(http://127.0.0.1:8000/)에서 baseline·event 표 확인
```

## 빠른 시작

Python 가상환경은 **`server/.venv` 하나를 서버·클라이언트가 공유**한다
(클라이언트의 watchdog까지 모두 여기에 설치).

```powershell
# 1. 서버 기동 (한 터미널)
Set-Location server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# → http://127.0.0.1:8000/ 에서 위험파일 업로드(baseline 등록)

# 2. 엔드포인트 호스트 기동 (다른 터미널)
#    한 프로세스로 코어(서버 전송) + FS 감시 + 커넥터 intake(:8765)를 띄운다.
Set-Location client
..\server\.venv\Scripts\python.exe -m main config.toml
```

> `config.toml`의 `watch_paths`는 **실재하는 폴더**여야 한다(없으면 기동 시 오류).
> 빠른 시연용으로는 루트의 `supervise-folder`를 가리키는 `client/config.e2e.toml`을
> 써도 된다: `... -m main config.e2e.toml`.
>
> 브라우저 업로드/다운로드/붙여넣기까지 잡는 **Chrome 커넥터(C++ 브리지) 셋업**은
> `client/connector/README.md` 참고.

각 프로그램의 설정·테스트 등 자세한 내용은 폴더별 README를 참고한다.

> **참고:** `python`은 PATH에 없을 수 있으므로 venv의 절대 경로
> `server\.venv\Scripts\python.exe`를 사용한다.

## 기술 스택

Python 3.12 · FastAPI · uvicorn · sqlite3(표준) · ppdeep(ssdeep 계열 fuzzy) ·
watchdog · httpx · pytest
