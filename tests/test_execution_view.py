"""Inspect effective speaker/model/context without opening or running a ledger."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        cfg = call("product.models.config.get")
        patch = {k:v for k,v in cfg["data"].items() if k != "runtime_override"}
        small = next(m for m in patch["items"] if m["id"] == "mohists-local").copy()
        small.update(id="mohists-small", name="Small member model", wire_model="member-wire")
        small["window"] = {**small["window"], "context_tokens": 65536, "max_input_tokens": 60000,
            "max_output_tokens": 4096, "output_reserve_tokens": 4096, "summary_tokens": 1024}
        patch["items"] = [m for m in patch["items"] if m["id"] != small["id"]] + [small]
        call("product.settings.by_domain.put", {"path": {"domain": "models"}, "revision": cfg["revision"], "body": {"schema_version": 1, "patch": patch}})
        owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists", "model_id": "mohists-local"}})["data"]["id"]
        ctx = {"project": "mohists", "session": owner}
        def team(action, **p): return call("mohists.team", {"action": action, **p}, context=ctx)
        def view(): return call("session.execution", context=ctx)
        assert view()["model_id"] == "mohists-local" and "target" not in view()
        team("start", id="execution-view", goal="Keep the real speaker's model and context distinct")
        team("configure", expected_revision=team("get")["revision"], roles={"worker": {"agent_id": "subagent.mohists-worker", "model_id": "mohists-small"}})
        team("assign", id="seed", member="writer", role="worker", title="Seed", prompt="Remember the smaller member model")
        executed = team("execute", id="seed"); assert executed["state"] == "succeeded", executed
        team("handoff", member="writer", expected_revision=team("get")["revision"])
        before = len(model.server.requests); projected = view()
        assert projected["available"] and projected["model_id"] == "mohists-small", projected
        assert projected["target"]["id"] == "writer" and projected["target"]["state"] == "idle", projected
        checkpoint = projected["checkpoint"]
        assert checkpoint["model_id"] == "mohists-small" and checkpoint["context_window_tokens"] == 65536, checkpoint
        assert checkpoint["input_tokens"] == 20 and checkpoint["output_tokens"] == 5 and checkpoint["usage_available"], checkpoint
        assert checkpoint["context"]["exact"] and checkpoint["context"]["estimated_input_tokens"] >= 25, checkpoint
        assert model.server.requests[-1]["model"] == "member-wire"
        native = {"namespace": f"mohists.{owner}.g1", "id": "writer"}
        revision = call("instance.get", native, context=ctx)["revision"]
        detail = call("session.get", {"path": ctx}, context=ctx)["data"]
        assert detail["model_id"] == "mohists-local" and detail["agent_id"] == "agent.mohists"
        assert detail["execution"] == projected and projected == view()
        assert call("instance.get", native, context=ctx)["revision"] == revision and len(model.server.requests) == before
        # A target hook cannot make a foreign conversation's member readable.
        foreign = call("session.create", {"body": {"project_id": "mohists", "model_id": "mohists-local"}})["data"]["id"]
        call("instance.create", {**native, "id": "foreign", "agent_id": "subagent.mohists-worker", "model_id": "mohists-small"}, context={**ctx, "session": foreign})
        state = {"namespace": "mohists." + owner, "key": "team"}
        saved = call("state.get", state, context=ctx)
        try:
            wrong = {**saved["value"], "speaker": "foreign"}
            call("state.compare_exchange", {**state, "expected_revision": saved["revision"], "value": wrong}, context=ctx)
            assert call("session.execution", context=ctx, status=403)["code"] == "sdk_execution_scope"
            unavailable = call("session.get", {"path": ctx}, context=ctx)["data"]
            assert not unavailable["execution"]["available"] and unavailable["model_id"] == "mohists-local"
            assert len(model.server.requests) == before
        finally:
            current = call("state.get", state, context=ctx)
            call("state.compare_exchange", {**state, "expected_revision": current["revision"], "value": saved["value"]}, context=ctx)
        team("handoff", member="coordinator", expected_revision=team("get")["revision"])
        assert view()["model_id"] == "mohists-local" and "target" not in view()
        assert len(model.server.requests) == 1
    print("PASS effective model/context, unchanged coordinator, side-effect-free inspection and native target ownership")


if __name__ == "__main__": main()
