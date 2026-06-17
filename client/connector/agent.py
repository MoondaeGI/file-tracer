"""커넥터 에이전트: 브리지가 보낸 raw 요청을 지문·매핑해 코어로 보낸다.

본문(파일/텍스트)은 여기서 지문으로만 변환되고 폐기된다 — 서버로 본문이 가지 않는다.
파일 읽기 실패 시 Chrome digest로 폴백(fuzzy=null), 매핑 실패(url 없음 등)는 드롭+로그.
"""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

from common.events import TraceEvent
from common.fingerprint import (
    CachedFingerprint,
    compute_fuzzy,
    compute_sha256,
    fingerprint_file,
)
from connector.errors import MappingError
from connector.mapping import to_trace_event

logger = logging.getLogger("connector.agent")


def _fingerprint(req: dict) -> CachedFingerprint | None:
    """요청 본문(파일 또는 텍스트)에서 지문을 만든다. 실패 시 digest 폴백/None."""
    text = req.get("text_content")
    if text is not None:
        data = text.encode("utf-8")
        return CachedFingerprint(compute_sha256(data), compute_fuzzy(data), len(data))

    file_path = req.get("file_path")
    if file_path:
        from pathlib import Path
        try:
            return fingerprint_file(Path(file_path))
        except OSError as exc:
            logger.warning("파일 지문 실패 %s: %s — digest 폴백", file_path, exc)
            digest = req.get("digest")
            if digest:
                return CachedFingerprint(digest, None, 0)
    logger.info("지문 불가(본문 없음): %s", req.get("filename"))
    return None


def handle_request(req: dict, core, host: str) -> bool:
    """브리지 요청 1건을 처리한다. 코어로 submit하면 True, 드롭하면 False."""
    fp = _fingerprint(req)
    if fp is None:
        return False
    try:
        event: TraceEvent = to_trace_event(req, fp, host)
    except MappingError as exc:
        logger.warning("매핑 실패, 이벤트 드롭: %s", exc)
        return False
    core.submit(event)
    return True


def serve(core, host: str, port: int) -> HTTPServer:
    """브리지가 POST /event로 보내는 요청을 받는 로컬 HTTP 서버를 만든다(start는 호출자).

    반환된 HTTPServer를 `serve_forever()`로 실행하거나 `shutdown()`으로 종료한다.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body)
                handle_request(req, core, host)
                self.send_response(200)
            except Exception:  # 브리지는 응답만 받으면 됨 — 예외를 Chrome에 노출하지 않음
                logger.exception("intake 처리 실패")
                self.send_response(500)
            self.end_headers()

        def log_message(self, *args) -> None:  # 기본 stderr 로깅 끔
            pass

    return HTTPServer(("127.0.0.1", port), _Handler)
