"""Run the complete Mohists regression sequentially in its existing Home."""
from __future__ import annotations
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from dev import ROOT, RUNTIME, call, environment, write_json

CASES = (
    "test_environment.py", "test_state_scale.py", "test_team.py", "test_execution.py", "test_control.py",
    "test_recovery.py", "test_scheduler.py", "test_history.py", "test_policy.py",
    "test_pending_recovery.py", "test_origin.py", "test_settings.py", "test_coordinator_flow.py",
    "test_run_route.py", "test_handoff.py", "test_handoff_recovery.py",
    "test_execution_view.py", "test_remote_scope.py", "test_portability.py", "test_distribution.py",
)


def main():
    assert call("mohists.status")["plugin"] == "mohists", "Start the single development host first"
    node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "home": "runtime/home",
        "host": environment(), "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "One existing XS/TCC instance; deterministic local model and network peers. No vendor, Android hardware or real dual-device claims.",
        "passed": False, "cases": []}
    output = RUNTIME / "acceptance/full-regression.json"
    commands = [(name, [sys.executable, "-u", str(ROOT / "tests" / name)]) for name in CASES]
    commands.append(("store.test.mjs", [node, "--test", str(ROOT / "tests/store.test.mjs")]))
    for name, command in commands:
        row = {"name": name, "state": "running"}
        report["cases"].append(row)
        write_json(output, report)
        began = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        row.update(state="passed" if result.returncode == 0 else "failed", exit_code=result.returncode,
            elapsed_seconds=round(time.monotonic() - began, 3))
        write_json(output, report)
        print(f"{row['state'].upper()} {name} ({row['elapsed_seconds']}s)", flush=True)
        if result.returncode:
            # Persist facts, not HTTP payloads or model transcripts.
            print((result.stdout + result.stderr)[-3500:], file=sys.stderr)
            raise SystemExit(result.returncode)
    report.update(passed=True, finished_at=datetime.now(timezone.utc).isoformat())
    write_json(output, report)
    print(f"PASS {len(commands)} sequential regression cases in the existing Home", flush=True)


if __name__ == "__main__":
    main()
