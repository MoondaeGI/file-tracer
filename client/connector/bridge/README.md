# file-tracer C++ 브리지 빌드 가이드

Chrome Content Analysis Connector용 C++ 브리지.
Chrome이 named pipe로 보내는 ContentAnalysisRequest를 받아 **즉시 ALLOW 응답**하고,
요청 메타데이터를 `http://127.0.0.1:8765/event` 로 비동기 POST해 Python 호스트에 전달한다.

> **자동 테스트 없음**: 이 브리지는 실제 Chrome(관리형) 환경에서만 검증 가능하다.
> Python 파이프라인(`connector/agent.py` → `core` → 서버)은 Task 1~12에서 이미 자동 검증됨.

---

## 전제 조건

- Windows 10/11
- Visual Studio 2022 (MSVC v143, C++17)
- CMake 3.20 이상
- Git
- 관리형 Chrome (Chromium 기반, 정책 주입 가능한 환경) — 수동 E2E에만 필요

---

## 1단계: content_analysis_sdk clone

SDK를 **이 디렉터리(`client/connector/bridge/`) 안에** clone한다.

```powershell
Set-Location "client/connector/bridge"
git clone https://github.com/chromium/content_analysis_sdk content_analysis_sdk
```

clone 후 디렉터리 구조:

```
client/connector/bridge/
  content_analysis_sdk/     ← SDK 저장소
    agent/                  ← Agent C++ 인터페이스
    demo/                   ← 데모 에이전트 (참고용)
    proto/
      content_analysis/
        sdk/
          analysis.proto    ← 메시지 스키마 (ContentAnalysisRequest/Response)
    CMakeLists.txt
  bridge_handler.cpp        ← 우리 핸들러
  CMakeLists.txt
  README.md
```

> `content_analysis_sdk/` 디렉터리는 `.gitignore`에 등록돼 있으므로 커밋되지 않는다.

---

## 2단계: SDK API 확인 (중요)

`bridge_handler.cpp`의 SDK 호출부(`※` 주석)는 공식 저장소 기준 **추측**이다.
빌드 전 반드시 아래 파일들과 대조하라:

| 확인 항목 | 참고 파일 |
|---|---|
| `Agent::Config` 구조체·필드명 | `content_analysis_sdk/agent/` 헤더 |
| `Agent::Create` / 핸들러 시그니처 | `content_analysis_sdk/demo/agent/` |
| `ContentAnalysisRequest` getter명 | `content_analysis_sdk/proto/.../analysis.proto` |
| ALLOW 응답 구성 방식 | `content_analysis_sdk/demo/agent/main.cc` |
| SDK CMake 타겟명 | `content_analysis_sdk/CMakeLists.txt` |

특히 **demo/agent/main.cc**는 데모 에이전트의 핸들러 패턴을 그대로 보여주므로,
`bridge_handler.cpp`의 `make_allow_response`와 `main()` 안 Agent 초기화 부분을
데모와 대조해 조정하라.

---

## 3단계: CMake 빌드

```powershell
# client/connector/bridge/ 에서 실행
New-Item -ItemType Directory -Force build
Set-Location build

cmake .. `
  -G "Visual Studio 17 2022" `
  -A x64 `
  -DCA_SDK_SRC_DIR="$((Get-Location).Path)/../content_analysis_sdk"

cmake --build . --config Release
```

SDK 경로가 다르면 `-DCA_SDK_SRC_DIR=<절대경로>` 로 지정한다.

빌드 성공 시 실행 파일 위치:

```
client/connector/bridge/build/Release/file_tracer_bridge.exe
```

### 빌드 오류 체크리스트

| 증상 | 원인 / 해결 |
|---|---|
| `content_analysis_sdk/CMakeLists.txt` not found | SDK clone 경로가 잘못됨 — `CA_SDK_SRC_DIR` 재지정 |
| `content_analysis/sdk/analysis_client.h` not found | SDK include 경로 불일치 — `CMakeLists.txt`의 `target_include_directories` 조정 |
| `content_analysis_sdk` 링크 타겟 없음 | SDK가 노출하는 타겟명 확인 후 `CMakeLists.txt` 수정 |
| proto 헤더(`analysis.pb.h`) 없음 | SDK 빌드 시 protobuf 코드 생성 경로 확인 |
| `Agent::Create` 컴파일 오류 | SDK API 시그니처 변경 — demo/agent 참고 후 `bridge_handler.cpp` 조정 |

---

## 4단계: 파이프명 설정

`bridge_handler.cpp`의 `PIPE_NAME` 상수와 Chrome 정책의 에이전트 이름이 **반드시 일치**해야 한다.

```cpp
// bridge_handler.cpp:
static const char* PIPE_NAME = "file_tracer_agent";  // ← 이 값이 정책과 일치해야 함
```

`connector/README.md`의 Chrome 정책 JSON에서 `service_provider` 값을 이 이름으로 맞춰라.

---

## SDK ContentAnalysisRequest/Response 주요 필드 참고

`proto/content_analysis/sdk/analysis.proto` 기준 (실제 파일에서 최종 확인 권고):

```protobuf
// ─── 요청 ──────────────────────────────────────────────────────────────────
message ContentAnalysisRequest {
  string request_token = 1;          // 요청 고유 ID
  AnalysisConnector analysis_connector = 2;
    // FILE_ATTACHED   = 1  → event_type: upload
    // FILE_DOWNLOADED = 2  → event_type: download
    // BULK_DATA_ENTRY = 3  → event_type: paste

  RequestData request_data = 3;

  oneof content_data {
    string text_content = 4;         // paste: 원문 텍스트 (로컬에서만 사용, 전송 금지)
    string file_path    = 5;         // 파일: 로컬 경로 (SDK가 직접 전달하는 경우 ※)
  }
}

message RequestData {
  string url       = 1;             // 목적지 URL (필수)
  string filename  = 2;             // 파일명 (paste면 빈 값)
  string digest    = 3;             // Chrome이 계산한 SHA256 (폴백용)
  string email     = 4;             // Chrome에 로그인된 이메일
  string tab_title = 5;             // 브라우저 탭 제목
}

// ─── 응답 ──────────────────────────────────────────────────────────────────
message ContentAnalysisResponse {
  message Result {
    message TriggeredRule {
      enum Action {
        ACTION_UNSPECIFIED = 0;
        REPORT_ONLY        = 1;   // ← 우리는 항상 이것 (ALLOW + 기록)
        WARN               = 2;
        BLOCK              = 3;
      }
      Action action = 5;
    }
    // ...
  }
}
```

> ※ `file_path`를 SDK가 직접 제공하는지, 아니면 URL/다른 방식인지는
>   SDK 버전에 따라 다를 수 있다. demo 코드에서 확인하라.
