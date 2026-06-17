"""watchdog 이벤트를 지정 시간 동안 watch만 하며 출력(임시). argv: <watchdir> <seconds>."""

import os
import sys
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class H(FileSystemEventHandler):
    def on_any_event(self, event) -> None:
        dest = getattr(event, "dest_path", None)
        print(f"EVENT type={event.event_type:9} src={os.path.basename(event.src_path)}"
              + (f" dest={os.path.basename(dest)}" if dest else ""), flush=True)


watch = sys.argv[1]
seconds = float(sys.argv[2])
obs = Observer()
obs.schedule(H(), watch, recursive=True)
obs.start()
time.sleep(seconds)
obs.stop()
obs.join()
