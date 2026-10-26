"""Actual member loops: multi-turn roles, native outcomes, messages and budgets."""
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
        team("start", id="implementation", goal="Study a small change and independently check it")
        snap = team("get")
        roles = {role: {"agent_id": "subagent.mohists-" + role, "model_id": ""}
            for role in ("researcher", "worker", "reviewer")}
        team("configure", expected_revision=snap["revision"], roles=roles, max_calls=2)
        assignment = team("assign", id="inspect", member="reader", role="researcher", title="Inspect", prompt="Remember marker-FIRST")
        assert assignment["model_id"] == "mohists-local", "Default binding must inherit the owning conversation model"
        call("mohists.team", {"action": "assign", "id": "followup", "member": "reader", "role": "researcher", "title": "Follow up",
            "prompt": "Then marker-SECOND", "depends_on": ["inspect"]}, context={**ctx, "extension": "plugin.mohists"})
        team("assign", id="review", member="reviewer", role="reviewer", title="Review", prompt="Independent check", depends_on=["followup"])
        assert not model.server.requests, "Admission and listing must not call models"
        team("execute", id="followup", status=409)
        assert not model.server.requests
        result = team("execute", id="inspect")
        assert result["state"] == "succeeded", result
        first = team("result", id="inspect")
        assert first["native"]["result"]["text"] == "member result 1", first
        assert first["native"]["result"]["text_truncated"] is False
        team("execute", id="inspect", status=409)
        assert len(model.server.requests) == 1, "Repeated execute must never duplicate a turn"
        assert team("execute", id="followup")["state"] == "succeeded"
        assert len(model.server.requests) == 2
        users = [m["content"] for m in model.server.requests[-1]["messages"] if m["role"] == "user"]
        assert any("marker-FIRST" in p for p in users) and any("marker-SECOND" in p for p in users), users
        tools = [t["function"]["name"] for t in model.server.requests[0].get("tools", [])]
        assert "write" not in tools and "edit" not in tools, "Research role must remain read-only under a full-access parent"
        assert "mohists_mail" in tools and "mohists_team" not in tools, tools
        assert team("execute", id="review", status=429)["code"] == "mohists_budget"
        assert len(model.server.requests) == 2
        sent = team("message", to="reader", message_id="human-guidance", text="Check the new constraint")
        assert team("message", to="reader", message_id="human-guidance", text="Check the new constraint") == sent
        inbox = team("inbox", to="reader")
        assert inbox["items"][0]["body"]["source"] == "user", inbox
        team("ack", to="reader", message_id="human-guidance")
        assert team("inbox", to="reader")["items"] == []
        team("message", to="nonexistent", message_id="wrong", text="No", status=404)
        snapshot = team("get")
        assert snapshot["calls_used"] == 2 and snapshot["active"] == []
        empty = call("instance.step", {"namespace": f"mohists.{owner}.g1", "id": "reviewer"}, context=ctx)
        assert empty["no_work"] and empty["state"] == "idle", empty
        other = call("session.create", {"body": {"project_id": "default"}})["data"]["id"]
        denied = call("instance.step", {"namespace": f"mohists.{owner}.g1", "id": "reader"},
            context={"project": "default", "session": other}, status=403)
        assert denied["code"] == "sdk_instance_scope", denied
        assert len(snapshot["members"]) == 2, "Follow-ups must reuse the native member"
        assert len(model.server.requests) == 2, "Messages and snapshots must not wake models"
        invoked = call("tool.call", {"project": "default", "session": owner, "tool": "mohists_mail",
            "arguments": {"action": "get"}}, context=ctx)
        assert invoked["success"], invoked
        assert '"calls_used":2' in invoked["text"].replace(" ", "")
    print("PASS actual multi-turn native loops, dependencies, read-only role, results, passive messages and cumulative budget")


if __name__ == "__main__": main()
