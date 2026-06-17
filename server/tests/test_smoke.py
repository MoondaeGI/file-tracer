"""패키지 임포트가 가능한지 확인하는 스모크 테스트."""


def test_app_package_imports() -> None:
    import app  # noqa: F401
