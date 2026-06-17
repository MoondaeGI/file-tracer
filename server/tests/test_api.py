"""API 통합 테스트(TestClient + SqliteRepository(:memory:))."""

import io

import pytest
from fastapi.testclient import TestClient

from app.api import build_app
from app.repository import SqliteRepository

BIG = ("Confidential design dossier. " * 40).encode()


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(SqliteRepository(":memory:")))


def _upload(client, content: bytes, name: str):
    return client.post("/api/fingerprints",
                       files={"file": (name, io.BytesIO(content), "application/octet-stream")})


def test_mode_a_new_baseline(client) -> None:
    r = _upload(client, BIG, "secret.dwg")
    assert r.status_code == 200
    body = r.json()
    assert body["was_update"] is False
    assert body["supervise_file"]["name"] == "secret.dwg"
    # supervise-files 목록에 1건, history 0
    files = client.get("/api/supervise-files").json()["supervise_files"]
    assert len(files) == 1
    assert files[0]["update_history_count"] == 0


def test_mode_a_reupload_snapshots(client) -> None:
    _upload(client, BIG, "secret.dwg")
    r = _upload(client, BIG + b"changed", "secret.dwg")
    assert r.json()["was_update"] is True
    files = client.get("/api/supervise-files").json()["supervise_files"]
    assert len(files) == 1
    assert files[0]["update_history_count"] == 1


def test_mode_b_event_creates_trace_match(client) -> None:
    _upload(client, BIG, "secret.dwg")             # baseline 등록
    import hashlib
    import ppdeep
    payload = {"sha256": hashlib.sha256(BIG).hexdigest(), "fuzzy_hash": ppdeep.hash(BIG),
               "size": len(BIG), "name": "copy_on_pc.dwg", "event_type": "created",
               "host": "PC-9", "user": "lee"}
    r = client.post("/api/fingerprints", json=payload)
    assert r.status_code == 200
    matches = r.json()["matches"]
    assert any(m["match_type"] == "exact" for m in matches)
    # events 목록에 trace_match 요약
    events = client.get("/api/events").json()["events"]
    assert events[0]["name"] == "copy_on_pc.dwg"
    assert events[0]["best_match"]["similarity"] == 100


def test_mode_b_missing_sha_400(client) -> None:
    assert client.post("/api/fingerprints", json={"size": 1}).status_code == 400


def test_supervise_file_events_endpoint(client) -> None:
    import hashlib
    import ppdeep
    _upload(client, BIG, "secret.dwg")             # baseline 등록
    payload = {"sha256": hashlib.sha256(BIG).hexdigest(), "fuzzy_hash": ppdeep.hash(BIG),
               "size": len(BIG), "name": "copy_on_pc.dwg", "event_type": "created",
               "host": "PC-9", "user": "lee"}
    client.post("/api/fingerprints", json=payload)  # baseline과 exact 매칭되는 이벤트
    sf_id = client.get("/api/supervise-files").json()["supervise_files"][0]["id"]

    resp = client.get(f"/api/supervise-files/{sf_id}/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["supervise_file"]["id"] == sf_id
    assert body["supervise_file"]["name"] == "secret.dwg"
    assert len(body["events"]) == 1
    item = body["events"][0]
    assert item["name"] == "copy_on_pc.dwg"
    assert item["host"] == "PC-9"
    assert item["match"]["match_type"] == "exact"
    assert item["match"]["similarity"] == 100


def test_supervise_file_events_404_for_unknown(client) -> None:
    assert client.get("/api/supervise-files/999/events").status_code == 404
