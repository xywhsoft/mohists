"""Restart the sole project mdo, proving recovery requires a user decision."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, start, stop
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        owner = call("session.create", {"body": {"project_id": "default", "model_id": "mohists-local",
            "permission_profile": "full-access"}})["data"]["id"]
        ctx = {"project": "default", "session": owner}
        def team(action, status=200, **params):
            return call("mohists.team", {"action": action, **params}, context=ctx, status=status)
        def crash(id):
            model.server.blocked = True
            model.server.entered.clear()
            model.server.release.clear()
            call("operation.start", {"method": "mohists.team", "params": {"action": "execute", "id": id}}, context=ctx)
            assert model.server.entered.wait(3)
            before = len(model.server.requests)
            stop()
            model.server.blocked = False
            model.server.release.set()
            start()
            assert len(model.server.requests) == before, "Restart must never replay an uncertain request"
            assert team("get")["active"] == [id], "Admission must survive process loss"
            team("refresh")
            interrupted = team("result", id=id)
            assert interrupted["state"] == "requires_review" and interrupted["member_state"]["state"] == "requires_review", interrupted
            assert team("get")["active"] == []
            return interrupted, before
        team("start", id="recover", goal="Resume or abandon only after explicit review")
        team("assign", id="first", member="worker", role="worker", title="First", prompt="marker-recover-first")
        interrupted, before = crash("first")
        assert team("execute", id="first", status=409)["code"] == "mohists_task_admitted"
        assert team("resume", id="first", status=409, expected_revision=0)["code"] == "mohists_conflict"
        current = team("result", id="first")
        assert team("get")["calls_used"] == 1, "Rejected stale recovery must not consume a budget slot"
        result = team("resume", id="first", expected_revision=current["revision"],
            expected_member_revision=current["member_state"]["revision"])
        assert result["state"] == "succeeded", result
        assert len(model.server.requests) == before + 1
        users = [m["content"] for m in model.server.requests[-1]["messages"] if m["role"] == "user"]
        assert sum("marker-recover-first" in u for u in users) == 1, users
        team("assign", id="second", member="worker", role="worker", title="Second", prompt="marker-recover-second")
        interrupted, before = crash("second")
        abandoned = team("abandon", id="second", expected_revision=interrupted["revision"],
            expected_member_revision=interrupted["member_state"]["revision"])
        assert abandoned["state"] == "cancelled", abandoned
        assert len(model.server.requests) == before, "Abandon must not invoke a model"
        assert team("result", id="second")["member_state"]["state"] == "idle"
        snapshot = team("get")
        assert snapshot["calls_used"] == 3 and snapshot["active"] == []
        team("assign", id="third", member="worker", role="worker", title="Third", prompt="New work after explicit abandon")
        assert team("execute", id="third")["state"] == "succeeded"
        assert team("get")["calls_used"] == 4
    print("PASS restart without replay, revision-checked explicit resume/abandon, preserved turn budgets and member reuse")


if __name__ == "__main__": main()
