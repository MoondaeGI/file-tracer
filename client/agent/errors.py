"""클라이언트 에이전트 커스텀 예외."""


class ConfigError(Exception):
    """설정(config.toml) 로드·검증 실패."""
