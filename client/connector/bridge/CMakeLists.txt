cmake_minimum_required(VERSION 3.20)
project(file_tracer_bridge CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ─── SDK 경로 설정 ─────────────────────────────────────────────────────────────
# content_analysis_sdk를 clone한 경로를 아래 변수에 설정하라.
# 예: cmake -DCA_SDK_SRC_DIR="C:/dev/content_analysis_sdk" ..
#
# 권장 clone 위치: client/connector/bridge/content_analysis_sdk/
#   git clone https://github.com/chromium/content_analysis_sdk \
#       client/connector/bridge/content_analysis_sdk
#
# ※ SDK의 실제 CMakeLists.txt 이름/구조는 저장소 최신 버전을 확인하라.
set(CA_SDK_SRC_DIR
    "${CMAKE_CURRENT_SOURCE_DIR}/content_analysis_sdk"
    CACHE PATH "chromium/content_analysis_sdk 저장소 루트 경로")

if(NOT EXISTS "${CA_SDK_SRC_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "content_analysis_sdk를 찾을 수 없습니다.\n"
        "CA_SDK_SRC_DIR='${CA_SDK_SRC_DIR}'\n"
        "아래 명령으로 clone한 뒤 다시 cmake를 실행하세요:\n"
        "  git clone https://github.com/chromium/content_analysis_sdk ${CA_SDK_SRC_DIR}\n"
        "또는 cmake 옵션으로 경로를 지정하세요:\n"
        "  cmake -DCA_SDK_SRC_DIR=<경로> ..")
endif()

# SDK를 서브디렉터리로 포함
# ※ SDK의 CMakeLists.txt가 노출하는 타겟 이름을 확인하라 (예: content_analysis_sdk).
add_subdirectory("${CA_SDK_SRC_DIR}" "${CMAKE_BINARY_DIR}/sdk_build")

# ─── 브리지 실행 파일 ──────────────────────────────────────────────────────────
add_executable(file_tracer_bridge
    bridge_handler.cpp
)

# SDK include 경로
# ※ SDK 저장소의 실제 include 디렉터리 이름을 확인하라.
target_include_directories(file_tracer_bridge PRIVATE
    "${CA_SDK_SRC_DIR}"
    "${CA_SDK_SRC_DIR}/proto"           # proto 생성 헤더가 여기 있을 경우
    "${CMAKE_BINARY_DIR}/sdk_build"     # proto 빌드 산출물 위치 (빌드 시스템마다 다름 ※)
)

# SDK 라이브러리 링크
# ※ SDK CMakeLists.txt가 노출하는 타겟 이름을 확인하라.
# 일반적으로 content_analysis_sdk, content_analysis_sdk_agent 등이 쓰인다.
target_link_libraries(file_tracer_bridge PRIVATE
    content_analysis_sdk   # ※ SDK 타겟명 확인
    winhttp                # WinHTTP (비동기 POST 용)
)

# Windows 전용
if(NOT WIN32)
    message(FATAL_ERROR "이 브리지는 Windows 전용입니다 (WinHTTP, named pipe).")
endif()

# ─── 빌드 후 실행 파일 위치 안내 ───────────────────────────────────────────────
# 빌드 완료 후:
#   Debug 빌드:   build/Debug/file_tracer_bridge.exe
#   Release 빌드: build/Release/file_tracer_bridge.exe
#
# 실행 전 README.md의 "실행 순서"를 따라 서버/호스트를 먼저 기동하라.
message(STATUS "브리지 빌드 설정 완료: CA_SDK_SRC_DIR=${CA_SDK_SRC_DIR}")
