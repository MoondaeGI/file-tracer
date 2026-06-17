# Chrome Content Analysis Connector 셋업 가이드

file-tracer 브라우저 채널(upload/download/paste) 탐지를 위한 Chrome 정책 설정 및 전체 실행 절차.

> **한계 (반드시 읽을 것)**
> - Chromium 기반 **관리형** 브라우저 전용 (Chrome Enterprise / CBCM / GPO 환경).
>   개인 BYOD, Firefox, Edge 등은 이 커넥터로 잡히지 않는다.
> - **REPORT_ONLY** 모드 — 사용자 업로드/다운로드/붙여넣기를 **차단하지 않는다**.
>   탐지 기록용이며 fail-open(브리지/호스트 다운 시 사용자 작업은 그대로 진행).
> - **무손실 아님** — 호스트/서버 다운 중 이벤트는 드롭된다(로그만 남음).
>   무손실 outbox 버퍼는 다음 반복에서 구현 예정.
> - 비-Chromium 앱, 터미널, 네이티브 클라이언트(Dropbox 데스크톱 등)는 잡히지 않는다.
>
> 설계 §10 우려 전문: `docs/superpowers/specs/2026-06-17-exfiltration-detection-design.md` §10

---

## 아키텍처 요약

```
Chrome ──named pipe──> file_tracer_bridge.exe (C++)
          ① 즉시 ALLOW 응답
          ② loopback POST → http://127.0.0.1:8765/event
                                 ↓
                    Python 호스트 (client/main.py)
                    └ connector/agent.py: 지문 계산 + 매핑
                    └ core: TraceEvent → POST /api/fingerprints
                                 ↓
                    서버 (server/) → 대시보드 http://127.0.0.1:8000/
```

---

## 1. 전제 조건

- Windows 10/11
- 관리형 Chrome(정책 주입 가능) — 개인 Chrome은 정책이 먹히지 않는다
- C++ 브리지 빌드 완료 (`bridge/README.md` 참고)
- Python 호스트 의존성 설치 완료 (`.venv` 활성화 상태)

---

## 2. Chrome 정책 주입

Chrome Content Analysis Connector는 레지스트리 또는 GPO 정책으로 설정한다.

### 2a. 레지스트리 직접 설정 (테스트 환경 권장)

관리자 PowerShell에서 실행:

```powershell
# 정책 루트 경로
$root = "HKLM:\SOFTWARE\Policies\Google\Chrome"
New-Item -Path $root -Force | Out-Null

# ── 파일 업로드 감지 ─────────────────────────────────────────────────────────
$uploadPolicy = @'
[
  {
    "service_provider": "local_user_agent",
    "enable": [{"url_list": ["*"], "tags": ["dlp"]}],
    "default_action": "allow",
    "block_until_verdict": 0,
    "block_password_protected": false,
    "block_large_files": false
  }
]
'@
Set-ItemProperty -Path $root `
  -Name "OnFileAttachedEnterpriseConnector" `
  -Value $uploadPolicy

# ── 파일 다운로드 감지 ───────────────────────────────────────────────────────
$downloadPolicy = @'
[
  {
    "service_provider": "local_user_agent",
    "enable": [{"url_list": ["*"], "tags": ["dlp"]}],
    "default_action": "allow",
    "block_until_verdict": 0,
    "block_password_protected": false,
    "block_large_files": false
  }
]
'@
Set-ItemProperty -Path $root `
  -Name "OnFileDownloadedEnterpriseConnector" `
  -Value $downloadPolicy

# ── 붙여넣기 감지 ────────────────────────────────────────────────────────────
$pastePolicy = @'
[
  {
    "service_provider": "local_user_agent",
    "enable": [{"url_list": ["*"], "tags": ["dlp"]}],
    "default_action": "allow"
  }
]
'@
Set-ItemProperty -Path $root `
  -Name "OnBulkDataEntryEnterpriseConnector" `
  -Value $pastePolicy
```

> **`service_provider` 값 주의**: `"local_user_agent"` 는 예시이며,
> SDK의 실제 에이전트 등록 이름 및 `bridge_handler.cpp`의 `PIPE_NAME`과
> **반드시 일치**해야 한다. SDK 공식 문서에서 로컬 에이전트 이름 규칙을 확인하라.

### 2b. 정책 JSON 상세 설명

| 필드 | 설명 |
|---|---|
| `service_provider` | 로컬 에이전트 이름 (named pipe 이름과 연결됨) |
| `enable[].url_list` | 감시할 URL 패턴 (`"*"` = 전체) |
| `enable[].tags` | 감지 태그 (SDK 핸들러가 필터링에 사용 가능) |
| `default_action` | `"allow"` = REPORT_ONLY (차단 안 함) |
| `block_until_verdict` | `0` = 에이전트 응답을 기다리지 않음 (fail-open) |

### 2c. 정책 적용 확인

Chrome을 재시작한 뒤 주소창에:

```
chrome://policy
```

`OnFileAttachedEnterpriseConnector` 등 세 정책이 설정값으로 표시되면 성공이다.

### 2d. 정책 제거 (원상복구)

```powershell
$root = "HKLM:\SOFTWARE\Policies\Google\Chrome"
Remove-ItemProperty -Path $root -Name "OnFileAttachedEnterpriseConnector"   -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $root -Name "OnFileDownloadedEnterpriseConnector" -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $root -Name "OnBulkDataEntryEnterpriseConnector"  -ErrorAction SilentlyContinue
```

---

## 3. 실행 순서

각 단계를 **순서대로** 실행한다. 아래 명령은 사용자 확인 후 실행하라.

### 3-1. 서버 기동

```powershell
Set-Location "D:\기타 프로그램\file-tracer\server"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

대시보드: http://127.0.0.1:8000/

### 3-2. Python 호스트 기동 (FS agent + connector intake)

새 터미널:

```powershell
Set-Location "D:\기타 프로그램\file-tracer\client"
..\server\.venv\Scripts\python.exe -m main config.toml
```

`[INFO] 호스트 시작: FS 감시 + 커넥터 intake(:8765)` 로그가 뜨면 준비 완료.

### 3-3. C++ 브리지 실행

새 터미널 (관리자 권한 불필요, 단 Chrome 정책이 적용된 환경이어야 함):

```powershell
"D:\기타 프로그램\file-tracer\client\connector\bridge\build\Release\file_tracer_bridge.exe"
```

`[bridge] Chrome 이벤트 대기 중...` 이 뜨면 브리지가 파이프에서 대기 중이다.

> Chrome이 브리지 프로세스의 수명을 관리한다. Chrome 재시작 시 브리지를 다시 실행해야 할 수 있다.

### 3-4. Chrome 재시작

정책 적용 후 Chrome을 완전히 종료(`chrome://quit`)하고 다시 연다.
`chrome://policy` 에서 정책이 보이면 커넥터가 활성화된 상태다.

---

## 4. 수동 E2E 검증

### 4-1. 업로드 테스트

1. Chrome에서 https://drive.google.com 또는 임의 파일 업로드 사이트에 접속.
2. 파일을 선택해 업로드한다(실제 전송 전에 Chrome이 커넥터에 알림).
3. 대시보드 http://127.0.0.1:8000/ 에서 `event_type=upload` + 목적지 url이 표시되는지 확인.

### 4-2. 붙여넣기 테스트

1. Chrome에서 https://chat.openai.com 등 텍스트 입력 사이트 접속.
2. 텍스트를 붙여넣기한다(Ctrl+V).
3. 대시보드에 `event_type=paste` + url이 뜨는지 확인.

### 4-3. 기대 결과

| 확인 항목 | 기대값 |
|---|---|
| 대시보드 `event_type` 컬럼 | `upload` / `download` / `paste` |
| 대시보드 `목적지` 컬럼 | 업로드/다운로드한 사이트 URL |
| 사용자 업로드 차단 여부 | 차단 안 됨 (REPORT_ONLY) |
| 서버 로그 | `POST /api/fingerprints 200` |
| 호스트 로그 | `connector.agent: 매핑 성공` (또는 유사) |

### 4-4. 트러블슈팅

| 증상 | 원인 / 확인 |
|---|---|
| 대시보드에 이벤트 없음 | (1) 브리지 실행 여부, (2) 파이프명 불일치, (3) 호스트 포트 8765 점유 |
| `chrome://policy` 에 정책 안 보임 | 관리자 권한으로 레지스트리 설정, Chrome 완전 재시작 |
| 브리지가 즉시 종료됨 | SDK Agent 생성 실패 — 파이프명, SDK 빌드 확인 |
| `WinHttpConnect 실패` | Python 호스트(포트 8765)가 먼저 기동돼 있어야 함 |
| 이벤트는 오나 url이 없음 | `connector/agent.py`의 `mapping.py` MappingError — 호스트 로그 확인 |

---

## 5. 파일 구조 참고

```
client/connector/
  __init__.py
  agent.py          # Python: 지문 계산 + 매핑 + 코어 전송, loopback intake (POST /event)
  mapping.py        # Python: connector enum → event_type, 메타 추출 (순수 함수)
  errors.py         # Python: MappingError
  config.toml       # intake_port = 8765
  README.md         # ← 이 파일
  bridge/
    bridge_handler.cpp    # C++: Chrome pipe 수신 → ALLOW + loopback POST
    CMakeLists.txt        # 빌드 설정
    README.md             # 빌드 상세 가이드
    content_analysis_sdk/ # SDK clone 위치 (gitignore됨)
```
