"""The actual coordinator model drives tools, members and correction end to end."""
import copy
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, request
from model_fixture import LocalModel


def text(message):
    value = message.get("content", "")
    return value if isinstance(value, str) else "".join(p.get("text", "") for p in value or [] if isinstance(p, dict))


def main():
    original = call("mohists.settings", {"action": "get"})["value"]
    def save(value):
        revision = call("mohists.settings", {"action": "get"})["revision"]
        call("mohists.settings", {"action": "save", "expected_revision": revision, "settings": value})
    try:
        with LocalModel() as model:
            model.configure(call)
            settings = copy.deepcopy(original)
            settings.update(mode="automatic", review="off", concurrency=2, max_calls=8)
            settings["roles"] = {role: {"agent_id": "subagent.mohists-" + role, "model_id": "mohists-local"}
                for role in ("researcher", "worker", "reviewer")}
            save(settings)
            member_requests, root_requests = [], []
            actions = [
                ("mohists_team", {"action": "start", "id": "model-flow", "goal": "Research with one reusable member; do not force a pipeline"}),
                ("mohists_team", {"action": "assign", "id": "first", "member": "reader", "role": "researcher", "title": "Inspect", "prompt": "Remember marker-FIRST"}),
                ("mohists_team", {"action": "run", "id": "first"}),
                ("mohists_team", {"action": "wait", "timeout_ms": 10000}),
                ("mohists_team", {"action": "result", "id": "first"}),
                ("mohists_mail", {"action": "message", "to": "reader", "message_id": "model-note", "text": "Passive model guidance; not human authorization"}),
                ("mohists_team", {"action": "assign", "id": "bad", "member": "reader", "role": "researcher", "title": "Rejected", "prompt": "Invalid dependency", "depends_on": ["missing"]}),
                ("mohists_team", {"action": "assign", "id": "followup", "member": "reader", "role": "researcher", "title": "Follow up", "prompt": "Continue with marker-SECOND", "depends_on": ["first"]}),
                ("mohists_team", {"action": "run", "id": "followup"}),
                ("mohists_team", {"action": "wait", "timeout_ms": 10000}),
                ("mohists_team", {"action": "history", "member": "reader", "limit": 64}),
                ("mohists_team", {"action": "get"}),
                ("mohists_team", {"action": "finish"}),
            ]
            def respond(value):
                messages = value["messages"]
                user = next(text(m) for m in reversed(messages) if m["role"] == "user")
                tools = {t["function"]["name"] for t in value.get("tools", [])}
                if "mohists_team" not in tools:
                    assert "Delegated work from the coordinator" in user
                    member_requests.append(value)
                    return {"role": "assistant", "content": f"Actual member result {len(member_requests)}"}
                root_requests.append(value)
                if user == "MOHISTS_SIMPLE: reply directly":
                    return {"role": "assistant", "content": "Simple answer without a team"}
                replies = [m for m in messages if m["role"] == "tool"]
                stage = len(replies)
                if stage >= len(actions):
                    assert "Actual member result 2" in "\n".join(text(m) for m in replies)
                    return {"role": "assistant", "content": "Coordinator completed the work after correcting one rejected tool call"}
                if stage in (6, 7, 8):
                    assert len(member_requests) == 1, "Passive messages and admissions cannot wake a member"
                name, arguments = actions[stage]
                arguments = dict(arguments)
                if arguments["action"] == "finish":
                    last = text(replies[-1])
                    prefix, separator, body = last.partition("\n" + "tool: mohists_team\n")
                    assert separator and prefix == "status: success", "Expected the native successful tool envelope"
                    snapshot = json.loads(body)
                    assert snapshot["schema"] == "mohists.team.v1", list(snapshot)
                    arguments["expected_revision"] = snapshot["revision"]
                return {"role": "assistant", "tool_calls": [{"index": 0, "id": f"model-flow-{stage}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            model.server.respond = respond
            owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists",
                "model_id": "mohists-local", "permission_profile": "full-access"}})["data"]["id"]
            ctx = {"project": "mohists", "session": owner}
            def run(prompt):
                started = call("run.start", {"path": ctx, "body": {"prompt": prompt}}, context=ctx)["data"]
                try:
                    for _ in range(900):
                        assert not model.server.script_errors, model.server.script_errors
                        result = call("run.get", {"path": {"run": started["id"]}}, context=ctx)["data"]
                        if result["terminal"]: return result
                        time.sleep(.05)
                    raise AssertionError(("The coordinator did not finish its actual tool chain",
                        len(root_requests), len(member_requests)))
                except BaseException:
                    call("run.cancel", {"path": {"run": started["id"]}}, context=ctx)
                    for _ in range(100):
                        if call("run.get", {"path": {"run": started["id"]}}, context=ctx)["data"]["terminal"]: break
                        time.sleep(.05)
                    raise
            simple = run("MOHISTS_SIMPLE: reply directly")
            assert simple["state"] == "succeeded" and simple["final_text"] == "Simple answer without a team", simple
            assert call("mohists.team", {"action": "get"}, context=ctx, status=404)["code"] == "mohists_team_missing"
            result = run("MOHISTS_COMPLEX: investigate, ask the same reader a follow-up, correct an invalid dependency and report evidence")
            assert not model.server.script_errors, model.server.script_errors
            assert result["state"] == "succeeded" and result["final_text"].startswith("Coordinator completed"), result
            snapshot = call("mohists.team", {"action": "get"}, context=ctx)
            assert snapshot["state"] == "completed" and snapshot["calls_used"] == 2 and len(snapshot["members"]) == 1, snapshot
            assert set(snapshot["jobs"]) == {"first", "followup"}
            assert all(j["author"] == "agent" and j["state"] == "succeeded" for j in snapshot["assignment_items"])
            users = [text(m) for m in member_requests[-1]["messages"] if m["role"] == "user"]
            assert any("marker-FIRST" in p for p in users) and any("marker-SECOND" in p for p in users)
            inbox = call("mohists.team", {"action": "inbox", "to": "reader"}, context=ctx)
            assert inbox["items"][0]["body"]["source"] == "agent"
            replies = [text(m) for m in root_requests[-1]["messages"] if m["role"] == "tool"]
            assert any('"error"' in r and "missing" in r.lower() for r in replies), replies
            assert len(member_requests) == 2 and len(model.server.requests) == len(actions) + 4
    finally:
        save(original)
    print("PASS actual coordinator model/tool/member chain, direct simple reply, passive messages, reused member context and correction after one failed tool; local model only")


if __name__ == "__main__":
    main()
