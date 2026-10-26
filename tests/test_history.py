"""Real public history: complete visible output, scopes and bounded pages."""
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
        def team(action, **params): return call("mohists.team", {"action": action, **params}, context=ctx)
        team("start", id="history", goal="Read the actual visible conversation")
        team("assign", id="long", member="reader", role="researcher", title="Long result", prompt="marker-history-input")
        params = {"namespace": f"mohists.{owner}.g1", "id": "reader"}
        initial = call("instance.history", params, context=ctx)
        assert initial["available"] and initial["complete_from_creation"] and initial["items"] == [], initial
        model.server.reply = "墨者完整正文🙂ABC\n" * 3000
        model.server.reasoning = "hidden-reasoning-should-never-appear-in-visible-history"
        assert team("execute", id="long")["state"] == "succeeded"
        assert team("result", id="long")["native"]["result"]["text_truncated"]
        cursor = 0
        records = []
        pages = 0
        while True:
            page = call("instance.history", {**params, "after": cursor, "limit": 2}, context=ctx)
            assert len(page["items"]) <= 2 and page["next_cursor"] >= cursor
            records.extend(page["items"])
            cursor = page["next_cursor"]
            pages += 1
            if not page["has_more"]: break
            assert pages < 100
        text = "".join(e["text"] for e in records if e["kind"] == "model_text_delta")
        assert text == model.server.reply, (len(text), len(model.server.reply))
        assert any("marker-history-input" in e["text"] for e in records if e["kind"] == "agent_start")
        assert not any("hidden-reasoning" in e.get("text", "") for e in records)
        assert pages > 2
        for e in records:
            assert len(e["text"].encode()) <= 8192
            assert e["message_id"] == "task.long"
            assert e["source"] == "user"
        assert call("instance.history", {**params, "after": cursor}, context=ctx)["items"] == []
        wrong = call("session.create", {"body": {"project_id": "default"}})["data"]["id"]
        denied = call("instance.history", params, context={"project": "default", "session": wrong}, status=403)
        assert denied["code"] == "sdk_instance_history_scope"
        assert call("instance.history", {**params, "after": 1}, context=ctx, status=409)["code"] == "sdk_instance_history_cursor"
        assert call("instance.history", {**params, "limit": 65}, context=ctx, status=400)["code"] == "sdk_arguments_invalid"
        assert len(model.server.requests) == 1, "History must never invoke or recover a model"
        # Exercise native tool-start/output events, rather than reconstructing
        # a fake transcript from the short final-result receipt.
        model.server.reply = "tool-history-finished"
        model.server.tool_call = True
        team("assign", id="tools", member="tool-reader", role="researcher", title="Tool history", prompt="Use the team mailbox")
        assert team("execute", id="tools")["state"] == "succeeded"
        tool_page = team("history", member="tool-reader", limit=64)
        assert any(e["kind"] == "tool_start" and e.get("tool_name") == "mohists_mail" and "visible-tool-body" in e["text"] for e in tool_page["items"])
        assert any(e["kind"] == "tool_done" and e.get("tool_name") == "mohists_mail" and "accepted" in e["text"] for e in tool_page["items"])
        assert team("inbox")["items"][0]["body"]["source"] == "agent"
        # Fault injection is confined to this test Home. Production Mohists
        # reads only the SDK and never knows the private storage layout.
        import hashlib
        from dev import RUNTIME
        state_path = "data/application/state/" + hashlib.sha256(f"default\nmohists.{owner}.g1".encode()).hexdigest() + ".json"
        identity = hashlib.sha256((state_path + "\nreader").encode()).hexdigest()
        journal = RUNTIME / "home/data/application/instances" / identity / "visible.jsonl"
        committed = journal.read_bytes()
        with journal.open("ab") as sink: sink.write(b'{"torn":')
        partial = call("instance.history", {**params, "after": cursor}, context=ctx)
        assert partial["pending_tail"] and partial["items"] == [] and partial["next_cursor"] == cursor
        model.server.tool_call = False
        model.server.reply = "after-torn-tail"
        team("assign", id="after-tail", member="reader", role="researcher", title="Continue", prompt="Continue after an uncommitted display tail")
        assert team("execute", id="after-tail")["state"] == "succeeded"
        assert journal.read_bytes().startswith(committed) and b'{"torn":' not in journal.read_bytes()
        while True:
            page = call("instance.history", {**params, "after": cursor, "limit": 32}, context=ctx)
            records.extend(page["items"])
            cursor = page["next_cursor"]
            if not page["has_more"]: break
        assert any(e["message_id"] == "task.after-tail" and e["text"] == "after-torn-tail" for e in records)
        from dev import RUNTIME, write_json
        write_json(RUNTIME / "last-history-test.json", {"context": ctx, "params": params, "cursor": cursor, "records": records})
        assert len(model.server.requests) == 4
    print("PASS public native visible history: full long UTF-8 text, bounded pages, source identity, hidden reasoning exclusion and owner scope")


if __name__ == "__main__":
    if "--check-durable" in sys.argv:
        from dev import RUNTIME, read_json
        saved = read_json(RUNTIME / "last-history-test.json")
        cursor = 0
        records = []
        while True:
            page = call("instance.history", {**saved["params"], "after": cursor, "limit": 32}, context=saved["context"])
            records.extend(page["items"])
            cursor = page["next_cursor"]
            if not page["has_more"]: break
        assert cursor == saved["cursor"] and records == saved["records"]
        print("PASS committed visible member history and cursor survive project host restart")
    else: main()
