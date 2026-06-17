"""Python 에이전트 호스트 진입점: 한 프로세스에서 코어 + FS agent + 커넥터 intake를 띄운다.

실행(사용자 확인 후):
  Set-Location client
  ..\\server\\.venv\\Scripts\\python.exe -m main config.toml
"""

import getpass
import logging
import socket
import threading
import time
from pathlib import Path

from agent.cache import FingerprintCache
from agent.config import load_config
from agent.scanner import initial_scan
from agent.watcher import build_watcher
from connector.agent import serve as serve_connector
from core.core import CollectorCore
from core.sender import Sender

logger = logging.getLogger("host")
_STATE_DIR = Path(__file__).resolve().parent / ".state"


def main(config_path: str) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config(Path(config_path))
    _STATE_DIR.mkdir(exist_ok=True)
    cache = FingerprintCache(_STATE_DIR / "cache.db")

    sender = Sender(config.server_url, host=socket.gethostname(), user=getpass.getuser())
    core = CollectorCore(sender)
    core.start()

    initial_scan(config.watch_paths, config.ignore_globs, cache)
    watcher = build_watcher(
        watch_paths=config.watch_paths, ignore_globs=config.ignore_globs,
        cache=cache, core=core, debounce_seconds=config.debounce_seconds)
    watcher.start()

    intake_port = 8765
    httpd = serve_connector(core, host=socket.gethostname(), port=intake_port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("호스트 시작: FS 감시 + 커넥터 intake(:%s)", intake_port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("종료 중...")
    finally:
        httpd.shutdown()
        watcher.stop()
        core.stop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python -m main <config.toml>")
        sys.exit(1)
    main(sys.argv[1])
