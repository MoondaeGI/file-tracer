"""브리지 JSON → connector.handle_request → core → 서버(httpx)까지 한 흐름.

서버는 server 패키지를 import해 uvicorn 스레드로 임시 포트에 띄운다.
실 Chrome·실 브리지 없음. OS가 빈 포트를 자동 할당한다.
"""

import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.api import build_app  # noqa: E402
from app.repository import SqliteRepository  # noqa: E402

from core.core import CollectorCore  # noqa: E402
from core.sender import Sender  # noqa: E402
from connector.agent import handle_request  # noqa: E402


def _free_port() -> int:
    """OS가 사용 가능한 빈 포트를 하나 반환한다."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_upload_event_reaches_server_with_url(tmp_path: Path) -> None:
    port = _free_port()
    app = build_app(SqliteRepository(":memory:"))

    # uvicorn을 데몬 스레드에 띄운다
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    # 서버 기동 대기 (최대 5초)
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            httpx.get(f"{base_url}/api/events", timeout=1.0)
            break
        except httpx.ConnectError:
            time.sleep(0.05)

    try:
        client = httpx.Client(base_url=base_url, timeout=5.0)
        sender = Sender(base_url, host="PC-1", user="default", client=client)
        core = CollectorCore(sender)

        f = tmp_path / "secret.dwg"
        f.write_bytes(b"confidential bytes for e2e fingerprint test")
        req = {
            "connector": "FILE_ATTACHED",
            "filename": "secret.dwg",
            "file_path": str(f),
            "text_content": None,
            "url": "https://drive.google.com/x",
            "email": "kim@corp.com",
            "tab_title": "Drive",
        }

        core.start()
        try:
            assert handle_request(req, core, host="PC-1") is True

            # 폴링: 최대 5초 내에 서버에 이벤트 도달 대기
            deadline = time.time() + 5
            events = []
            while time.time() < deadline:
                events = client.get("/api/events").json()["events"]
                if events:
                    break
                time.sleep(0.05)

            assert events, "5초 내에 이벤트가 서버에 도달하지 않음"
            assert events[0]["event_type"] == "upload"
            assert events[0]["url"] == "https://drive.google.com/x"
            assert events[0]["user"] == "kim@corp.com"
        finally:
            core.stop()
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
