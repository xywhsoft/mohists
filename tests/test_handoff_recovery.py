"""Crash the actual main speaker, explicitly recover and continue requested work."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, request, stop, start
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists",
            "model_id": "mohists-local", "permission_profile": "full-access"}})["data"]["id"]
        ctx = {"project": "mohists", "session": owner}
        def team(action, **params):
            return call("mohists.team", {"action": action, **params}, context=ctx)
        team("start", id="main-recovery", goal="Native main recovery must finish requested dependencies")
        team("assign", id="seed", member="writer", role="worker", title="Seed", prompt="Remember seed context")
        team("execute", id="seed")
        team("handoff", member="writer", expected_revision=team("get")["revision"])
        model.server.blocked = True; model.server.entered.clear(); model.server.release.clear()
        run = call("run.start", {"path": ctx, "body": {"prompt": "RECOVER-this-main-input"}}, context=ctx)["data"]
        assert model.server.entered.wait(3)
        job = next(j for j in team("get")["assignment_items"] if j.get("main_run_id") == run["id"])
        team("assign", id="after-recovery", member="reviewer", role="reviewer", title="Review resumed main work",
            prompt="Review the completed recovered turn", depends_on=[job["id"]])
        team("run", id="after-recovery")
        before = len(model.server.requests); stop(); model.server.release.set(); model.server.blocked = False; start()
        assert len(model.server.requests) == before, "Restart must not replay a main speaker"
        team("refresh")
        interrupted = team("recovery", id=job["id"])
        assert interrupted["state"] == "requires_review" and interrupted["recovery"]["items"] == [], interrupted
        assert len(model.server.requests) == before
        model.server.reply = "Recovered actual main speaker"
        resumed = team("resume", id=job["id"], expected_revision=interrupted["revision"],
            expected_member_revision=interrupted["member_state"]["revision"],
            expected_recovery_token=interrupted["recovery"]["recovery_token"])
        assert resumed["state"] == "succeeded", resumed
        complete = team("wait", timeout_ms=10000)
        assert next(j for j in complete["assignment_items"] if j["id"] == "after-recovery")["state"] == "succeeded", complete
        assert complete["calls_used"] == 4 and not complete["active"]
        assert len(model.server.requests) == before + 2, "Only explicit resume plus already requested reviewer may run"
        recovered = model.server.requests[before]
        users = [m.get("content") for m in recovered["messages"] if m["role"] == "user"]
        assert users.count("RECOVER-this-main-input") == 1
        page = request("GET", f"/api/v1/projects/mohists/sessions/{owner}/events?after=0&limit=32")[2]["data"]
        assert any(e["kind"] == "model_text_delta" and e["text"] == model.server.reply and e["source"]["member"] == "writer" for e in page["items"])
        assert team("get")["speaker"] == "writer"
    print("PASS actual main-speaker crash, explicit native recovery, single preserved input, cumulative budget and dependent queue continuation")


if __name__ == "__main__": main()
