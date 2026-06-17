"""SHA-256·fuzzy(ssdeep) 계산과 유사도 비교 테스트."""

import hashlib

from app.fingerprint import compute_fuzzy, compute_sha256, fuzzy_similarity


def test_sha256_matches_hashlib() -> None:
    data = b"hello world"
    assert compute_sha256(data) == hashlib.sha256(data).hexdigest()


def test_fuzzy_none_for_empty_input() -> None:
    assert compute_fuzzy(b"") is None


def test_fuzzy_generated_for_normal_input() -> None:
    data = ("The quick brown fox jumps over the lazy dog. " * 20).encode()
    digest = compute_fuzzy(data)
    assert digest is not None
    assert len(digest) > 0


def test_fuzzy_similarity_identical_is_100() -> None:
    data = ("The quick brown fox jumps over the lazy dog. " * 20).encode()
    digest = compute_fuzzy(data)
    assert digest is not None
    assert fuzzy_similarity(digest, digest) == 100


def test_fuzzy_similarity_high_for_small_edit() -> None:
    # ssdeep(ppdeep)은 동일 문장을 단순 반복한 텍스트에서는 청크 경계가
    # 어긋나 유사도가 0이 나오므로(블록 크기 민감성, 설계 §10), 변화가 있는
    # 비반복 텍스트(같은 원본 + 소량 편집)로 검증한다.
    base_text = "".join(
        f"Confidential design note {i}: vendor {i * 7}, module {i % 13}, status open.\n"
        for i in range(300)
    )
    base = base_text.encode()
    edited = base + b"A few words changed for the edit test."
    sim = fuzzy_similarity(compute_fuzzy(base), compute_fuzzy(edited))
    assert sim >= 50  # 소량 편집은 높은 유사도

def test_fuzzy_similarity_range() -> None:
    a = compute_fuzzy(("alpha beta gamma. " * 40).encode())
    b = compute_fuzzy(("zulu yankee xray whiskey. " * 40).encode())
    sim = fuzzy_similarity(a, b)
    assert 0 <= sim <= 100
