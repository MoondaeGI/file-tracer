"""커넥터 에이전트 — 브리지 요청을 지문·매핑해 코어로 보냄."""

from pathlib import Path

from connector.agent import handle_request


class FakeCore:
    def __init__(self) -> None:
        self.events: list = []

    def submit(self, event) -> None:
        self.events.append(event)


def test_file_upload_fingerprints_and_submits(tmp_path: Path) -> None:
    f = tmp_path / "secret.dwg"
    f.write_bytes(b"confidential bytes here for fingerprint")
    req = {"connector": "FILE_ATTACHED", "filename": "secret.dwg",
           "file_path": str(f), "url": "https://drive.google.com/x",
           "email": "kim@corp.com", "tab_title": "Drive", "text_content": None}
    core = FakeCore()
    assert handle_request(req, core, host="PC-1") is True
    ev = core.events[-1]
    assert ev.event_type == "upload"
    assert ev.sha256  # 실제 파일에서 계산됨
    assert ev.metadata["url"] == "https://drive.google.com/x"


def test_paste_fingerprints_text(tmp_path: Path) -> None:
    req = {"connector": "BULK_DATA_ENTRY", "filename": "",
           "file_path": None, "text_content": "secret source code " * 30,
           "url": "https://chat.openai.com", "email": "kim@corp.com", "tab_title": "ChatGPT"}
    core = FakeCore()
    assert handle_request(req, core, host="PC-1") is True
    ev = core.events[-1]
    assert ev.event_type == "paste"
    assert ev.name == "(pasted text)"
    assert ev.sha256


def test_missing_url_drops_event() -> None:
    req = {"connector": "FILE_ATTACHED", "filename": "x", "file_path": None,
           "text_content": None, "url": None, "email": "u"}
    core = FakeCore()
    assert handle_request(req, core, host="PC") is False
    assert core.events == []


def test_fingerprinted_but_missing_url_drops_event(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_bytes(b"data for fingerprint but no destination url")
    req = {"connector": "FILE_ATTACHED", "filename": "x.txt",
           "file_path": str(f), "url": None, "email": "u", "text_content": None}
    core = FakeCore()
    assert handle_request(req, core, host="PC") is False
    assert core.events == []
