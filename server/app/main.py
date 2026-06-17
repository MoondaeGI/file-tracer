"""uvicorn 진입점. SQLite 저장소로 앱을 구성한다.

실행(사용자 확인 후): python -m uvicorn app.main:app --reload --port 8000
"""

from pathlib import Path

from app.api import build_app
from app.repository import SqliteRepository

_DB_PATH = Path(__file__).parent.parent / "file_tracer.db"

app = build_app(SqliteRepository(_DB_PATH))
