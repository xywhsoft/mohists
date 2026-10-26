"""Compose the real remote HTTP protocol, SDK and plugin in the single Home."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import ROOT, call
from model_fixture import LocalModel

node = shutil.which("node") or str(Path(os.environ["USERPROFILE"]) /
    ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
with LocalModel() as model:
    model.configure(call)
    subprocess.run([node, str(ROOT / "tests/remote_scope.mjs")], cwd=ROOT, check=True)
    assert len(model.server.requests) == 1, "Reconnect/offline handling must not replay a model turn"
print("PASS remote protocol + real native plugin composition, one local model call, no second deployment or online account")
