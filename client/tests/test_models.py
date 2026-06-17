"""커스텀 예외와 도메인 모델 테스트."""

import dataclasses
from pathlib import Path

import pytest

from agent import models
from agent.errors import ConfigError
from agent.models import CachedFingerprint, Config, Pending, Task


def test_config_error_is_exception() -> None:
    with pytest.raises(ConfigError):
        raise ConfigError("bad")


def test_event_constants() -> None:
    assert models.EVENT_CREATED == "created"
    assert models.EVENT_MODIFIED == "modified"
    assert models.EVENT_MOVED == "moved"
    assert models.EVENT_DELETED == "deleted"


def test_config_is_frozen() -> None:
    cfg = Config(server_url="http://x", debounce_seconds=1.5,
                 watch_paths=(Path("C:/a"),), ignore_globs=("*.tmp",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.server_url = "y"  # type: ignore[misc]


def test_cached_fingerprint_and_pending_and_task() -> None:
    fp = CachedFingerprint(sha256="a" * 64, fuzzy_hash=None, size=10)
    assert fp.fuzzy_hash is None
    assert Pending(event_type="created").moved_from is None
    assert Task(path="p", event_type="moved", moved_from="q").moved_from == "q"
