# file-tracer 서버 스키마 정식화 설계

- 작성일: 2026-06-10
- 상태: 승인됨 (구현 계획 단계로 진행)
- 선행: 서버 프로토타입(`2026-06-09-...`)·클라이언트 프로토타입(`2026-06-10-client-...`) 완성 → 사용자와 스키마 대화로 엔티티·관계 확정 → `brainstorming`

---

## 1. 목적

프로토타입의 납작한 단일 `records` 테이블(baseline/event를 `record_kind`로 구분)을
**정규화된 관계형 스키마**로 교체한다. 매칭 이력(trace_match)·baseline 버전 이력
(update_history)을 제대로 담아, "위험파일이 어느 PC에 어떻게 퍼졌나" 대시보드의
데이터 토대를 만든다.

이번 범위는 **서버 스키마와 서버 로직만**이다. 클라이언트는 서버 API 계약
(`POST /api/fingerprints` 모드 b)이 그대로라 **변경하지 않는다**.

## 2. 범위

### 포함
- 서버 SQLite 스키마 4개 테이블: `supervise_file`·`update_history`·`event`·`trace_match`.
- 모드 a(파일 업로드)→baseline 등록·버전 이력, 모드 b(클라 JSON)→이벤트 기록·자동 매칭.
- `event` 테이블에 한정한 append-only 해시체인.
- 대시보드용 읽기 엔드포인트.
- `repository.py`를 SQLite 단일 구현으로 단순화(테스트는 `:memory:`).

### 제외 (이월/범위 밖)
- 클라이언트 로컬 `event` 로그 테이블 — 목적(로컬 감사/재전송)이 약해 보류, 필요 시 후속.
- `copy`/`upload`/`download` event_type — 예약 enum만(로직 없음). 클라가 현재 만드는 건
  created/modified/moved/deleted뿐(R7: 파일 레이어로 다운/업/복사 구분 불가).
- 웹 대시보드 고도화, 인증(무인증 GET은 의도적 이월, 서버 프로토타입 §10 유효).
- 기존 `records` 데이터 마이그레이션 — 데모 데이터라 버리고 새로 만든다.

## 3. 스키마 (SQLite)

```sql
CREATE TABLE supervise_file (        -- 추적 대상 baseline(위험파일)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,                -- baseline 식별 키(재업로드 판정용)
  sha256 TEXT NOT NULL,
  fuzzy_hash TEXT,
  size INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE update_history (        -- baseline 갱신 시 '옛 버전' 스냅샷 (1:N)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supervise_file_id INTEGER NOT NULL REFERENCES supervise_file(id),
  sha256 TEXT NOT NULL,
  fuzzy_hash TEXT,
  size INTEGER NOT NULL,
  replaced_at TEXT NOT NULL
);

CREATE TABLE event (                 -- 클라가 올린 감시 이벤트 (append-only + 체인)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT NOT NULL,
  fuzzy_hash TEXT,
  size INTEGER NOT NULL,
  name TEXT NOT NULL,
  host TEXT,
  user TEXT,
  event_type TEXT NOT NULL,          -- created|modified|moved|deleted (예약: copy|upload|download)
  detected_at TEXT NOT NULL,         -- 서버가 찍는 수신 시각(UTC)
  source_hint TEXT,
  prev_hash TEXT,                    -- 직전 event의 record_hash
  record_hash TEXT NOT NULL          -- 이 event 정규화 직렬화 해시
);

CREATE TABLE trace_match (           -- event ↔ supervise_file 일치 결과
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES event(id),
  supervise_file_id INTEGER NOT NULL REFERENCES supervise_file(id),
  match_type TEXT NOT NULL,          -- exact|fuzzy
  similarity INTEGER NOT NULL,       -- 0~100
  matched_at TEXT NOT NULL
);
```

- 전 관계 1:N/N:1 (M:N 정크션 없음).
- `sha256`+`fuzzy_hash`는 지문 보유 테이블 모두에 둔다(sha256=정확 신원, fuzzy=유사도).
- 체인 컬럼(`prev_hash`/`record_hash`)은 `event`에만. 나머지 테이블은 가변/보조라 체인 없음.

## 4. 쓰기 흐름

### 4.1 모드 a — `POST /api/fingerprints` (multipart 파일)
baseline 등록·갱신. 서버가 파일 바이트를 읽어 지문 계산(raw bytes).

1. 같은 `name`의 `supervise_file`이 **없으면** → 새 행 insert(`created_at`=`updated_at`=now).
2. **있으면** → 옛 행의 `sha256/fuzzy_hash/size`를 `update_history`에 스냅샷(`replaced_at`=now)
   → `supervise_file` 행을 새 지문으로 UPDATE(`updated_at`=now). (`id` 유지)
3. 응답: 등록된/갱신된 `supervise_file`(id·name·sha256·fuzzy_hash·size)과 `was_update`
   불리언(신규 등록인지 기존 갱신인지). 다른 baseline과의 매칭은 모드 a 응답에 넣지
   않는다(매칭은 모드 b 이벤트의 역할 — 역할 분리).

### 4.2 모드 b — `POST /api/fingerprints` (application/json)
클라 이벤트 기록 + 자동 트레이스. 입력 필드는 서버 프로토타입 계약 그대로
(`sha256` 필수, `fuzzy_hash`/`size`/`name`/`event_type`/`host`/`user`/`source_hint`).

1. `event` insert: `detected_at`=서버 now, 체인 이어붙임(직전 event의 record_hash를
   `prev_hash`로, 정규화 직렬화 해시를 `record_hash`로).
2. 모든 `supervise_file`과 매칭(`matching.py` 재사용: SHA 동일=exact(100), 아니면
   ssdeep 유사도 ≥50=fuzzy).
3. 매칭마다 `trace_match` insert(`event_id`·`supervise_file_id`·`match_type`·`similarity`).
4. 응답: 매칭 목록(클라는 로그만, 웹·디버깅용).

## 5. 읽기 API (대시보드)

- `GET /api/supervise-files` — baseline 목록. 각 항목에 `update_history` 건수 포함.
- `GET /api/events` — 이벤트 목록(최근 N개). 각 이벤트에 trace_match 요약(최고 similarity·
  매칭된 baseline name) 포함.
- 기존 `GET /api/fingerprints`는 폐기하고 위 둘로 대체. `static/index.html`은 새 GET에
  맞춰 표 두 개(baseline / event+매칭)로 소폭 갱신.

## 6. 코드 변경 (server/app/)

- **`models.py`** — `Record`/`FingerprintInput`/`MatchResult`를 폐기하고 frozen dataclass
  4종으로 교체: `SuperviseFile`·`UpdateHistory`·`Event`·`TraceMatch`(+입력용 경량 모델).
- **`repository.py`** — `Repository`(ABC)·`InMemoryRepository` 폐기, **`SqliteRepository`
  단일 구현**. 테스트는 `SqliteRepository(":memory:")`로 빠르게. 메서드:
  `register_supervise_file(name, fp, now) -> (SuperviseFile, was_update: bool)`,
  `add_event(event_input, now) -> Event`(체인 포함), `add_trace_matches(event_id, matches)`,
  `list_supervise_files()`, `list_events(limit)`, `list_update_history(supervise_file_id)`,
  `all_events()`(체인 검증용).
- **`matching.py`** — baseline 목록 대상 exact/fuzzy 로직 재사용. 결과를 `trace_match`
  행으로 변환하는 얇은 어댑터만 추가.
- **`chain.py`** — `event` 레코드 대상으로 payload 필드 갱신(event 컬럼들). `verify_chain`은
  `event` 목록을 받는다.
- **`api.py`** — 모드 a/b 분기를 위 4.1/4.2 흐름으로, 신규 GET 2개. `constants.py`에
  event_type 상수·예약값, fuzzy 임계치 유지.
- **`errors.py`** — 기존 HttpError 계층 재사용.

## 7. 테스트

- **단위**: repository 각 메서드(supervise_file 등록·재업로드 스냅샷, event 추가+체인,
  trace_match 자동 생성), matching→trace_match 변환, chain(event 대상 변조 탐지).
- **통합(API, TestClient + `:memory:`)**:
  - 모드 a 신규 → supervise_file 1행, update_history 0행.
  - 모드 a 같은 name 재업로드 → update_history 1행 스냅샷 + supervise_file 갱신.
  - 모드 b 이벤트 → event 1행 + (baseline 매칭 시) trace_match insert + 응답 매칭.
  - event 여러 건 → 체인 정상, 한 건 변조 시 검증이 깨진 지점 반환.
  - GET supervise-files / events 형태.
- **검증 시나리오 재현**: 클라 E2E에서 본 created/modified/deleted 이벤트가 새 스키마의
  event+trace_match로 들어가는지(서버 단독 통합 테스트로).

## 8. 살아남은 한계 (인지하고 진행)
- 서버 프로토타입의 R1/R2/R4/R5/R7·R8(클라 지문 미검증)·무인증 GET·해시체인 의도적
  전체 재작성 한계는 그대로 유효.
- ssdeep 블록 크기 민감성 유효.
- `name` 기반 baseline 식별: 서로 다른 위험파일이 같은 파일명을 쓰면 충돌(프로토타입
  한계, 향후 명시적 target id로 보완).
