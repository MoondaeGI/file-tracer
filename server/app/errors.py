"""시스템 경계에서 사용하는 커스텀 HTTP 예외 계층."""


class HttpError(Exception):
    """status_code를 동반하는 기본 HTTP 예외."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidFingerprintRequestError(HttpError):
    """지문 등록 요청이 유효하지 않을 때(필수 필드 누락·잘못된 모드) 발생."""

    def __init__(self, message: str) -> None:
        super().__init__(400, message)
