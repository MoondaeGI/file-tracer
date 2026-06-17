# file-tracer 클라이언트(에이전트) 프로토타입 설계

- 작성일: 2026-06-10
- 상태: 승인됨 (구현 계획 단계로 진행)
- 선행: 서버 프로토타입 완성(`2026-06-09-file-tracer-prototype-design.md`) → `brainstorming` → `discussion`(devils-advocate, 6개 결함 수정)

---

## 1. 목적과 포지셔닝

각 PC에 백그라운드 상주하며 **지정 폴더의 파일 이벤트**(생성/수정/이동/삭제)가 발생하면
파일 지문(SHA-256 + ssdeep fuzzy)과 메타데이터를 찍어 **이미 완성된 서버**의
`POST /api/fingerprints` 모드 b로 전송하는 경량 에이전트.

서버 계약은 고정이므로 클라이언트는 그 계약을 채우는 **얇은 어댑터**다. 포지셔닝은
서버와 동일하게 "억지·감사 도구" 프로토타입이며, "빠르게 동작 확인"이 목표다.

## 2. 범위

### 포함

- `client/` 폴더, 전부 Python (watchdog + httpx + ppdeep).
- 지정 폴더(워치리스트) 재귀 감시 → 이벤트 필터 → 디바운스 → 지문 생성 → 서버 전송.
- 삭제·이동 추적을 위한 **로컬 SQLite 지문 캐시**.
- 시작 시 **초기 스캔**(감시 폴더 1회 워크로 캐시를 채움 — 전송은 하지 않음).
- **단일 워커 큐**로 해싱·전송을 순차 처리(백프레셔).

### 제외 (다음 단계로 명시 이월)

- 프로세스 귀속(process_name)·다운로드/업로드 방향(direction) — ETW·커널 영역.
- 화면 촬영·클립보드·암호화·대용량 파일 정책.
- 인증, 전송 실패 시 **영속(디스크) 재전송 큐**.
- 본문 업로드 게이트(서버 측 문서지문) — 클라는 지문만 보낸다.

## 3. 아키텍처

```
client/                      (전부 Python)
  requirements.txt           watchdog, httpx, ppdeep
  config.toml                감시 설정 (예시 동봉)
  agent/
    __init__.py
    errors.py                커스텀 예외(ConfigError 등)
    config.py                config.toml 로드·검증(tomllib=표준 라이브러리)
    fingerprint.py           SHA-256 + ppdeep — 서버와 동일 라이브러리·동일 raw bytes
    cache.py                 SQLite '경로→지문' 캐시 (get/put/pop), 스레드 안전
    events.py                watchdog 이벤트 → 내부 이벤트 매핑, 임시파일/디렉터리 필터
    debouncer.py             경로별 디바운스 타이머(시간 주입 가능), 발화 시 워커 큐로
    worker.py                단일 워커 큐 — 해싱·전송을 순차 소비(백프레셔)
    sender.py                서버 모드 b로 POST(httpx, 동기, 재시도 2회 후 로그)
    scanner.py               초기 스캔: 감시 폴더 워크 → 캐시만 채움(전송 없음)
    watcher.py               observer + handler + debouncer + worker 배선
    main.py                  진입점: 설정 로드·검증 → 초기 스캔 → 감시 시작 → 상주
  tests/
```

- **언어/스택**: Python. watchdog(파일 이벤트), httpx(전송), ppdeep(서버와 동일 fuzzy),
  tomllib(설정, 표준 라이브러리). Windows 11 우선.
- **상태 파일 격리(자기 이벤트 방지)**: 캐시 SQLite·로그 파일은 **감시 폴더 밖**(client/
  디렉터리 또는 `%LOCALAPPDATA%/file-tracer-agent/`)에 둔다. 감시 폴더 안에 두면 자기
  쓰기가 자기 이벤트를 유발하는 루프가 생긴다.

## 4. 서버 계약 (고정 — 이미 구현됨)

`POST {server_url}/api/fingerprints`, `Content-Type: application/json` (모드 b):

```json
{
  "sha256": "...(필수)",
  "fuzzy_hash": "...(null 가능)",
  "size": 12345,
  "name": "secret.txt",
  "event_type": "created | modified | moved | deleted",
  "host": "PC-01",
  "user": "kim",
  "source_hint": "downloads | gdrive_sync | ... | null"
}
```

서버는 이를 `record_kind=event`로 저장하고 baseline과 매칭한다. **서버는 클라가 보낸
지문의 진위를 검증하지 않는다**(R8, 프로토타입 가정). `size`/`name` 누락은 서버가 조용히
기본값 처리하므로, **값의 정확성은 클라이언트 책임**이다.

## 5. 지문 동일성 계약 (중요)

클라가 보낸 지문이 서버 baseline(서버가 본문으로 계산)과 매칭되려면 **바이트 단위로
동일**해야 한다.

- 파일은 **반드시 `Path.read_bytes()`(바이너리)로 읽은 raw bytes**에서 지문을 계산한다.
  텍스트 모드·줄바꿈 변환(CRLF)이 끼면 SHA부터 어긋나 매칭 0건이 된다.
- `fingerprint.py`는 서버 `server/app/fingerprint.py`와 **동일 로직**: `hashlib.sha256`,
  `ppdeep.hash`. 빈 입력(0바이트)은 `fuzzy_hash=None`.

## 6. 이벤트 → 전송 파이프라인

1. watchdog가 `watch_paths`의 각 폴더를 **재귀 감시**한다.
2. 이벤트 발생 → `events.py` **필터**:
   - 디렉터리 이벤트 무시.
   - 임시파일 무시: `ignore_globs`(기본 `~$*`, `*.tmp`, `*.crdownload`, `*.part`).
   - 상태 파일(캐시/로그) 경로 무시(감시 폴더 밖이라 보통 해당 없음, 방어적으로).
3. 통과한 이벤트는 경로별 **디바운서**에 등록(기본 1.5초). 같은 경로의 연속 이벤트는
   타이머를 리셋해 1건으로 합쳐진다.
   - **event_type 병합 규칙**: 마지막 이벤트 우선. **단 발화 시점의 "파일 존재 여부"가
     최종 심판** — 존재하면 해싱(created/modified/moved), 없으면 캐시 지문으로 `deleted`.
4. 디바운스 발화 → **워커 큐에 작업 1건 enqueue**(경로 + 추정 event_type). 직접 해싱·전송
   하지 않는다.
5. **단일 워커 스레드**가 큐를 순차 소비:
   - **파일 존재** → `read_bytes()`로 해싱(열기 실패=잠금 시 1회 재큐) → `cache.put(path)` →
     event_type(created/modified/moved)으로 전송.
   - **파일 없음**(deleted) → `cache.pop(path)`로 기억된 지문을 꺼내 `deleted` 전송. 캐시에
     없으면(한 번도 못 본 파일) 스킵하고 로그.
   - **moved**: watchdog `FileMovedEvent`면 `cache.pop(src)` 후 dst를 위 "파일 존재" 경로로
     처리(dst 해싱·`cache.put(dst)`·`moved` 전송). 드라이브 간 이동은 OS가 deleted+created
     쌍으로 주므로 각각 위 규칙으로 처리된다(§10 한계).
6. **전송**(`sender.py`): JSON 모드 b. `host=socket.gethostname()`,
   `user=getpass.getuser()`, `source_hint`=경로 휴리스틱(Downloads / Google Drive /
   Dropbox / OneDrive 폴더명 매칭 시 채움, 아니면 null).

### 동시성 모델 (백프레셔)

- watchdog 콜백 스레드와 디바운스 타이머 스레드는 **작업을 큐에 넣기만** 한다.
- **워커 스레드 1개**가 해싱·전송을 순차 처리한다. 서버가 어차피 단일 락으로 직렬
  처리하므로 클라 병렬화는 무의미하고, 단일 워커가 **폭주 시 큐에 쌓아 순차 소화하는
  백프레셔**를 공짜로 제공한다(폴더째 붙여넣기 시연에도 안전).
- 공유 자료구조(디바운서 내부 dict)는 **락**으로 보호. 캐시 SQLite는 서버 repository와
  같은 `check_same_thread=False` + 락 패턴.

## 7. 초기 스캔 (콜드스타트 대응)

에이전트 시작 시 캐시는 비어 있다. 이 상태에서 기존 파일이 **수정 없이 바로 삭제**되면
캐시에 지문이 없어 삭제를 못 잡는다("기존 위험파일 반출"이 1순위 사건인데 빠짐).

- 시작 시 `scanner.py`가 `watch_paths`를 `os.walk`로 1회 훑어 각 파일을 해싱해
  **캐시에만 채운다(전송하지 않음)**. 시작마다 수천 건 POST하는 폭주를 피한다.
- 초기 스캔은 **observer를 시작하기 전에 동기로 1회** 수행하고 전송 단계를 건너뛴다.
  (observer 시작 전이라 스캔 중 들어온 이벤트와의 경합이 없다.)

## 8. 설정 (`config.toml`)과 검증

```toml
server_url = "http://127.0.0.1:8000"
debounce_seconds = 1.5
watch_paths = ["C:\\Secret", "C:\\Users\\me\\Desktop\\기밀"]
ignore_globs = ["~$*", "*.tmp", "*.crdownload", "*.part"]
```

- `config.py`가 시작 시 **검증, 실패 시 즉시 종료**(조용한 무수집 방지, 경계 입력 검증):
  - `server_url` 존재·형식.
  - `watch_paths` 비어있지 않음 + 각 경로가 **존재하는 디렉터리**.
  - `debounce_seconds` 양수.
- `debounce_seconds`는 주입 가능하게 설계(테스트는 0.1~0.2초).

## 9. 에러 처리

- 모든 예외는 **커스텀 예외**(예: `ConfigError`) + 구조적 로깅. bare except 금지.
- **해싱 중 파일 잠김/열기 실패** → 워커가 1회 재큐, 그래도 실패면 로그 후 스킵.
- **전송 실패(서버 다운 등)** → 짧은 재시도 2회 후 **로그만 남기고 진행**. 영속
  재전송 큐는 범위 밖(§2). 캐시는 그대로라 이후 삭제 추적엔 영향 없음.
- 의도적 묵살이 필요하면 변수명 `ignored` + 이유·날짜 주석(전역 code-style 규칙).

## 10. 검증

- **단위 테스트**:
  - `fingerprint`: 서버와 동일 값(같은 bytes → 같은 sha256·fuzzy_hash), 빈 입력 None.
  - `cache`: get/put/pop, 스레드 안전(락) 동작.
  - `events`: 임시파일·디렉터리 필터, watchdog 이벤트 → 내부 이벤트 매핑.
  - `debouncer`: 연속 이벤트 1건 합치기, deleted-승리 병합 — **시간 주입으로 결정적**.
  - `sender`: 모드 b 페이로드 형태(HTTP는 mock).
  - `config`: 잘못된 설정(없는 경로·빈 watch_paths) → ConfigError.
  - `scanner`: 초기 스캔이 캐시만 채우고 전송 안 함(sender mock 호출 0회).
- **통합 테스트**: 임시 폴더에 실제 watcher 띄워 파일 생성→수정→이동→삭제 시,
  sender(mock)에 올바른 event_type·지문 페이로드가 도달. **디바운스는 짧게(0.1s) 주입,
  대기는 폴링(조건 충족까지 최대 N초)으로** flaky 방지.
- **수동 E2E**: 구동 중인 서버 상대로 감시 폴더에 파일 넣고/고치고/지우고 → 서버
  `GET /api/fingerprints`·웹페이지에 event 레코드(host=내 PC)가 뜨면 성공. 같은 내용을
  서버에 baseline으로도 올려두면 exact 매칭으로 "트레이스"가 이어지는 것까지 확인.

## 11. 살아남은 한계 (인지하고 진행 — 프로토타입 범위 밖)

- 🔴 콜드스타트 외 **에이전트 꺼진 동안의 변경**: 초기 스캔은 시작 시점 스냅샷만 채운다.
  에이전트가 꺼져 있던 사이 생겼다 사라진 파일은 못 잡는다(설계 가정상 불가피).
- 🟡 **드라이브 간 이동(USB 등)**: OS가 `moved`가 아니라 deleted+created 쌍으로 준다.
  SHA가 같아 서버 매칭으로 이어지긴 하나 단일 moved로 잇지는 못한다.
- 🟡 watchdog Windows 한계: 긴 경로(>260)·네트워크(SMB) 드라이브는 이벤트 누락·지연
  가능. 프로토타입 `watch_paths`는 로컬 단경로 가정.
- 🟢 `source_hint` 휴리스틱은 폴더명 문자열 매칭이라 리네임·정크션에 빗나갈 수 있음
  (서버에선 nullable 확장 필드라 비치명적).
- (서버에서 이월된 한계 R1/R2/R4/R5/R7·프로세스 귀속 없음·서버의 클라 지문 미검증 R8은
  그대로 유효.)
