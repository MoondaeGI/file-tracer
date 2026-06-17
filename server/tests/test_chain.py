"""event 대상 해시체인 테스트."""

import dataclasses

from app.chain import compute_record_hash, event_payload, verify_chain
from app.models import Event


def _event(idx: int, prev_hash: str | None) -> Event:
    base = Event(id=idx, sha256=f"{idx:064x}", fuzzy_hash=None, size=1, name=f"f{idx}",
                 host="PC", user="u", event_type="created", detected_at="t",
                 source_hint=None, prev_hash=prev_hash, record_hash="")
    digest = compute_record_hash(event_payload(base), prev_hash)
    return dataclasses.replace(base, record_hash=digest)


def test_payload_excludes_id_and_hashes() -> None:
    payload = event_payload(_event(1, None))
    assert "id" not in payload
    assert "record_hash" not in payload
    assert "prev_hash" not in payload
    assert payload["sha256"] == f"{1:064x}"


def test_clean_chain_verifies() -> None:
    e1 = _event(1, None)
    e2 = _event(2, e1.record_hash)
    e3 = _event(3, e2.record_hash)
    assert verify_chain([e1, e2, e3]) is None


def test_tamper_detected() -> None:
    e1 = _event(1, None)
    e2 = _event(2, e1.record_hash)
    tampered = dataclasses.replace(e2, name="HACKED")
    assert verify_chain([e1, tampered]) == 2


def test_broken_prev_link_detected() -> None:
    e1 = _event(1, None)
    e2 = _event(2, "wrong")
    assert verify_chain([e1, e2]) == 2


def test_metadata_tamper_detected() -> None:
    """metadata 변조가 해시체인에서 탐지되는지 확인."""
    def _ev(idx, prev, meta):
        base = Event(id=idx, sha256=f"{idx:064x}", fuzzy_hash=None, size=1, name="f",
                     host="PC", user="u", event_type="upload", detected_at="t",
                     source_hint=None, metadata=meta, prev_hash=prev, record_hash="")
        return dataclasses.replace(base, record_hash=compute_record_hash(event_payload(base), prev))

    e1 = _ev(1, None, {"url": "https://good"})
    tampered = dataclasses.replace(e1, metadata={"url": "https://evil"})
    assert verify_chain([tampered]) == 1
