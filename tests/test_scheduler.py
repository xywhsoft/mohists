"""One persistent queue: bounded background turns and event-based waiting."""
import sys
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
        team("start", id="queue", goal="Complete independent research and two serialized changes")
        jobs = [("write-one", "worker"), ("write-two", "worker"), ("read-one", "researcher"),
            ("read-two", "researcher"), ("read-three", "researcher"), ("review", "reviewer")]
        for id, role in jobs:
            team("assign", id=id, member=id, role=role, title=id, prompt="Execute marker-" + id,
                depends_on=["write-one", "write-two"] if id == "review" else [])
        model.server.blocked = True
        snapshot = team("run")
        assert model.server.entered.wait(3)
        snapshot = team("get")
        assert len(snapshot["active"]) == 3, snapshot
        assert "write-one" in snapshot["active"] and "write-two" not in snapshot["active"], snapshot
        assert snapshot["calls_used"] == 3
        team("run")  # A second UI/window intent must reuse existing admissions.
        assert team("get")["calls_used"] == 3
        assert len(team("wait", timeout_ms=20)["active"]) == 3
        model.server.blocked = False
        model.server.release.set()
        snapshot = team("wait", timeout_ms=10000)
        # A completion-to-next-admission boundary may coincide with a snapshot;
        # another passive wait must finish the requested queue without a model
        # asking status questions or manually scheduling each dependency.
        for _ in range(8):
            if all(t["state"] == "completed" for t in snapshot["tasks"]["items"]): break
            snapshot = team("wait", timeout_ms=1000)
        assert all(t["state"] == "completed" for t in snapshot["tasks"]["items"]), snapshot
        assert snapshot["active"] == [] and snapshot["calls_used"] == 6
        assert len(model.server.requests) == 6, "Queue coordination must never call a status/manager model"
        assert len(snapshot["members"]) == 6
        call("mohists.team", {"action": "execute_reserved", "id": "read-one"}, context=ctx, status=403)
        assert len(model.server.requests) == 6
        # Shared native resources are a waiting condition, not a failed task
        # or a consumed model budget. No new test environment is created.
        other = call("session.create", {"body": {"project_id": "default", "model_id": "mohists-local"}})["data"]["id"]
        other_ctx = {"project": "default", "session": other}
        held = [call("operation.start", {"method": "events.wait", "params": {"timeout_ms": 30000,
            "topic": "mohists.test.hold"}}, context=other_ctx) for _ in range(8)]
        try:
            snap = team("get")
            team("finish", expected_revision=snap["revision"])
            team("start", id="native-slots", goal="Wait for the global SDK resource pool")
            team("assign", id="wait-resource", member="waiter", role="researcher", title="Wait", prompt="Execute after shared slots are free")
            waiting = team("run")
            assert waiting["calls_used"] == 0 and waiting["active"] == [], waiting
            assert team("result", id="wait-resource")["state"] == "queued"
            assert len(model.server.requests) == 6
        finally:
            for op in held:
                call("operation.cancel", {"id": op["id"]}, context=other_ctx)
                call("operation.wait", {"id": op["id"], "timeout_ms": 2000}, context=other_ctx)
                call("operation.release", {"id": op["id"]}, context=other_ctx)
        completed = team("wait", timeout_ms=10000)
        assert completed["calls_used"] == 1 and not completed["active"], completed
        assert team("result", id="wait-resource")["state"] == "succeeded"
        assert len(model.server.requests) == 7
    print("PASS background admissions, duplicate run reuse, three member slots, one writer, dependency scheduling and event waits")


if __name__ == "__main__": main()
