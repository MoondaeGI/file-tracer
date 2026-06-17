"""파일 바이트로부터 지문(SHA-256·ssdeep fuzzy)을 계산하고 유사도를 비교한다.

fuzzy는 순수 파이썬 ppdeep(ssdeep 계열)을 쓴다. ssdeep은 compare()가 0~100
유사도를 직접 주므로 별도 환산식이 없다.
"""

import hashlib

import ppdeep


def compute_sha256(data: bytes) -> str:
    """바이트의 SHA-256 16진 해시를 반환한다.

    Args:
        data: 해시 대상 바이트.

    Returns:
        64자리 16진 문자열.
    """
    return hashlib.sha256(data).hexdigest()


def compute_fuzzy(data: bytes) -> str | None:
    """바이트의 ssdeep fuzzy 지문을 반환한다.

    입력이 비어 있으면(0바이트) 의미 있는 지문을 만들 수 없으므로 None을
    반환한다(이 레코드는 fuzzy 매칭에서 제외된다).

    Args:
        data: 지문 대상 바이트.

    Returns:
        ssdeep 지문 문자열 또는 None.
    """
    if not data:
        return None
    return ppdeep.hash(data)


def fuzzy_similarity(a: str, b: str) -> int:
    """두 ssdeep 지문의 유사도(0~100)를 반환한다. 100이 동일."""
    return ppdeep.compare(a, b)
