"""Keep one local model available during manual browser acceptance in this Home.
Stop with runtime/ui-fixture.stop; expires after 20 minutes. Never calls vendors.
"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, RUNTIME
from model_fixture import LocalModel

stop = RUNTIME / "ui-fixture.stop"
stop.unlink(missing_ok=True)
with LocalModel() as model:
    model.configure(call)
    model.server.reply = "已按新的指导完成任务，并保留原成员上下文。"
    print("Local UI model ready; no supplier calls", flush=True)
    until = time.monotonic() + 1200
    while not stop.exists() and time.monotonic() < until: time.sleep(.5)
    print(f"Completed {len(model.server.requests)} local model requests", flush=True)
