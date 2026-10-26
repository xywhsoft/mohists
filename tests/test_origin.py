"""Prove root C Agent provenance using the actual sole project deployment."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, stop, start, RUNTIME
from model_fixture import LocalModel


def main():
    roles = RUNTIME / "home/agents"
    roles.mkdir(exist_ok=True)
    modules = RUNTIME / "home/modules/agents"
    modules.mkdir(parents=True, exist_ok=True)
    source, config = modules / "mohists-origin.c", roles / "mohists-origin.md"
    assert not source.exists() and not config.exists(), "Keep an existing user role"
    try:
        source.write_text(Path(__file__).with_name("origin-role.c").read_text(encoding="utf-8"), encoding="utf-8")
        config.write_text("---\nschema: mdo.agent.v1\nname: Origin acceptance\ncode: true\n---\n", encoding="utf-8")
        stop(); start()
        with LocalModel() as model:
            model.configure(call)
            owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists-origin",
                "model_id": "mohists-local", "permission_profile": "full-access"}})["data"]["id"]
            ctx = {"project": "mohists", "session": owner}
            call("mohists.team", {"action": "start", "id": "origin", "goal": "Check root C provenance"}, context=ctx)
            path = {"project": "mohists", "session": owner}
            run = call("run.start", {"path": path, "body": {"prompt": "Root origin test"}}, context=ctx)["data"]
            for _ in range(120):
                result = call("run.get", {"path": {"run": run["id"]}}, context=ctx)["data"]
                if result["terminal"]: break
                time.sleep(.1)
            assert result["state"] == "succeeded", result
            facts = call("state.get", {"namespace": owner, "key": "facts"}, context=ctx)["value"]
            assert facts["origin"] == facts["background"]["origin"] == "agent", facts
            assert not facts["run"] and not facts["member"], "Exercise the root C context without legacy identity hints"
            inbox = call("mohists.team", {"action": "inbox", "to": "coordinator"}, context=ctx)
            assert inbox["items"][0]["body"]["source"] == "agent", inbox
            assert call("sdk.context", context={**ctx, "origin": "agent"})["origin"] == "user"
            assert len(model.server.requests) == 1
    finally:
        source.unlink(missing_ok=True); config.unlink(missing_ok=True)
        stop(); start()
    print("PASS real root C Agent origin, background propagation, passive message source and user-only recovery")


if __name__ == "__main__": main()
