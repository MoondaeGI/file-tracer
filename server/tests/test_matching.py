"""supervise_file 대상 매칭 테스트."""

from app.fingerprint import compute_fuzzy
from app.matching import find_matches
from app.models import SuperviseFile


def _sf(idx: int, sha: str, fuzzy: str | None) -> SuperviseFile:
    return SuperviseFile(id=idx, name=f"b{idx}.txt", sha256=sha, fuzzy_hash=fuzzy,
                         size=10, created_at="t", updated_at="t")


# ssdeep(ppdeep)은 단순 반복 텍스트에서 청크 경계가 어긋나 유사도가 0이 되므로
# (설계 §10), 변화가 있는 비반복 텍스트로 fuzzy 매칭을 검증한다.
VARIED_TEXT = "".join(
    f"Confidential design note {i}: vendor {i * 7}, module {i % 13}, status open.\n"
    for i in range(300)
)


def test_exact_match() -> None:
    sha = "a" * 64
    matches = find_matches(sha, None, [_sf(1, sha, None)])
    assert len(matches) == 1
    assert matches[0].supervise_file_id == 1
    assert matches[0].match_type == "exact"
    assert matches[0].similarity == 100


def test_fuzzy_match_within_threshold() -> None:
    text = VARIED_TEXT
    fa = compute_fuzzy(text.encode())
    fb = compute_fuzzy((text + "a small edit here.").encode())
    matches = find_matches("e" * 64, fb, [_sf(1, "f" * 64, fa)], threshold=50)
    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].similarity >= 50


def test_no_match_when_below_threshold() -> None:
    fa = compute_fuzzy(("alpha beta gamma. " * 40).encode())
    fb = compute_fuzzy(("zulu yankee xray. " * 40).encode())
    matches = find_matches("e" * 64, fb, [_sf(1, "f" * 64, fa)], threshold=101)
    assert matches == []


def test_null_fuzzy_skips() -> None:
    matches = find_matches("e" * 64, None, [_sf(1, "f" * 64, "3:x")])
    assert matches == []


def test_sorted_desc() -> None:
    sha = "a" * 64
    matches = find_matches(sha, None, [_sf(1, "z" * 64, None), _sf(2, sha, None)])
    assert [m.supervise_file_id for m in matches] == [2]
