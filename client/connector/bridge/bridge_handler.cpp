/**
 * bridge_handler.cpp
 *
 * Chrome Content Analysis SDK 데모 에이전트를 최소 개조한 C++ 브리지.
 *
 * 역할:
 *   1. Chrome이 named pipe로 보내는 ContentAnalysisRequest를 SDK Agent/handler API로 수신.
 *   2. 수신 즉시 ALLOW 응답을 Chrome에 반환(REPORT_ONLY — 사용자 작업을 막지 않음, fail-open).
 *   3. 별도 스레드에서 §5.1 JSON을 구성해 WinHTTP로 http://127.0.0.1:8765/event 에 POST.
 *      전달 실패는 로그만 남기고 Chrome 응답을 막지 않는다.
 *
 * SDK 의존 (추측 표시 ※ — 공식 저장소에서 최종 확인 권고):
 *   chromium/content_analysis_sdk (https://github.com/chromium/content_analysis_sdk)
 *   headers: content_analysis/sdk/analysis_client.h
 *             content_analysis/sdk/analysis.pb.h  (proto 빌드 산출물)
 *   link:    content_analysis_sdk (CMakeLists.txt 참고)
 *
 * 빌드:
 *   이 파일만으로는 빌드되지 않는다. 반드시 SDK를 먼저 clone하고(README.md 참고)
 *   CMakeLists.txt에서 SDK 경로를 설정한 뒤 빌드하라.
 *
 * 사용자가 채워야 할 부분:
 *   - PIPE_NAME: Chrome 정책의 service_provider 에이전트 이름과 일치해야 한다.
 *   - SDK include 경로: CMakeLists.txt의 CA_SDK_SRC_DIR 변수.
 *   - SDK API 시그니처: 아래 코드는 SDK demo/agent 기준이므로 실제 헤더와 대조하라.
 */

// ─── SDK 헤더 (※ SDK clone 후 include 경로가 맞아야 함) ──────────────────────
#include "content_analysis/sdk/analysis_client.h"  // ※ Agent, ContentAnalysisRequest/Response
// analysis.pb.h 는 SDK가 proto를 빌드하면 자동 생성됨
// #include "content_analysis/sdk/analysis.pb.h"  // proto 메시지 직접 사용 시

// ─── 표준 라이브러리 ────────────────────────────────────────────────────────
#include <windows.h>
#include <winhttp.h>
#include <string>
#include <thread>
#include <iostream>
#include <sstream>
#include <stdexcept>

#pragma comment(lib, "winhttp.lib")

// ─── 설정 상수 ───────────────────────────────────────────────────────────────
// Chrome 정책의 service_provider 에이전트 이름 (정책 JSON의 파이프명과 반드시 일치)
// ※ 사용자가 Chrome 정책 적용 시 사용한 에이전트 이름으로 바꿀 것.
static const char* PIPE_NAME = "file_tracer_agent";

// Python 호스트의 connector intake 엔드포인트
static const wchar_t* INTAKE_HOST    = L"127.0.0.1";
static const INTERNET_PORT INTAKE_PORT = 8765;
static const wchar_t* INTAKE_PATH    = L"/event";

// ─── JSON 직렬화 (헤더-온리, 수동 문자열 조립) ──────────────────────────────
// 외부 JSON 라이브러리 없이 단순 수동 조립. 파일명/url에 큰따옴표·백슬래시가 있으면
// 이스케이프하지 않아 깨질 수 있다 — 프로토타입 수준. 실제 배포 시 nlohmann/json 등 사용 권고.
static std::string escape_json_string(const std::string& s) {
    std::ostringstream out;
    for (unsigned char c : s) {
        switch (c) {
            case '"':  out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n";  break;
            case '\r': out << "\\r";  break;
            case '\t': out << "\\t";  break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out << buf;
                } else {
                    out << c;
                }
        }
    }
    return out.str();
}

static std::string json_str(const std::string& val) {
    if (val.empty()) return "null";
    return "\"" + escape_json_string(val) + "\"";
}

// ─── WinHTTP 비동기 POST ─────────────────────────────────────────────────────
// Chrome 응답 임계경로 밖에서 별도 스레드로 실행된다. 실패해도 예외를 삼키고 로그만.
static void post_to_intake(const std::string& json_body) {
    HINTERNET hSession = WinHttpOpen(
        L"file-tracer-bridge/1.0",
        WINHTTP_ACCESS_TYPE_NO_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) {
        std::cerr << "[bridge] WinHttpOpen 실패: " << GetLastError() << "\n";
        return;
    }

    HINTERNET hConnect = WinHttpConnect(hSession, INTAKE_HOST, INTAKE_PORT, 0);
    if (!hConnect) {
        std::cerr << "[bridge] WinHttpConnect 실패: " << GetLastError() << "\n";
        WinHttpCloseHandle(hSession);
        return;
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect, L"POST", INTAKE_PATH, nullptr,
        WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!hRequest) {
        std::cerr << "[bridge] WinHttpOpenRequest 실패: " << GetLastError() << "\n";
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return;
    }

    const wchar_t* headers = L"Content-Type: application/json\r\n";
    BOOL ok = WinHttpSendRequest(
        hRequest, headers, (DWORD)-1L,
        (LPVOID)json_body.data(), (DWORD)json_body.size(),
        (DWORD)json_body.size(), 0);
    if (!ok) {
        std::cerr << "[bridge] WinHttpSendRequest 실패: " << GetLastError() << "\n";
    } else {
        if (!WinHttpReceiveResponse(hRequest, nullptr)) {
            std::cerr << "[bridge] WinHttpReceiveResponse 실패: " << GetLastError() << "\n";
        } else {
            DWORD status = 0;
            DWORD statusSize = sizeof(status);
            WinHttpQueryHeaders(hRequest,
                WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                WINHTTP_HEADER_NAME_BY_INDEX, &status, &statusSize, WINHTTP_NO_HEADER_INDEX);
            if (status != 200) {
                std::cerr << "[bridge] intake HTTP " << status << "\n";
            }
        }
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
}

// ─── ContentAnalysisRequest에서 §5.1 JSON 조립 ───────────────────────────────
// ※ 아래 필드 접근(request_token, analysis_connector, request_data, text_content 등)은
//   SDK의 content_analysis/sdk/analysis.proto 기준으로 작성했다. 실제 C++ API는
//   proto-generated getter(snake_case 메서드)를 따르므로 헤더와 대조 후 조정하라.
//
// proto 참고 (추측 ※):
//   message ContentAnalysisRequest {
//     string request_token = 1;
//     AnalysisConnector analysis_connector = 2;  // FILE_ATTACHED=1, FILE_DOWNLOADED=2, BULK_DATA_ENTRY=3
//     RequestData request_data = 3;
//     oneof content_data {
//       string text_content = 4;
//       string file_path    = 5;   // SDK가 파일 경로를 직접 제공하는 경우
//     }
//   }
//   message RequestData {
//     string url        = 1;
//     string filename   = 2;
//     string digest     = 3;
//     string email      = 4;
//     string tab_title  = 5;
//   }
static std::string build_json(
    const content_analysis::sdk::ContentAnalysisRequest& req)  // ※ SDK 네임스페이스 확인
{
    // analysis_connector enum → 문자열
    // ※ enum 값은 proto 정의 기준(FILE_ATTACHED=1, FILE_DOWNLOADED=2, BULK_DATA_ENTRY=3)
    std::string connector_str;
    switch (req.analysis_connector()) {  // ※ getter 이름 확인
        case 1: connector_str = "FILE_ATTACHED";  break;
        case 2: connector_str = "FILE_DOWNLOADED"; break;
        case 3: connector_str = "BULK_DATA_ENTRY"; break;
        default: connector_str = "UNKNOWN";        break;
    }

    const auto& rd = req.request_data();  // ※ getter 이름 확인

    // text_content / file_path: proto oneof — 존재 여부 확인 후 사용
    // ※ SDK가 file_path를 직접 주는지, URL로 주는지 확인 필요
    std::string text_content_val;
    std::string file_path_val;
    if (req.has_text_content()) {         // ※ has_ 메서드 존재 여부 확인
        text_content_val = req.text_content();
    } else if (req.has_file_path()) {     // ※ has_ 메서드 존재 여부 확인
        file_path_val = req.file_path();
    }

    // §5.1 JSON 조립
    std::ostringstream json;
    json << "{"
         << "\"request_token\":"  << json_str(req.request_token())    // ※
         << ",\"connector\":"     << json_str(connector_str)
         << ",\"filename\":"      << json_str(rd.filename())           // ※
         << ",\"digest\":"        << json_str(rd.digest())             // ※
         << ",\"url\":"           << json_str(rd.url())                // ※
         << ",\"email\":"         << json_str(rd.email())              // ※
         << ",\"tab_title\":"     << json_str(rd.tab_title())          // ※
         << ",\"file_path\":"     << json_str(file_path_val)
         << ",\"text_content\":"  << json_str(text_content_val)
         << "}";
    return json.str();
}

// ─── 요청 핸들러 ─────────────────────────────────────────────────────────────
// ※ SDK 핸들러 인터페이스는 demo/agent 기준이다. 실제 Agent 클래스/Handler 기반 API는
//   content_analysis_sdk의 agent/ 디렉터리 헤더를 확인하라.
//
// SDK 데모 에이전트는 대개 아래 패턴을 사용한다:
//   class MyHandler : public content_analysis::sdk::AgentEventHandler { ... };
//   또는 함수 포인터/람다 방식.
// 아래는 람다/함수 방식으로 작성했다 — SDK 패턴에 맞게 조정하라.

// ※ SDK가 제공하는 ALLOW verdict 상수/헬퍼 이름 확인 필요 (예: ContentAnalysisResponse::ALLOW)
static content_analysis::sdk::ContentAnalysisResponse  // ※ 반환 타입 확인
make_allow_response(const content_analysis::sdk::ContentAnalysisRequest& req) {
    content_analysis::sdk::ContentAnalysisResponse response;  // ※

    // ※ SDK 응답 구성 방식: demo 코드 참고.
    // 일반적 패턴 (proto 기반 추측):
    //   auto* result = response.add_results();
    //   result->set_tag("dlp");
    //   result->set_status(ContentAnalysisResponse::Result::SUCCESS);
    //   auto* rule = result->add_triggered_rules();
    //   rule->set_action(ContentAnalysisResponse::Result::TriggeredRule::REPORT_ONLY);
    // 또는 SDK 헬퍼:
    //   content_analysis::sdk::SetEventVerdictToAllow(&response);  // ※ 헬퍼 이름 확인

    // TODO: SDK demo/agent 코드의 "ALLOW" 응답 구성 부분을 그대로 복사하라.
    // 중요: 이 응답이 Chrome에 즉시 반환되어야 사용자 작업이 차단되지 않는다.
    (void)req;  // 현재 req는 응답 구성에 미사용 (request_token은 SDK가 자동 연결)
    return response;
}

// ─── main: Agent 초기화 + 이벤트 루프 ───────────────────────────────────────
int main() {
    std::cout << "[bridge] file-tracer C++ 브리지 시작 (pipe: " << PIPE_NAME << ")\n";

    // ※ SDK Agent 생성 방식: demo/agent/main.cc 참고.
    // 일반적 패턴 (추측):
    //   auto config = content_analysis::sdk::Agent::Config();
    //   config.name = PIPE_NAME;
    //   auto agent = content_analysis::sdk::Agent::Create(config, handler);
    //   agent->HandleEvents();

    // ※ 아래는 SDK API를 추측한 골격이다. 실제 Agent 클래스 생성자/메서드명 확인 필요.
    try {
        // ※ SDK Agent::Config 또는 동등 구조체로 파이프명 설정
        content_analysis::sdk::Agent::Config config;  // ※ Config 구조체 이름 확인
        config.name = PIPE_NAME;                       // ※ 필드명 확인

        // ※ 핸들러: SDK가 함수 포인터, 람다, 또는 Handler 서브클래스를 요구하는지 확인.
        // 아래는 람다 방식 가정:
        auto handler = [](content_analysis::sdk::ContentAnalysisRequest req)  // ※
            -> content_analysis::sdk::ContentAnalysisResponse  // ※
        {
            // ① 즉시 ALLOW 응답 구성 (Chrome에 반환)
            auto response = make_allow_response(req);

            // ② 별도 스레드에서 비동기 loopback POST (Chrome 응답 임계경로 밖)
            std::string json_body = build_json(req);
            std::thread([json_body]() {
                try {
                    post_to_intake(json_body);
                } catch (const std::exception& e) {
                    std::cerr << "[bridge] loopback POST 예외: " << e.what() << "\n";
                } catch (...) {
                    std::cerr << "[bridge] loopback POST 알 수 없는 예외\n";
                }
            }).detach();

            return response;
        };

        // ※ Agent::Create / new Agent 방식 확인
        auto agent = content_analysis::sdk::Agent::Create(config, handler);  // ※
        if (!agent) {
            std::cerr << "[bridge] Agent 생성 실패 (파이프명 충돌 또는 SDK 오류)\n";
            return 1;
        }

        std::cout << "[bridge] Chrome 이벤트 대기 중...\n";
        // ※ 이벤트 루프 메서드 이름 확인 (HandleEvents / Run / Serve 등)
        agent->HandleEvents();  // ※ 블로킹 루프

    } catch (const std::exception& e) {
        std::cerr << "[bridge] 치명적 오류: " << e.what() << "\n";
        return 1;
    }

    std::cout << "[bridge] 종료\n";
    return 0;
}
