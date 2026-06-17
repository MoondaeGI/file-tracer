"""전체 파이프라인 계측: FIRE(디바운서 발화)와 SENT(워커 전송)를 같이 출력(임시)."""

import os
import sys
import time

sys.path.insert(0, r"D:\기타 프로그램\file-tracer\client")

from watchdog.observers import Observer

from agent.cache import FingerprintCache
from agent.debouncer import Debouncer
from agent.models import Task
from agent.watcher import _Handler
from agent.worker import Worker


def b(p):
    return os.path.basename(p) if p else None


watch = sys.argv[1]
state = sys.argv[2]
if os.path.exists(os.path.join(state, "cache.db")):
    os.remove(os.path.join(state, "cache.db"))


class FakeSender:
    def send(self, **kw) -> bool:
        print(f"    SENT event_type={kw['event_type']:9} name={kw['name']}", flush=True)
        return True


worker = Worker(FingerprintCache(os.path.join(state, "cache.db")), FakeSender())


def on_fire(path, pending):
    print(f"  FIRE path={b(path)} type={pending.event_type} moved_from={b(pending.moved_from)}", flush=True)
    worker.submit(Task(path=path, event_type=pending.event_type, moved_from=pending.moved_from))


deb = Debouncer(0.5, on_fire)
h = _Handler(deb, ["~$*", "*.tmp"])
obs = Observer()
obs.schedule(h, watch, recursive=True)
worker.start()
obs.start()
time.sleep(0.5)

p = os.path.join(watch, "x.txt")
print(">> create x.txt")
with open(p, "w", encoding="utf-8") as f:
    f.write("abc def ghi " * 200)
time.sleep(1.2)

print(">> rename x.txt -> x_renamed.txt")
os.rename(p, os.path.join(watch, "x_renamed.txt"))
time.sleep(1.2)

print(">> delete x_renamed.txt")
os.remove(os.path.join(watch, "x_renamed.txt"))
time.sleep(1.2)

obs.stop()
obs.join()
worker.stop()
print(">> done")
