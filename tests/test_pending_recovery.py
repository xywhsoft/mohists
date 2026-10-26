"""Inspect actual interrupted process calls, never guessing from short results."""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, request, RUNTIME, start, stop
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        owner = call("session.create", {"body": {"project_id": "mohists", "model_id": "mohists-local",
            "permission_profile": "full-access"}})["data"]["id"]
        ctx = {"project": "mohists", "session": owner}
        def team(action, status=200, **p): return call("mohists.team", {"action": action, **p}, context=ctx, status=status)
        team("start", id="uncertain-tools", goal="Inspect actual pending native side effects")
        for index in range(3):
            task = f"pending-{index}"
            marker = RUNTIME / f"recovery-child-{uuid.uuid4().hex}.json"
            script = "import os,time,json;from pathlib import Path;p=Path(" + repr(str(marker)) + ");t=p.with_name(p.name+'.tmp');t.write_text(json.dumps({'pid':os.getpid()}));t.replace(p);time.sleep(20)"
            model.server.tool_call = True
            model.server.tool_override = ("exec", {"argv": [sys.executable, "-c", script], "timeout_ms": 25000})
            team("assign", id=task, member=f"worker-{index}", role="worker", title="Interrupted process", prompt="Call the bounded fixture process")
            call("operation.start", {"method": "mohists.team", "params": {"action": "execute", "id": task}}, context=ctx)
            until = time.monotonic() + 15
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
            if index == 1: team("cancel", id=task)
            team("refresh")
            view = team("recovery", id=task)
            pending = view["recovery"]
            assert pending["available"] and pending["resume_required"] and len(pending["items"]) == 1, pending
            tool = pending["items"][0]
            assert tool["tool"] == "exec" and not tool["automatic_retry_safe"] and marker.name in tool["arguments_json"], tool
            assert team("recovery", id=task)["recovery"] == pending
            other = call("session.create", {"body": {"project_id": "mohists"}})["data"]["id"]
            generation = team("get")["generation"]
            assert call("instance.recovery", {"namespace": f"mohists.{owner}.g{generation}", "id": f"worker-{index}"},
                context={"project": "mohists", "session": other}, status=403)["code"] == "sdk_instance_recovery_scope"
            assert len(model.server.requests) == before, "Inspecting unresolved calls must not run a model"
            assert team("finish", expected_revision=team("get")["revision"], status=409)["code"] == "mohists_review_pending"
            team("assign", id=f"guarded-{index}", member=f"guarded-{index}", role="worker", title="Wait for uncertainty", prompt="Must not write before the prior decision")
            assert team("execute", id=f"guarded-{index}", status=409)["code"] == "mohists_unresolved_writer"
            target = RUNTIME / f"unresolved-write-{uuid.uuid4().hex}.txt"
            code, _, denied = request("POST", "/api/v1/application/call", {"method": "tool.call", "params": {
                "tool": "write", "arguments": {"path": str(target), "content": "must not write"}}, "context": ctx})
            wrote = target.exists()
            if wrote: target.unlink()
            assert not wrote and (code != 200 or not denied["data"].get("success")), denied
            assert len(model.server.requests) == before
            stamp = marker.stat().st_mtime_ns
            if index < 2:
                team("cancel", id=task)
                assert team("result", id=task)["state"] == "requires_review", "Cancel cannot discard the user's recovery decision"
                if index == 1:
                    team("stop", expected_revision=team("get")["revision"])
                    assert team("start", id="blocked-new-group", goal="Do not hide uncertainty", status=409)["code"] == "mohists_review_pending"
                view = team("recovery", id=task)
                result = team("abandon", id=task, expected_revision=view["revision"], expected_member_revision=view["member_state"]["revision"])
                assert result["state"] == "cancelled" and len(model.server.requests) == before, result
            else:
                result = team("resume", id=task, expected_revision=view["revision"], expected_member_revision=view["member_state"]["revision"],
                    expected_recovery_token=pending["recovery_token"], decisions=[{"tool_call_id": tool["tool_call_id"], "action": "record_uncertain"}])
                assert result["state"] == "succeeded", result
                assert len(model.server.requests) == before + 1
            assert marker.stat().st_mtime_ns == stamp, "Neither abandon nor record_uncertain can repeat the process"
            assert team("result", id=task)["member_state"]["state"] == "idle"
            if index == 1: team("start", id="after-explicit-decision", goal="Continue after the unknown turn was explicitly abandoned")
    print("PASS actual pending process inspection, stable native token, owner scope, explicit abandon and continue without replay")


if __name__ == "__main__": main()
