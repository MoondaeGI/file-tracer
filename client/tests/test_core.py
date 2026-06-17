"""CollectorCore — TraceEvent를 받아 Sender로 전송."""

from core.core import CollectorCore
from common.events import TraceEvent


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


def _ev() -> TraceEvent:
    return TraceEvent(sha256="a" * 64, fuzzy_hash="3:x", size=5, name="s.dwg",
                      event_type="upload", host="PC", user="kim@corp.com",
                      source_hint=None, metadata={"url": "https://drive.google.com"})


def test_process_forwards_to_sender_with_metadata() -> None:
    sender = FakeSender()
    core = CollectorCore(sender)
    assert core.process(_ev()) is True
    call = sender.calls[-1]
    assert call["event_type"] == "upload"
    assert call["user"] == "kim@corp.com"
    assert call["metadata"] == {"url": "https://drive.google.com"}
