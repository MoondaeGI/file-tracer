"""커스텀 HTTP 예외 계층 테스트."""

import pytest

from app.errors import HttpError, InvalidFingerprintRequestError


def test_http_error_carries_status_and_message() -> None:
    err = HttpError(500, "boom")
    assert err.status_code == 500
    assert str(err) == "boom"


def test_invalid_request_is_400_http_error() -> None:
    err = InvalidFingerprintRequestError("sha256 누락")
    assert isinstance(err, HttpError)
    assert err.status_code == 400
    assert "sha256" in str(err)


def test_invalid_request_can_be_raised() -> None:
    with pytest.raises(HttpError):
        raise InvalidFingerprintRequestError("x")
