"""파일 이벤트 보조 함수: 임시파일 필터, 경로 기반 source_hint 추정."""

from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import PurePath

# 경로 폴더명(소문자) → source_hint 값
_HINT_FOLDERS = (
    ("downloads", "downloads"),
    ("google drive", "gdrive_sync"),
    ("googledrive", "gdrive_sync"),
    ("dropbox", "dropbox_sync"),
    ("onedrive", "onedrive_sync"),
)


def should_ignore(path: str, ignore_globs: Sequence[str]) -> bool:
    """파일명이 임시파일 glob 중 하나에 맞으면 True.

    Args:
        path: 파일 경로.
        ignore_globs: 무시할 파일명 glob 목록.

    Returns:
        무시 대상이면 True.
    """
    name = PurePath(path).name
    return any(fnmatch(name, pattern) for pattern in ignore_globs)


def source_hint_for(path: str) -> str | None:
    """경로의 폴더명으로 출처 힌트를 추정한다(없으면 None)."""
    lowered = path.lower()
    for needle, hint in _HINT_FOLDERS:
        if needle in lowered:
            return hint
    return None
