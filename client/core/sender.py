"""서버 POST /api/fingerprints 모드 b 전송. 재시도 후 실패 시 로그."""

import logging

import httpx

logger = logging.getLogger("core.sender")


class Sender:
    """지문 이벤트를 서버 모드 b(JSON)로 전송한다."""

    def __init__(self, server_url: str, host: str, user: str,
                 client: httpx.Client | None = None, retries: int = 2) -> None:
        self._url = server_url.rstrip("/") + "/api/fingerprints"
        self._host = host
        self._user = user
        self._client = client or httpx.Client(timeout=5.0)
        self._retries = retries

    def send(self, *, sha256: str, fuzzy_hash: str | None, size: int, name: str,
             event_type: str, source_hint: str | None,
             user: str | None = None, metadata: dict | None = None) -> bool:
        """이벤트를 전송한다. 성공(200)이면 True, 재시도 후에도 실패면 False."""
        payload = {
            "sha256": sha256, "fuzzy_hash": fuzzy_hash, "size": size, "name": name,
            "event_type": event_type, "host": self._host,
            "user": user if user is not None else self._user,
            "source_hint": source_hint, "metadata": metadata,
        }
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.post(self._url, json=payload)
                if resp.status_code == 200:
                    return True
                logger.warning("전송 실패 status=%s (시도 %s)", resp.status_code, attempt + 1)
            except httpx.HTTPError as exc:
                logger.warning("전송 예외 %s (시도 %s)", exc, attempt + 1)
        logger.error("전송 최종 실패: name=%s event=%s", name, event_type)
        return False
