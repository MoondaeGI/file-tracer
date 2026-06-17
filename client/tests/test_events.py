"""임시파일 필터·source_hint 휴리스틱 테스트."""

from agent.events import should_ignore, source_hint_for

GLOBS = ["~$*", "*.tmp", "*.crdownload", "*.part"]


def test_ignores_temp_files() -> None:
    assert should_ignore("C:\\x\\~$report.docx", GLOBS)
    assert should_ignore("C:\\x\\data.tmp", GLOBS)
    assert should_ignore("C:\\x\\movie.crdownload", GLOBS)


def test_keeps_normal_files() -> None:
    assert not should_ignore("C:\\x\\secret.txt", GLOBS)
    assert not should_ignore("C:\\x\\design.dwg", GLOBS)


def test_source_hint_downloads() -> None:
    assert source_hint_for("C:\\Users\\me\\Downloads\\a.zip") == "downloads"


def test_source_hint_cloud() -> None:
    assert source_hint_for("C:\\Users\\me\\Google Drive\\a.txt") == "gdrive_sync"
    assert source_hint_for("C:\\Users\\me\\Dropbox\\a.txt") == "dropbox_sync"
    assert source_hint_for("C:\\Users\\me\\OneDrive\\a.txt") == "onedrive_sync"


def test_source_hint_none() -> None:
    assert source_hint_for("C:\\Secret\\a.txt") is None
