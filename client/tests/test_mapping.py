"""커넥터 요청 → TraceEvent 매핑(순수)."""

import pytest

from common.fingerprint import CachedFingerprint
from connector.errors import MappingError
from connector.mapping import to_trace_event

FP = CachedFingerprint(sha256="a" * 64, fuzzy_hash="3:x", size=12)


def _req(**over) -> dict:
    base = {"connector": "FILE_ATTACHED", "filename": "s.dwg",
            "url": "https://drive.google.com/x", "email": "kim@corp.com",
            "tab_title": "Drive", "text_content": None}
    base.update(over)
    return base


def test_upload_mapping() -> None:
    ev = to_trace_event(_req(), FP, host="PC-1")
    assert ev.event_type == "upload"
    assert ev.name == "s.dwg"
    assert ev.user == "kim@corp.com"
    assert ev.host == "PC-1"
    assert ev.metadata["url"] == "https://drive.google.com/x"
    assert ev.metadata["dst_host"] == "drive.google.com"
    assert ev.source_hint is None


def test_download_and_paste_event_types() -> None:
    assert to_trace_event(_req(connector="FILE_DOWNLOADED"), FP, "PC").event_type == "download"
    p = to_trace_event(_req(connector="BULK_DATA_ENTRY", filename=""), FP, "PC")
    assert p.event_type == "paste"
    assert p.name == "(pasted text)"


def test_missing_url_raises() -> None:
    with pytest.raises(MappingError):
        to_trace_event(_req(url=None), FP, "PC")


def test_unknown_connector_raises() -> None:
    with pytest.raises(MappingError):
        to_trace_event(_req(connector="PRINT"), FP, "PC")
