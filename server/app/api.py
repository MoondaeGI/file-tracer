"""FastAPI 라우트. 모드 a=baseline 등록, 모드 b=이벤트+자동 매칭, GET 2개."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.errors import HttpError, InvalidFingerprintRequestError
from app.fingerprint import compute_fuzzy, compute_sha256
from app.matching import find_matches
from app.models import EventInput, Fingerprint
from app.repository import SqliteRepository

_STATIC_DIR = Path(__file__).parent / "static"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_app(repository: SqliteRepository) -> FastAPI:
    """저장소를 주입받아 FastAPI 앱을 구성한다."""
    app = FastAPI(title="file-tracer")

    @app.exception_handler(HttpError)
    async def _http_error_handler(_: Request, exc: HttpError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    @app.post("/api/fingerprints")
    async def post_fingerprints(request: Request) -> dict:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            return await _handle_mode_a(request, repository)
        if content_type.startswith("application/json"):
            return await _handle_mode_b(request, repository)
        raise InvalidFingerprintRequestError("multipart 또는 JSON 요청이어야 합니다")

    @app.get("/api/supervise-files")
    async def get_supervise_files() -> dict:
        items = []
        for sf in repository.list_supervise_files():
            items.append({
                "id": sf.id, "name": sf.name, "sha256": sf.sha256,
                "fuzzy_hash": sf.fuzzy_hash, "size": sf.size,
                "created_at": sf.created_at, "updated_at": sf.updated_at,
                "update_history_count": repository.count_update_history(sf.id),
            })
        return {"supervise_files": items}

    @app.get("/api/events")
    async def get_events() -> dict:
        items = []
        for ev in repository.list_events(limit=100):
            best = repository.best_trace_match(ev.id)
            best_dict = None
            if best is not None:
                sf = repository.get_supervise_file(best.supervise_file_id)
                best_dict = {"supervise_file_id": best.supervise_file_id,
                             "name": sf.name if sf else None,
                             "match_type": best.match_type, "similarity": best.similarity}
            items.append({
                "id": ev.id, "sha256": ev.sha256, "name": ev.name,
                "event_type": ev.event_type, "host": ev.host, "user": ev.user,
                "detected_at": ev.detected_at, "best_match": best_dict,
            })
        return {"events": items}

    @app.get("/api/supervise-files/{supervise_file_id}/events")
    async def get_supervise_file_events(supervise_file_id: int) -> dict:
        sf = repository.get_supervise_file(supervise_file_id)
        if sf is None:
            raise HttpError(404, f"supervise_file {supervise_file_id} 를 찾을 수 없습니다")
        events = []
        for ev, match in repository.events_matching_supervise_file(supervise_file_id):
            events.append({
                "id": ev.id, "sha256": ev.sha256, "name": ev.name,
                "event_type": ev.event_type, "host": ev.host, "user": ev.user,
                "detected_at": ev.detected_at,
                "match": {"match_type": match.match_type, "similarity": match.similarity},
            })
        return {"supervise_file": {"id": sf.id, "name": sf.name}, "events": events}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app


async def _handle_mode_a(request: Request, repository: SqliteRepository) -> dict:
    """모드 a: 파일 업로드 → baseline 등록/갱신."""
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        raise InvalidFingerprintRequestError("file 필드가 필요합니다")
    data = await upload.read()
    fp = Fingerprint(sha256=compute_sha256(data), fuzzy_hash=compute_fuzzy(data), size=len(data))
    sf, was_update = repository.register_supervise_file(upload.filename or "unknown", fp, _now_iso())
    return {
        "was_update": was_update,
        "supervise_file": {"id": sf.id, "name": sf.name, "sha256": sf.sha256,
                           "fuzzy_hash": sf.fuzzy_hash, "size": sf.size,
                           "created_at": sf.created_at, "updated_at": sf.updated_at},
    }


async def _handle_mode_b(request: Request, repository: SqliteRepository) -> dict:
    """모드 b: 클라 지문 JSON → 이벤트 기록 + 자동 매칭."""
    payload = await request.json()
    sha256 = payload.get("sha256")
    if not sha256:
        raise InvalidFingerprintRequestError("sha256 필드가 필요합니다")
    ev_input = EventInput(
        sha256=sha256, fuzzy_hash=payload.get("fuzzy_hash"),
        size=int(payload.get("size", 0)), name=payload.get("name", "unknown"),
        event_type=payload.get("event_type", "created"),
        host=payload.get("host"), user=payload.get("user"),
        source_hint=payload.get("source_hint"),
    )
    now = _now_iso()
    event = repository.add_event(ev_input, now)
    matches = find_matches(event.sha256, event.fuzzy_hash, repository.list_supervise_files())
    repository.add_trace_matches(event.id, matches, now)
    return {
        "event_id": event.id,
        "matches": [{"supervise_file_id": m.supervise_file_id, "name": m.name,
                     "match_type": m.match_type, "similarity": m.similarity} for m in matches],
    }
