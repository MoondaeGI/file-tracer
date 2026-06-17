"""에이전트 진입점: 설정 로드·검증 → 초기 스캔 → 감시 상주.

실행(사용자 확인 후): .venv\\Scripts\\python.exe -m agent.main client\\config.toml
캐시·로그는 감시 폴더 밖(client/ 옆)에 둔다(자기 이벤트 루프 방지, 설계 §3).
"""

import getpass
import logging
import socket
import sys
import time
from pathlib import Path

from agent.cache import FingerprintCache
from agent.config import load_config
from agent.scanner import initial_scan
from agent.sender import Sender
from agent.watcher import build_watcher

logger = logging.getLogger("agent")

_STATE_DIR = Path(__file__).resolve().parent.parent / ".state"  # client/.state (감시 폴더 밖)


def main(config_path: str) -> None:
    """에이전트를 구동한다."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config(Path(config_path))

    _STATE_DIR.mkdir(exist_ok=True)
    cache = FingerprintCache(_STATE_DIR / "cache.db")

    logger.info("초기 스캔 시작...")
    initial_scan(config.watch_paths, config.ignore_globs, cache)

    sender = Sender(config.server_url, host=socket.gethostname(), user=getpass.getuser())
    watcher = build_watcher(
        watch_paths=config.watch_paths, ignore_globs=config.ignore_globs,
        cache=cache, sender=sender, debounce_seconds=config.debounce_seconds,
    )
    watcher.start()
    logger.info("감시 시작: %s", [str(p) for p in config.watch_paths])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("종료 중...")
    finally:
        watcher.stop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m agent.main <config.toml>")
        sys.exit(1)
    main(sys.argv[1])
