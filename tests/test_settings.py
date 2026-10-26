"""User defaults, real prompt injection, immutable teams and independent review."""
import copy
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, stop, start
from model_fixture import LocalModel


def main():
    original = call("mohists.settings", {"action": "get"})
    def save(value, revision=None, status=200):
        if revision is None: revision = call("mohists.settings", {"action": "get"})["revision"]
        return call("mohists.settings", {"action": "save", "settings": value, "expected_revision": revision}, status=status)
    try:
        settings = copy.deepcopy(original["value"])
        settings.update(mode="requested", review="always", concurrency=2, max_calls=8)
        saved = save(settings)
        assert save(settings, revision=original["revision"], status=409)["code"] == "sdk_state_conflict"
        wrong = copy.deepcopy(settings); wrong["roles"]["worker"]["agent_id"] = "subagent.missing"
        assert save(wrong, status=400)["code"] == "mohists_binding_missing"
        assert save({**settings, "concurrency": 4}, status=400)["code"] == "mohists_arguments"
        stop(); start()
        assert call("mohists.settings", {"action": "get"}) == {"value": saved["value"], "revision": saved["revision"]}
        with LocalModel() as model:
            model.configure(call)
            owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists",
                "model_id": "mohists-local", "permission_profile": "full-access"}})["data"]["id"]
            ctx = {"project": "mohists", "session": owner}
            def team(action, status=200, **p):
                return call("mohists.team", {"action": action, **p}, context=ctx, status=status)
            denied = call("tool.call", {"tool": "mohists_team", "arguments": {"action": "start", "id": "by-agent", "goal": "No human start"}}, context=ctx)
            assert not denied["success"] and "mohists_requested_only" in denied["text"], denied
            team("start", id="by-user", goal="Review completed changes")
            path = {"project": "mohists", "session": owner}
            run = call("run.start", {"path": path, "body": {"prompt": "A simple direct answer"}}, context=ctx)["data"]
            for _ in range(100):
                result = call("run.get", {"path": {"run": run["id"]}}, context=ctx)["data"]
                if result["terminal"]: break
                time.sleep(.1)
            assert result["state"] == "succeeded", result
            text = "\n".join(str(m.get("content", "")) for m in model.server.requests[0]["messages"])
            assert "Mohists user preferences" in text and "Only start collaboration" in text and "Reserve review turns" in text
            team("assign", id="change", member="writer", role="worker", title="Change", prompt="A bounded change")
            assert team("execute", id="change")["state"] == "succeeded"
            snap = team("get")
            assert team("finish", status=409, expected_revision=snap["revision"])["code"] == "mohists_review_required"
            assert team("get")["state"] == "active", "Failed review gate must not begin a destructive close"
            # A standalone earlier review cannot accidentally approve later work.
            team("assign", id="unrelated", member="reviewer", role="reviewer", title="Unrelated", prompt="Review nothing")
            team("execute", id="unrelated")
            assert team("finish", status=409, expected_revision=team("get")["revision"])["code"] == "mohists_review_required"
            team("assign", id="check", member="reviewer", role="reviewer", title="Review change", prompt="Independently check change", depends_on=["change"])
            team("execute", id="check")
            changed = {**settings, "mode": "automatic", "review": "off", "concurrency": 1, "max_calls": 12}
            save(changed)
            unchanged = team("get")
            assert unchanged["max_calls"] == 8 and unchanged["concurrency"] == 2 and unchanged["review"] == "always"
            assert team("finish", expected_revision=unchanged["revision"])["state"] == "completed"
            assert team("start", id="next", goal="New defaults")["max_calls"] == 12
            team("stop", expected_revision=team("get")["revision"])
            assert len(model.server.requests) == 4, "Saving, inspections and review gates must never invoke a model"
    finally:
        save(original["value"])
    print("PASS persistent user defaults, requested-only admission, real system context, immutable bindings and independent review gate")


if __name__ == "__main__": main()
