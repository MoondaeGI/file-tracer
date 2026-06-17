"""서버 모드 b 전송 테스트(httpx MockTransport)."""

import httpx

from agent.sender import Sender

CAPTURED: list[dict] = []


def _ok_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        CAPTURED.append(json.loads(request.content))
        return httpx.Response(200, json={"matches": []})
    return httpx.MockTransport(handler)


def _fail_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)
    return httpx.MockTransport(handler)


def test_send_posts_mode_b_payload() -> None:
    CAPTURED.clear()
    client = httpx.Client(transport=_ok_transport())
    sender = Sender("http://srv", host="PC-1", user="kim", client=client)
    ok = sender.send(sha256="a" * 64, fuzzy_hash="3:x", size=12,
                     name="s.txt", event_type="created", source_hint="downloads")
    assert ok is True
    assert CAPTURED[-1] == {
        "sha256": "a" * 64, "fuzzy_hash": "3:x", "size": 12, "name": "s.txt",
        "event_type": "created", "host": "PC-1", "user": "kim",
        "source_hint": "downloads",
    }


def test_send_returns_false_on_server_error() -> None:
    client = httpx.Client(transport=_fail_transport())
    sender = Sender("http://srv", host="PC-1", user="kim", client=client, retries=1)
    ok = sender.send(sha256="a" * 64, fuzzy_hash=None, size=1,
                     name="x", event_type="deleted", source_hint=None)
    assert ok is False
