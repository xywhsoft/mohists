"""Inspect actual interrupted process calls, never guessing from short results."""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, RUNTIME, start, stop
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        owner = call("session.create", {"body": {"project_id": "mohists", "model_id": "mohists-local",
            "permission_profile": "full-access"}})["data"]["id"]
        ctx = {"project": "mohists", "session": owner}
        def team(action, status=200, **p): return call("mohists.team", {"action": action, **p}, context=ctx, status=status)
        team("start", id="uncertain-tools", goal="Inspect actual pending native side effects")
        for index in range(2):
            task = f"pending-{index}"
            marker = RUNTIME / f"recovery-child-{uuid.uuid4().hex}.json"
            script = "import os,time,json;from pathlib import Path;Path(" + repr(str(marker)) + ").write_text(json.dumps({'pid':os.getpid()}));time.sleep(20)"
            model.server.tool_call = True
            model.server.tool_override = ("exec", {"argv": [sys.executable, "-c", script], "timeout_ms": 25000})
            team("assign", id=task, member=f"worker-{index}", role="worker", title="Interrupted process", prompt="Call the bounded fixture process")
            call("operation.start", {"method": "mohists.team", "params": {"action": "execute", "id": task}}, context=ctx)
            until = time.monotonic() + 8
            while not marker.exists() and time.monotonic() < until: time.sleep(.05)
            assert marker.exists(), "The real process must start before the simulated crash"
            child = json.loads(marker.read_text())["pid"]
            stop()
            # Windows process jobs usually close the owned child with the host.
            # Terminate a surviving child only after matching this exact fixture
            # marker in its command line; never kill an unrelated recycled PID.
            command = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={child}';if($p -and $p.CommandLine.Contains('{marker.name}')){{Stop-Process -Id {child} -Force}}"
            subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)
            start()
            before = len(model.server.requests)
            team("refresh")
            view = team("recovery", id=task)
            pending = view["recovery"]
            assert pending["available"] and pending["resume_required"] and len(pending["items"]) == 1, pending
            tool = pending["items"][0]
            assert tool["tool"] == "exec" and not tool["automatic_retry_safe"] and marker.name in tool["arguments_json"], tool
            assert team("recovery", id=task)["recovery"] == pending
            other = call("session.create", {"body": {"project_id": "mohists"}})["data"]["id"]
            assert call("instance.recovery", {"namespace": f"mohists.{owner}.g1", "id": f"worker-{index}"},
                context={"project": "mohists", "session": other}, status=403)["code"] == "sdk_instance_recovery_scope"
            assert len(model.server.requests) == before, "Inspecting unresolved calls must not run a model"
            stamp = marker.stat().st_mtime_ns
            if index == 0:
                team("cancel", id=task)
                assert team("result", id=task)["state"] == "requires_review", "Cancel cannot discard the user's recovery decision"
                view = team("recovery", id=task)
                result = team("abandon", id=task, expected_revision=view["revision"], expected_member_revision=view["member_state"]["revision"])
                assert result["state"] == "cancelled" and len(model.server.requests) == before
            else:
                result = team("resume", id=task, expected_revision=view["revision"], expected_member_revision=view["member_state"]["revision"],
                    expected_recovery_token=pending["recovery_token"], decisions=[{"tool_call_id": tool["tool_call_id"], "action": "record_uncertain"}])
                assert result["state"] == "succeeded", result
                assert len(model.server.requests) == before + 1
            assert marker.stat().st_mtime_ns == stamp, "Neither abandon nor record_uncertain can repeat the process"
            assert team("result", id=task)["member_state"]["state"] == "idle"
    print("PASS actual pending process inspection, stable native token, owner scope, explicit abandon and continue without replay")


if __name__ == "__main__": main()
