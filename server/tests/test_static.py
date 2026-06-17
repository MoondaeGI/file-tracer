"""정적 웹페이지 서빙·내용 테스트."""

from fastapi.testclient import TestClient

from app.api import build_app
from app.repository import SqliteRepository


def test_index_served_with_tables() -> None:
    client = TestClient(build_app(SqliteRepository(":memory:")))
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text.lower()
    assert "file-tracer" in text
    assert "supervise" in text          # baseline 표
    assert "event" in text              # 이벤트 표


def test_index_has_trace_detail_panel() -> None:
    client = TestClient(build_app(SqliteRepository(":memory:")))
    text = client.get("/").text
    assert 'id="detail"' in text                   # 클릭 시 보이는 상세 패널
    assert "/api/supervise-files/" in text          # baseline별 매칭 이벤트 호출(템플릿 URL)


def test_index_has_destination_column() -> None:
    client = TestClient(build_app(SqliteRepository(":memory:")))
    text = client.get("/").text.lower()
    assert "목적지" in text or "destination" in text or "url" in text
