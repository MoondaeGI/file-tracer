"""새 스키마 도메인 모델·상수 테스트."""

import dataclasses

import pytest

from app import constants
from app.models import (
    Event,
    EventInput,
    Fingerprint,
    MatchResult,
    SuperviseFile,
    TraceMatch,
    UpdateHistory,
)


def test_constants() -> None:
    assert constants.MATCH_TYPE_EXACT == "exact"
    assert constants.MATCH_TYPE_FUZZY == "fuzzy"
    assert constants.FUZZY_MATCH_THRESHOLD == 50
    assert constants.EVENT_TYPES == ("created", "modified", "moved", "deleted")
    assert constants.RESERVED_EVENT_TYPES == ("copy", "upload", "download")


def test_fingerprint() -> None:
    fp = Fingerprint(sha256="a" * 64, fuzzy_hash=None, size=0)
    assert fp.fuzzy_hash is None


def test_supervise_file_frozen() -> None:
    sf = SuperviseFile(id=1, name="s.txt", sha256="a" * 64, fuzzy_hash="3:x",
                       size=10, created_at="t", updated_at="t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        sf.name = "y"  # type: ignore[misc]


def test_other_models_construct() -> None:
    assert UpdateHistory(id=1, supervise_file_id=2, sha256="a" * 64,
                         fuzzy_hash=None, size=1, replaced_at="t").supervise_file_id == 2
    assert EventInput(sha256="a" * 64, fuzzy_hash=None, size=1, name="n",
                      event_type="created", host=None, user=None, source_hint=None).name == "n"
    assert Event(id=1, sha256="a" * 64, fuzzy_hash=None, size=1, name="n", host=None,
                 user=None, event_type="created", detected_at="t", source_hint=None,
                 prev_hash=None, record_hash="h").record_hash == "h"
    assert TraceMatch(id=1, event_id=2, supervise_file_id=3, match_type="exact",
                      similarity=100, matched_at="t").similarity == 100
    assert MatchResult(supervise_file_id=3, name="n", match_type="fuzzy",
                       similarity=87).similarity == 87
