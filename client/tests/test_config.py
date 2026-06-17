"""config.toml 로드·검증 테스트."""

from pathlib import Path

import pytest

from agent.config import load_config
from agent.errors import ConfigError


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_valid_config(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cfg_path = _write(tmp_path, f'''
server_url = "http://127.0.0.1:8000"
debounce_seconds = 1.5
watch_paths = ["{watch.as_posix()}"]
ignore_globs = ["*.tmp"]
''')
    cfg = load_config(cfg_path)
    assert cfg.server_url == "http://127.0.0.1:8000"
    assert cfg.debounce_seconds == 1.5
    assert cfg.watch_paths == (watch,)
    assert cfg.ignore_globs == ("*.tmp",)


def test_missing_server_url_raises(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cfg_path = _write(tmp_path, f'''
debounce_seconds = 1.0
watch_paths = ["{watch.as_posix()}"]
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_nonexistent_watch_path_raises(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, '''
server_url = "http://x"
debounce_seconds = 1.0
watch_paths = ["C:\\\\does\\\\not\\\\exist_xyz"]
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_empty_watch_paths_raises(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, '''
server_url = "http://x"
debounce_seconds = 1.0
watch_paths = []
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)


def test_nonpositive_debounce_raises(tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    cfg_path = _write(tmp_path, f'''
server_url = "http://x"
debounce_seconds = 0
watch_paths = ["{watch.as_posix()}"]
''')
    with pytest.raises(ConfigError):
        load_config(cfg_path)
