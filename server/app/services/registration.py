"""유스케이스: baseline 등록(mode a).

파일 바이트로부터 지문을 계산해 repository에 baseline을 등록/갱신한다.
요청 파싱·응답 직렬화는 컨트롤러(api) 책임이고, 여기선 도메인 입력만 다룬다.
"""

from app.domain.fingerprint import compute_fuzzy, compute_sha256
from app.models import Fingerprint, SuperviseFile
from app.repository import SqliteRepository


def register(
    repo: SqliteRepository, filename: str, data: bytes, now: str
) -> tuple[SuperviseFile, bool]:
    """파일 바이트 → 지문 계산 → baseline 등록/갱신.

    Args:
        repo: 저장소.
        filename: 업로드 파일명(없으면 호출부에서 기본값 지정).
        data: 파일 바이트.
        now: 서버 시각(ISO). 주입.

    Returns:
        (등록/갱신된 SuperviseFile, was_update). 신규면 was_update=False.
    """
    fp = Fingerprint(sha256=compute_sha256(data), fuzzy_hash=compute_fuzzy(data), size=len(data))
    return repo.register_supervise_file(filename, fp, now)
