"""Cancel and revise real running members using native asynchronous operations."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        owner = call("session.create", {"body": {"project_id": "default", "model_id": "mohists-local",
            "permission_profile": "full-access"}})["data"]["id"]
        ctx = {"project": "default", "session": owner}
        def team(action, status=200, **params):
            return call("mohists.team", {"action": action, **params}, context=ctx, status=status)
        def assign(id, member="writer", role="worker"):
            return team("assign", id=id, member=member, role=role, title=id, prompt="Complete the bounded task")
        def background(id):
            model.server.blocked = True
            model.server.entered.clear()
            model.server.release.clear()
            operation = call("operation.start", {"method": "mohists.team", "params": {"action": "execute", "id": id}}, context=ctx)
            assert model.server.entered.wait(3), "Member failed to enter the actual model request"
            return operation
        def drained(op):
            model.server.release.set()
            assert call("operation.wait", {"id": op["id"], "timeout_ms": 5000}, context=ctx)["terminal"]
            value = call("operation.result", {"id": op["id"]}, context=ctx)
            call("operation.release", {"id": op["id"]}, context=ctx)
            return value
        team("start", id="first", goal="A goal that can be cancelled")
        assign("change")
        assign("second-writer", "writer-b")
        op = background("change")
        assert team("execute", status=409, id="second-writer")["code"] == "mohists_writer_busy"
        snapshot = team("get")
        assert snapshot["active"] == ["change"] and snapshot["calls_used"] == 1
        team("stop", expected_revision=snapshot["revision"])
        assert drained(op)["state"] == "cancelled"
        final = team("get")
        assert final["active"] == [] and final["state"] == "cancelled", final
        assert team("result", id="second-writer")["state"] == "cancelled"
        assign_args = dict(id="late", member="late", role="worker", title="late", prompt="Must not run")
        assert team("assign", status=409, **assign_args)["code"] == "mohists_team_ended"
        # A new group may reuse ordinary task and member names without seeing
        # previous native snapshots or the plugin's prior-generation metadata.
        assert team("start", id="second", goal="Revised work group")["generation"] == 2
        assign("change")
        op = background("change")
        snapshot = team("get")
        team("revise", goal="Use the new user constraints", expected_revision=snapshot["revision"])
        assert drained(op)["state"] == "stale"
        current = team("get")
        assert current["state"] == "active" and current["constraint_revision"] == 2 and current["active"] == []
        assert current["goal"] == "Use the new user constraints" and current["calls_used"] == 1
        assert team("execute", status=409, id="change")["code"] == "mohists_stale_task"
        model.server.blocked = False
        assign("new-task", "new-reader", "researcher")
        assert team("execute", id="new-task")["state"] == "succeeded"
        snapshot = team("get")
        assert team("finish", expected_revision=snapshot["revision"])["state"] == "completed"
        assert team("start", id="third", goal="Another independent task")["generation"] == 3
        assert len(model.server.requests) == 3, "Stop/revise/finish must not invoke extra model requests"
    print("PASS single writer, active cancellation, drain, stale result fencing, constraint revision and new-group identity reuse")


if __name__ == "__main__": main()
