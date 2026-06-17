"""들어온 지문을 supervise_file(baseline) 목록과 비교해 매칭을 만든다.

SHA 동일은 exact(100). 아니면 양쪽 fuzzy_hash가 모두 있을 때 ssdeep 유사도(0~100)를
계산해 임계치 이상만 fuzzy로 포함한다.
"""

from collections.abc import Sequence

from app.constants import FUZZY_MATCH_THRESHOLD, MATCH_TYPE_EXACT, MATCH_TYPE_FUZZY
from app.domain.fingerprint import fuzzy_similarity
from app.models import MatchResult, SuperviseFile


def find_matches(
    sha256: str,
    fuzzy_hash: str | None,
    supervise_files: Sequence[SuperviseFile],
    threshold: int = FUZZY_MATCH_THRESHOLD,
) -> list[MatchResult]:
    """지문에 대한 매칭 목록을 유사도 내림차순으로 반환한다.

    Args:
        sha256: 들어온 SHA-256.
        fuzzy_hash: 들어온 ssdeep 지문(없으면 None).
        supervise_files: 비교 대상 baseline 목록.
        threshold: 이 이상 유사도만 fuzzy로 포함.

    Returns:
        MatchResult 리스트(similarity 내림차순, 동률은 supervise_file_id 오름차순).
    """
    matches: list[MatchResult] = []
    for sf in supervise_files:
        if sf.sha256 == sha256:
            matches.append(MatchResult(supervise_file_id=sf.id, name=sf.name,
                                       match_type=MATCH_TYPE_EXACT, similarity=100))
            continue
        if fuzzy_hash is None or sf.fuzzy_hash is None:
            continue
        similarity = fuzzy_similarity(fuzzy_hash, sf.fuzzy_hash)
        if similarity >= threshold:
            matches.append(MatchResult(supervise_file_id=sf.id, name=sf.name,
                                       match_type=MATCH_TYPE_FUZZY, similarity=similarity))
    matches.sort(key=lambda m: (-m.similarity, m.supervise_file_id))
    return matches
