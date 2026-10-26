"""Read-only role ceilings apply even to custom writable agent bindings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, RUNTIME
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        owner = call("session.create", {"body": {"project_id": "mohists", "model_id": "mohists-local",
            "permission_profile": "full-access"}})["data"]["id"]
        ctx = {"project": "mohists", "session": owner}
        def team(action, status=200, **p):
            return call("mohists.team", {"action": action, **p}, context=ctx, status=status)
        team("start", id="policy", goal="Respect the research role regardless of the selected implementation")
        team("configure", expected_revision=team("get")["revision"], roles={
            "researcher": {"agent_id": "subagent.mohists-worker", "model_id": ""}})
        team("assign", id="read", member="reader", role="researcher", title="Research", prompt="Read only")
        target = RUNTIME / "policy-must-not-exist.txt"
        assert not target.exists()
        model.server.tool_call = True
        model.server.tool_override = ("write", {"path": str(target), "content": "must not be written"})
        result = team("execute", id="read")
        assert result["state"] == "succeeded", result
        assert len(model.server.requests) == 2, "Tool rejection must allow a subsequent model response"
        messages = model.server.requests[-1]["messages"]
        failure = next(m["content"] for m in messages if m["role"] == "tool")
        assert "read-only" in str(failure), failure
        assert not target.exists(), "A researcher using a writable custom binding must not write"
        history = team("history", member="reader", limit=64)["items"]
        assert any(e["kind"] == "tool_done" and not e["success"] for e in history)
        assert any(e["kind"] == "model_text_delta" for e in history)
        team("stop", expected_revision=team("get")["revision"])
        team("start", id="new", goal="New group")
        assert team("cancel", status=409, id="read", expected_generation=1)["code"] == "mohists_stale_group"
        old = team("history", member="reader", generation=1, limit=64)["items"]
        assert old == history, "Old windows must explicitly select the old native transcript"
        team("stop", expected_revision=team("get")["revision"])
        team("start", id="large", goal="g" * 4096)
        assert team("assign", status=413, id="large", member="reader", role="researcher", title="Large",
            prompt="p" * 4096)["code"] == "mohists_input_limit"
        assert team("get")["assignment_items"] == [], "Invalid combined input must not create a stranded job"
    print("PASS custom read-only ceiling, recoverable tool denial, generation fencing, historical selection and admission size validation")


if __name__ == "__main__": main()
