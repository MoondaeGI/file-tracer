"""config.toml 로드·검증. 시스템 경계 입력 검증(설계 §8)."""

import tomllib
from pathlib import Path

from agent.errors import ConfigError
from agent.models import Config

_DEFAULT_IGNORE = ("~$*", "*.tmp", "*.crdownload", "*.part")


def load_config(path: Path) -> Config:
    """config.toml을 읽어 검증된 Config를 반환한다.

    Args:
        path: config.toml 경로.

    Returns:
        검증된 Config.

    Raises:
        ConfigError: 파일 없음·파싱 실패·필수값 누락·경로 부재·잘못된 값.
    """
    if not path.is_file():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config.toml 파싱 실패: {exc}") from exc

    server_url = raw.get("server_url")
    if not server_url or not isinstance(server_url, str):
        raise ConfigError("server_url 이 필요합니다")

    debounce = raw.get("debounce_seconds", 1.5)
    if not isinstance(debounce, (int, float)) or debounce <= 0:
        raise ConfigError("debounce_seconds 는 양수여야 합니다")

    raw_paths = raw.get("watch_paths") or []
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ConfigError("watch_paths 가 비어 있습니다")
    watch_paths: list[Path] = []
    for entry in raw_paths:
        p = Path(entry)
        if not p.is_dir():
            raise ConfigError(f"watch_paths 의 경로가 존재하는 디렉터리가 아닙니다: {p}")
        watch_paths.append(p)

    ignore = raw.get("ignore_globs") or list(_DEFAULT_IGNORE)
    return Config(
        server_url=server_url,
        debounce_seconds=float(debounce),
        watch_paths=tuple(watch_paths),
        ignore_globs=tuple(ignore),
    )
