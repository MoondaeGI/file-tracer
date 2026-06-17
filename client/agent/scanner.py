"""초기 스캔(콜드스타트 대응, 설계 §7): 감시 폴더를 1회 워크해 캐시만 채운다.

전송하지 않는다 — 시작마다 수천 건 POST하는 폭주를 피한다. observer 시작 전에
동기로 1회 호출한다.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from agent.cache import FingerprintCache
from agent.events import should_ignore
from agent.fingerprint import fingerprint_file as _default_fingerprint_file
from agent.models import CachedFingerprint

logger = logging.getLogger("agent.scanner")


def initial_scan(
    watch_paths: Sequence[Path],
    ignore_globs: Sequence[str],
    cache: FingerprintCache,
    fingerprint_file=_default_fingerprint_file,
) -> int:
    """감시 폴더를 워크해 각 파일 지문을 캐시에 채운다(전송 없음).

    Args:
        watch_paths: 감시 폴더 목록.
        ignore_globs: 무시할 임시파일 glob.
        cache: 채울 지문 캐시.
        fingerprint_file: 파일 지문 함수(테스트 주입용).

    Returns:
        캐시에 넣은 파일 수.
    """
    count = 0
    for root in watch_paths:
        for path in Path(root).rglob("*"):
            if not path.is_file():
                continue
            if should_ignore(str(path), ignore_globs):
                continue
            try:
                fp: CachedFingerprint = fingerprint_file(path)
            except OSError as exc:
                logger.warning("초기 스캔 해싱 실패 %s: %s", path, exc)
                continue
            cache.put(str(path), fp)
            count += 1
    logger.info("초기 스캔 완료: %s개 파일 캐시", count)
    return count
