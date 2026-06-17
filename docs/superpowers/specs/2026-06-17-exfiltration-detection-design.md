# file-tracer 외부 반출(exfiltration) 탐지 설계 (브라우저 채널 1차)

- 작성일: 2026-06-17
- 상태: 승인됨 (구현 계획 단계로 진행)
- 선행 논의: `personal:idea` 라운드(devils-advocate 2회) → `superpowers:brainstorming`
- 브랜치: `feat/exfiltration-detection`

---

## 1. 목적과 포지셔닝

기존 file-tracer는 지정 폴더의 **파일시스템 이벤트**(생성/수정/이동/삭제)만 감지한다.
그래서 두 가지 사각지대가 있다: (a) 감시 폴더 밖으로의 이동은 `deleted`로만 보이고,
(b) **업로드**(파일을 read해서 네트워크로 보냄)는 파일시스템 이벤트를 만들지 않아 완전히
장님이다.

이 단계의 목표는 **브라우저를 통한 외부 반출을 event_type으로 포착**하는 것이다 —
구체적으로 `upload`/`download`/`paste` 이벤트를 잡아 기존 지문 파이프라인(서버 매칭·
대시보드)에 흘려보낸다. 포지셔닝은 기존과 동일하게 **"법적 증거"가 아니라 "억지·감사
도구"**이며, 무손실·실시간 차단을 보장하지 않는다.

### 이번 단계 성공 기준 (가설 검증 데모)

`upload`/`download`/`paste` 신규 event_type이 **실제로 잡혀서 → 서버로 전송 → 대시보드
표에 url과 함께 뜬다**까지를 한 번 보여주면 성공이다. 차단(BLOCK)·무손실·USB·네이티브
정식화는 범위 밖(§9 이월).

---

## 2. 채택·기각된 접근 (idea 라운드 결론)

### 기각

- **"패킷/소켓에서 파일을 식별"** — 사실관계로 거짓 확인. OS connection table(소위
  socket table)은 PID·IP·포트·방향만 주고 파일 내용·이름은 담지 않으며, HTTPS면 어차피
  암호화(ciphertext)다. "TLS 직전 application layer 후킹으로 파일 식별"도 앱별 무한
  유지보수 표면 + "TLS 직전"과 "파일 식별"이 같은 지점에서 동시에 성립하지 않는 자기모순
  으로 기각.

### 채택

- **브라우저 채널 = Chrome Enterprise Content Analysis Connector.** 공식 오픈소스
  `chromium/content_analysis_sdk`. 관리형 Chrome이 업로드/다운로드/붙여넣기 **직전에**
  `{filename, digest(SHA256), file_path(본문), 목적지 url, 로그인 email, 동작종류}`를
  로컬 에이전트(named pipe)에 직접 넘긴다 → correlation 추정 없이 완결. 단 Chromium·
  관리형 브라우저 한정.
- **응답은 REPORT_ONLY**(항상 allow, 기록만). 사용자 작업을 막지 않고, Chrome
  Enterprise Premium·오탐 리스크를 피한다.
- **내용은 지문만 서버로.** 파일 본문·paste 원문은 **로컬 구간에서만** 지문(SHA256+
  ssdeep)으로 변환된 뒤 폐기. 서버로는 지문+메타만 나간다(기존 모드 b 계약과 일치).

### 추후 (이번 범위 밖)

- USB·이동식 매체(`usb_copy`) — 엔드포인트 FS/디바이스 미니필터.
- SaaS API/webhook(Drive Activity·Gmail) — 회사 테넌트 한정 보조 신호(외부 공유 전환 등).
- 차단(BLOCK), 무손실(outbox 버퍼), C++ 정식 에이전트 이식.

---

## 3. 아키텍처 (2프로세스 모델)

```
[프로세스 1: Python 에이전트 호스트]  ← 하나만 실행
   ├ agent (FS 수집 스레드, cache.db 단독 소유) ─┐
   ├ connector intake (스레드)                   ─┼─> core ─POST─> [서버]
   └ core: 큐 + Sender (egress 단독)   ─┘   (단일 egress·순서·재시도)
        ▲ loopback (JSON)
[프로세스 2: C++ 브리지]  ← Chrome이 띄움 (불가피)
   Chrome ─named pipe─> bridge ─loopback─> 호스트의 connector intake
```

- **꼭 별도 프로세스여야 하는 건 C++ 브리지 하나뿐**(Chrome이 수명을 쥠). 나머지(FS
  수집·커넥터 지문·코어 egress)는 전부 Python이라 **한 프로세스 안 스레드/모듈**로 합친다.
- **코드 경계는 모듈로 유지, 런타임은 한 지붕.** "모듈은 격리, 프로세스는 통합."
- SQLite는 `cache.db`(FS agent 단독 소유) 하나뿐 → 다중 프로세스 락 경합 없음. 코어
  outbox(오프라인 버퍼)는 인터페이스만, 구현은 추후(YAGNI).

### 데이터 흐름

```
Chrome ──pipe──> bridge(C++)
   ① 즉시 ALLOW 응답 (REPORT_ONLY — 사용자 작업 안 막음, fail-open)
   ② ContentAnalysisRequest의 raw 필드를 loopback JSON으로 connector intake에 fire-and-forget
        ▼
connector/agent.py
   · 지문 계산: 파일이면 file_path read→SHA256+ssdeep / paste면 text→지문 (원문 폐기)
   · mapping.py: analysis_connector → event_type, 메타 추출
   · TraceEvent 생성 → core로 전송
        ▼
core
   · TraceEvent를 모드 b JSON으로 직렬화 → 기존 Sender로 POST /api/fingerprints
        ▼
서버: event 기록(해시체인) + web_event_detail 저장 + baseline 자동 매칭 → 대시보드
```

**핵심 결정 2가지:**

1. **응답과 처리의 분리(비동기)** — 브리지는 Chrome에 즉시 ALLOW를 돌려주고, 지문·전송
   이라는 무거운 일은 임계 경로 밖에서 비동기로 한다. 사용자 업로드가 우리 처리 때문에
   지연되지 않는다.
2. **본문의 경계** — 파일 본문/paste 원문은 **브리지→Python 로컬 구간까지만** 흐르고,
   거기서 지문으로 변환된 뒤 폐기. 서버로는 지문+메타만 나간다. → "감청 리스크가 한
   단계 높다"는 우려를 *본문이 로컬 프로세스 밖으로 안 나간다*로 봉쇄.

---

## 4. 클라이언트 모듈 구조

```
client/
  common/                  공유 코어 라이브러리 (수집기들이 의존)
    fingerprint.py         ← agent/에서 이동 (SHA256+ssdeep, bytes/경로 둘 다 지원)
    events.py              ← 공유 event_type 상수 + TraceEvent 정의
  core/          서버 egress 단독 소유
    core.py                로컬 intake(수신) → 큐 → 서버 단일 전송 (Sender 소유)
    sender.py              ← agent/에서 이동 (+ per-event user override)
    config.toml            server_url, intake_port
  agent/                   FS 수집기 (cache.db 단독 소유)
    watcher/worker/debouncer/cache/scanner/config/models/events …
    → 완성된 TraceEvent를 코어로 전송 (직접 서버 전송 폐기)
  connector/               브라우저 수집기 (DB 없음)
    bridge/                C++ (SDK 데모 에이전트 fork)
      main.cpp             Chrome 파이프 수신 → 즉시 ALLOW → loopback 전달
      CMakeLists.txt
    agent.py               지문 + 매핑 → TraceEvent → 코어 전송
    mapping.py             순수 함수: 요청 → (event_type, 메타)
    config.toml            intake_port, core endpoint
    README.md
  tests/
```

### 공유 코드 추출 (기존 코드 리팩터링 — 구현 Task 1)

- `agent/fingerprint.py` → `common/fingerprint.py` (그대로 이동, 진짜 공유).
- `agent/sender.py` → `core/sender.py` (이동 + `send(..., user=None)` 선택
  인자 추가 — 커넥터는 이벤트마다 user=Chrome email이 다름; host는 그대로 호스트명).
- event_type 상수 + `TraceEvent`를 `common/events.py`로.
- **남기는 것:** `agent/models.py`의 `Pending`·`Task`·`CachedFingerprint`·`Config`는
  FS 파이프라인 전용이라 `agent/`에 둔다. `agent/events.py`의 `should_ignore`(임시파일
  필터)도 FS 전용이라 남긴다.
- 기존 `agent/` 테스트의 import 경로를 갱신하고, **기존 테스트 전부 그린 유지**가 이
  리팩터링의 합격 기준이다.

### 단일 책임 경계

| 단위 | 하는 일 | 모르는 것 |
|---|---|---|
| `bridge` (C++) | Chrome 파이프 수신 → ALLOW + loopback 전달 | 지문·서버 |
| `mapping.py` | 요청 dict → event_type·메타 변환 (순수) | 네트워크·파일 |
| `connector/agent.py` | 수신·조율: 지문+매핑+전송 엮기 | 파이프 프로토콜 |
| `core` | TraceEvent 받아 순서대로 서버로 | 채널·지문 |

---

## 5. 이벤트 구조화

### 5.1 홉 1: C++ 브리지 → connector intake (loopback, JSON)

브리지는 **지문을 안 만들고** raw 필드만 평평하게 전달한다 (파일은 경로만, paste는 텍스트
포함 — 둘 다 로컬 구간):

```json
{
  "request_token": "abc123",
  "connector": "FILE_ATTACHED",        // FILE_DOWNLOADED | BULK_DATA_ENTRY
  "filename": "설계도.dwg",             // paste면 빈 값
  "digest": "a3f9…",                    // Chrome이 준 SHA256 (폴백용)
  "file_path": "C:\\Users\\…\\upload.tmp",  // 파일 이벤트만
  "text_content": "…",                  // paste만 (원문, 로컬에서만)
  "url": "https://drive.google.com/…",
  "email": "kim@corp.com",
  "tab_title": "Drive"
}
```

### 5.2 홉 2: 정규화된 `TraceEvent` (공통 계약 — 모든 수집기가 emit)

```python
# common/events.py
@dataclass(frozen=True)
class TraceEvent:
    sha256: str
    fuzzy_hash: str | None
    size: int
    name: str
    event_type: str          # created/modified/… | upload/download/paste
    host: str
    user: str | None
    source_hint: str | None   # FS=경로 힌트(기존 의미 유지), 커넥터=None
    metadata: dict | None     # event_type별 부가정보 (wire 전용 유연 컨테이너)
```

FS agent도 같은 `TraceEvent`를 emit한다 → 코어는 한 종류만 안다.

### 5.3 event_type 매핑 & metadata 관례

| 커넥터 `analysis_connector` | event_type | 본문 출처 | metadata |
|---|---|---|---|
| `FILE_ATTACHED` | `upload` | `file_path` | `{url, dst_host, tab_title}` (url 필수) |
| `FILE_DOWNLOADED` | `download` | `file_path` | `{url, dst_host, tab_title}` (url 필수) |
| `BULK_DATA_ENTRY` | `paste` | `text_content` | `{url, dst_host, tab_title}` (url 필수) |
| `moved` (FS) | `moved` | (기존) | `{moved_from}` |
| `created/modified/deleted` (FS) | (기존) | (기존) | `null` 허용 |

메타 추출: `name`=filename이 있으면 filename, 없으면(paste) 고정 문자열
`"(pasted text)"`. `user`=email, `host`=`gethostname()`.

### 5.4 모드 b JSON (wire — 기존 계약 + metadata)

```json
{ "sha256":"a3f9…", "fuzzy_hash":"48:…|null", "size":48210, "name":"설계도.dwg",
  "event_type":"upload", "host":"PC-01", "user":"kim@corp.com", "source_hint":null,
  "metadata": { "url":"https://drive.google.com/…", "dst_host":"drive.google.com",
                "tab_title":"Drive" } }
```

---

## 6. 지문 처리

`common/fingerprint.py` 재사용. baseline(서버가 본문으로 계산한 것)과 **동일 로직**이라
정확 매칭된다.

- **파일(upload/download)**: `file_path`를 raw bytes로 읽어 `fingerprint_file()` →
  SHA256+ssdeep+size. 커넥터가 준 `digest`는 교차검증/폴백용(정상 경로는 로컬 재계산 —
  ssdeep도 필요하므로).
- **paste**: `text_content.encode()` → `compute_sha256` + `compute_fuzzy`. 원문은 지문
  생성 후 즉시 폐기. 짧은 텍스트는 ppdeep이 지문을 못 만들어 `fuzzy_hash=null` → SHA
  exact 매칭만 가능(기존 null-fuzzy 처리와 동일).

---

## 7. 서버 변경 (정규화 저장)

기존 서버 API 계약(`POST /api/fingerprints` 모드 b)은 유지하되, **정규화 detail 테이블**과
metadata 처리를 추가한다.

### 7.1 스키마: 채널별 detail 테이블

`upload`/`download`/`paste`는 모두 브라우저 채널이라 url·dst_host를 공유 → 테이블 하나로
묶는다(event_type마다 따로 만들지 않음). **DB에는 JSON 컬럼을 두지 않는다** — 전부 타입
컬럼(1NF 유지).

```sql
CREATE TABLE IF NOT EXISTS web_event_detail (
  event_id  INTEGER PRIMARY KEY REFERENCES event(id),  -- 1:0..1, event당 최대 1행
  url       TEXT NOT NULL,
  dst_host  TEXT,
  tab_title TEXT
);
```

향후 USB는 `usb_event_detail`(volume_label·drive_letter 등) 자기 테이블을 가진다 → 패턴
일관, 코어 무변경.

### 7.2 저장 흐름

- `EventInput`에 `metadata: dict | None` 추가(wire 수신용).
- `_handle_mode_b`: `add_event` 후, event_type이 브라우저 채널이면 `metadata`에서
  url/dst_host/tab_title을 꺼내 `web_event_detail`에 INSERT(같은 처리 흐름).
- **검증(시스템 경계):** 브라우저 event인데 `metadata.url`이 없으면 클라 `mapping.py`
  에서 빠르게 실패(불완전 이벤트는 서버로 안 보냄). 서버는 받은 값을 저장.
- `EVENT_TYPES` 상수에 `upload`/`download`/`paste` 추가(현재 `RESERVED_EVENT_TYPES`의
  upload/download를 승격). 서버 api는 event_type을 문자열로 받으므로 매칭 로직 변경은 없음.

### 7.3 해시체인

`event_payload`에 **url·dst_host를 포함**한다 — "어디로 보냈나"는 audit 핵심이라
변조탐지 대상. side table에 저장돼도 event 삽입 시점에 값이 있으니 체인 계산에 넣는다.
url이 변조되면 체인이 깨진다.

### 7.4 조회·대시보드

- `GET /api/events`: `event LEFT JOIN web_event_detail` → 응답에 url·dst_host 포함.
- 대시보드 event 표에 `upload`/`download`/`paste` + 목적지 url + 최고 매칭 표시.

---

## 8. 에러 처리

전역 코드스타일(모든 레벨 명시적 처리·상세 로깅) 준수.

| 지점 | 실패 | 대응 |
|---|---|---|
| Chrome → 브리지 | 브리지 크래시·파이프 끊김 | Chrome 커넥터 정책 `default_action=allow`(fail-open) → 사용자 작업 안 막힘. 그 구간 이벤트는 미수집(로깅) |
| 브리지 → intake | Python 호스트 다운 | 브리지는 이미 Chrome에 ALLOW 응답. 전달 실패 시 로그만, 이벤트 유실(프로토타입 수용; outbox는 추후) |
| file_path 읽기 | 파일 잠김·이동/삭제 | 기존 `OSError` 처리 → Chrome `digest`로 폴백(`fuzzy_hash=null`). digest도 없으면 스킵+경고 |
| paste 텍스트 | 짧음/빈 값 | `fuzzy_hash=null`, SHA만 계산. 완전 빈 값이면 스킵 |
| mapping 검증 | 브라우저 event인데 url 없음 | 경계에서 빠른 실패 → 드롭+로그 |
| 코어 → 서버 | 서버 다운·5xx | 기존 `Sender` 재시도(2회)+로그. 소진 후 드롭+에러로그(outbox 추후) |
| 수집기 스레드 | 처리 중 예외 | 기존 `worker._run` 태스크별 try/except 패턴을 코어·connector 루프에도 적용 |

**원칙:** (1) 브리지는 절대 다운스트림을 기다리지 않는다(Chrome에 즉시 ALLOW, fail-open).
(2) 프로토타입은 "유실 허용 + 로깅" — 조용한 누락 금지. 무손실(outbox)은 다음 반복.

---

## 9. 테스트 전략 & 환경 셋업

**핵심 이점:** 브리지→connector 홉이 평범한 JSON(loopback)이라, **실제 Chrome 없이**
시뮬레이션된 커넥터 요청을 POST해 Python 파이프라인 전체를 자동 테스트할 수 있다. 실
Chrome은 최종 수동 E2E에만 필요 → TDD 가능. 각 단위는 실패 테스트 → 구현 순(전역 규칙).

### 단위 테스트
- `mapping.py`: 요청 dict → `TraceEvent` (event_type 3종, metadata 추출, url 누락 시 빠른 실패)
- 서버 `repository`: `web_event_detail` insert/read, LEFT JOIN
- 서버 `chain`: metadata(url) 포함 → url 변조 시 체인 깨짐 탐지
- 서버 `api` 모드 b: metadata를 `web_event_detail`로 라우팅, `GET /api/events`가 url 반환
- `core`: 큐→전송 (FakeSender 주입)

### 통합 테스트
- `connector/agent.py`: 시뮬레이션 브리지 JSON loopback POST → 지문+매핑 후 TraceEvent emit
- Python 내 E2E: 브리지 JSON → connector → core → 서버(TestClient) → `GET`에 url 달린
  upload 이벤트 (실 Chrome 비의존)

### 수동 E2E (실 Chrome 필요 — 환경 전제)
1. C++ 브리지 빌드(SDK 데모 + 최소 개조; CMake + MSVC).
2. 관리형 Chrome 정책 주입 — `HKLM\SOFTWARE\Policies\Google\Chrome\`에
   `OnFileAttachedEnterpriseConnector`·`OnFileDownloadedEnterpriseConnector`·
   `OnBulkDataEntryEnterpriseConnector` 각각 `service_provider`=로컬 에이전트 + 파이프명 +
   `default_action=allow`. (SDK 파이프명과 정책의 에이전트명 일치 필요)
3. 테스트 사이트에 실제 업로드 → 대시보드에 url 달린 `upload` 이벤트 확인.

> 정책 셋업은 코드가 아니라 테스트 환경 전제다. `connector/README.md`에 셋업 절차를 둔다.

---

## 10. 살아남은 우려 (인지하고 진행 — 프로토타입 범위 밖/명시)

- 🔴 **채널 커버리지 구멍**: 비-Chromium 앱·네이티브 앱(개인 Dropbox 데스크톱 등)·관리
  안 된 브라우저·USB·터미널은 커넥터로 안 잡힌다. 부분 커버리지가 "안전하다"는 거짓
  안심을 줄 수 있음 → 유실·미수집을 로그로 드러내고, "이 프로토타입은 무손실·전채널
  아님"을 대시보드/문서에 명시.
- 🟡 **관리형 브라우저 전제**: 커넥터는 Chrome 정책 주입(CBCM/GPO) 필요. 개인 BYOD엔 안 붙음.
- 🔴 **법적(통신·근로 감시)**: paste 원문·업로드 본문에 접근하는 것은 기존 FS 지문보다
  감청 리스크가 한 단계 높다. 본문이 로컬 프로세스 밖으로 안 나가는 설계로 완화하나,
  실제 배포 시 법무·노사 검토 필요(기존 §10과 동일 강도 이상).
- 🟡 **무손실 아님**: 호스트/서버 다운 중 이벤트 드롭(로깅만). outbox 버퍼는 다음 반복.
- 🟡 **라이선스**: 차단(BLOCK)은 Chrome Enterprise Premium 필요할 수 있음. 이번엔
  REPORT_ONLY라 의존 낮음 — 차단으로 확장 시 재확인 필요.
- 🟡 **언어·통합 점프**: C++ 브리지는 별도 빌드(MSVC/CMake). 추후 Python 이식 또는 C++
  정식화는 별도 반복.
- 🟢 **모드 b 지문 신뢰 한계(R8)**: 기존과 동일 — 신뢰 로컬 환경 가정.

---

## 11. 구현 순서 (writing-plans에서 상세화)

1. 공유 코드 추출: `common/`·`core/` 신설, fingerprint·sender 이동, 기존
   agent 테스트 그린 유지.
2. `common/events.py`: `TraceEvent` + event_type 상수.
3. 서버: `web_event_detail` 테이블 + `EventInput.metadata` + 모드 b 라우팅 + 체인 포함 +
   GET 조회 (TDD).
4. `core`: intake + 큐 + Sender egress (TDD).
5. `connector/mapping.py`: 매핑·검증 순수 함수 (TDD).
6. `connector/agent.py`: 지문+매핑+코어 전송, loopback intake (TDD, 실 Chrome 비의존).
7. C++ 브리지: SDK 데모 fork, ALLOW + loopback 전달.
8. FS agent를 코어 경유로 이주.
9. 대시보드 갱신(url 표시) + 수동 E2E 셋업 문서.
