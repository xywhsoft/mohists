"""Real Mohists handoff uses native histories, admission and main Run streams."""
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
        def team(action, status=200, **p):
            return call("mohists.team", {"action": action, **p}, context=ctx, status=status)
        def select(member, **p):
            return team("handoff", member=member, expected_revision=team("get")["revision"], **p)
        def run(prompt):
            return call("run.start", {"path": ctx, "body": {"prompt": prompt}}, context=ctx)["data"]
        def wait(id):
            for _ in range(200):
                value = call("run.get", {"path": {"run": id}}, context=ctx)["data"]
                if value["terminal"]: return value
                time.sleep(.04)
            raise AssertionError(value)
        team("start", id="handoff", goal="Preserve continuity and actual author provenance")
        team("configure", expected_revision=team("get")["revision"], max_calls=4, review="off")
        # A model-created assignment later run by the user remains agent text.
        tool = call("tool.call", {"tool": "mohists_team", "arguments": {"action": "assign", "id": "seed",
            "member": "scholar", "role": "researcher", "title": "Remember", "prompt": "SEED-only-member-context"}}, context=ctx)
        assert tool["success"], tool
        team("run", id="seed"); team("wait", timeout_ms=10000)
        history = team("history", member="scholar", limit=64)
        assert next(e["source"] for e in history["items"] if e["kind"] == "agent_start") == "agent"
        assert team("handoff", status=409, member="scholar", expected_revision=0)["code"] == "mohists_conflict"
        assert team("handoff", status=404, member="missing", expected_revision=team("get")["revision"])["code"] == "mohists_member_missing"
        selected = select("scholar"); assert selected["speaker_binding"]["role"] == "researcher"
        prompt = "主输入必须完整进入成员账本🙂" * 1300
        model.server.reply = "实际主讲回复🙂" * 1600
        result = wait(run(prompt)["id"])
        assert result["state"] == "succeeded" and result["agent_id"] == "subagent.mohists-researcher", result
        assert result["final_text"] == model.server.reply and not result["final_text_truncated"]
        users = [m["content"] for m in model.server.requests[-1]["messages"] if m["role"] == "user"]
        assert prompt in users and any("SEED-only-member-context" in str(u) for u in users)
        system = "\n".join(str(m["content"]) for m in model.server.requests[-1]["messages"] if m["role"] == "system")
        assert "main speaker" in system and "Preserve continuity" in system
        snapshot = team("get"); direct = next(j for j in snapshot["assignment_items"] if j.get("main_run_id") == result["id"])
        assert snapshot["calls_used"] == 2 and not snapshot["active"] and direct["state"] == "succeeded", snapshot
        assert team("result", id=direct["id"])["native"]["result"]["text_truncated"]
        events, cursor = [], 0
        while True:
            code, _, page = request("GET", f"/api/v1/projects/mohists/sessions/{owner}/events?after={cursor}&limit=1&full_text=1")
            assert code == 200, page
            page = page["data"]; events.extend(page["items"]); cursor = page["next_cursor"]
            if cursor >= page["latest_event_id"]: break
        assert "".join(e["text"] for e in events if e["kind"] == "model_text_delta") == model.server.reply
        assert all(e["source"]["member"] == "scholar" for e in events if e["kind"] == "model_text_delta")
        assert call("session.get", {"path": ctx}, context=ctx)["data"]["agent_id"] == "agent.mohists"
        # Selection is durable, but restarting never invokes the model itself.
        calls = len(model.server.requests); stop(); start()
        assert team("get")["speaker"] == "scholar" and len(model.server.requests) == calls
        model.server.reply = "A second native main turn"
        assert wait(run("FOLLOWUP-main-context")["id"])["state"] == "succeeded"
        # An active main input cannot be silently retargeted.
        model.server.blocked = True; model.server.entered.clear(); model.server.release.clear()
        active = run("CANCEL-main-input"); assert model.server.entered.wait(3)
        assert team("handoff", status=409, member="coordinator", expected_revision=team("get")["revision"])["code"] == "mohists_main_busy"
        call("run.cancel", {"path": {"run": active["id"]}}, context=ctx); model.server.release.set()
        assert wait(active["id"])["state"] == "cancelled"
        model.server.blocked = False
        assert team("get")["calls_used"] == 4
        before = len(model.server.requests)
        code, _, denied = request("POST", "/api/v1/application/call", {"method": "run.start", "params": {"path": ctx, "body": {"prompt": "Over budget"}}, "context": ctx})
        assert code != 200, denied
        after = team("get")
        assert after["calls_used"] == 4 and not after["active"] and len(model.server.requests) == before, after
        assert not any(j["state"] in ("queued", "starting", "running") for j in after["assignment_items"]), after
        denied_job = next(j for j in after["assignment_items"] if j["state"] == "failed")
        work = call("work.get", {"namespace": f"mohists.{owner}.g1", "id": denied_job["id"]}, context=ctx)
        assert work["state"] == "cancelled", work
        assert team("configure", status=400, expected_revision=team("get")["revision"], max_calls=3)["code"] == "mohists_budget_used"
        assert team("configure", status=409, expected_revision=team("get")["revision"], roles=after["roles"])["code"] == "mohists_bindings_frozen"
        raised = team("configure", expected_revision=team("get")["revision"], max_calls=6, concurrency=1)
        assert raised["calls_used"] == 4 and raised["max_calls"] == 6
        assert wait(run("Continue after the user's budget adjustment")["id"])["state"] == "succeeded"
        assert team("get")["calls_used"] == 5
        assert select("coordinator")["last_speaker"] == "scholar"
        model.server.reply = "Coordinator uses a real history reference"
        assert wait(run("Please continue as coordinator")["id"])["agent_id"] == "agent.mohists"
        text = "\n".join(str(m.get("content", "")) for m in model.server.requests[-1]["messages"])
        assert "Main speaker returned from member scholar" in text and "action=history" in text
        history_tool = call("tool.call", {"tool": "mohists_team", "arguments": {"action": "history", "member": "scholar", "limit": 1}}, context=ctx)
        assert history_tool["success"] and '"items"' in history_tool["text"], history_tool
        assert team("finish", expected_revision=team("get")["revision"])["speaker"] == "coordinator"
    print("PASS real main-speaker handoff, long text, author provenance, restart, cancellation, budget and coordinator history reference")


if __name__ == "__main__": main()
