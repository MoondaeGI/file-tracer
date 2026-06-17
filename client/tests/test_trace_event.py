"""TraceEvent·event_type 상수 테스트."""

import dataclasses

import pytest

from common import events
from common.events import TraceEvent


def test_event_type_constants() -> None:
    assert events.EVENT_UPLOAD == "upload"
    assert events.EVENT_DOWNLOAD == "download"
    assert events.EVENT_PASTE == "paste"
    assert events.EVENT_CREATED == "created"


def test_trace_event_frozen_and_fields() -> None:
    ev = TraceEvent(sha256="a" * 64, fuzzy_hash=None, size=1, name="f",
                    event_type="upload", host="PC", user="kim@corp.com",
                    source_hint=None, metadata={"url": "https://x"})
    assert ev.metadata["url"] == "https://x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.name = "y"  # type: ignore[misc]
