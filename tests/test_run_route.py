"""Real interactive Run -> existing native member -> main visible transcript."""
import sys
import time
import base64
import http.client
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, request, stop, start, RUNTIME, environment
from model_fixture import LocalModel


def main():
    module = RUNTIME / "home/modules/tools/mohists-route.c"
    role = RUNTIME / "home/agents/mohists-route.md"
    assert not module.exists() and not role.exists()
    try:
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(Path(__file__).with_name("route-hook.c").read_text(encoding="utf-8"), encoding="utf-8")
        role.write_text("---\nschema: mdo.agent.v1\nname: Route acceptance\nextends: mdo.general\n---\nReply briefly.\n", encoding="utf-8")
        stop(); start()
        with LocalModel() as model:
            model.configure(call)
            cfg = call("product.models.config.get"); patch = {k:v for k,v in cfg["data"].items() if k != "runtime_override"}
            next(m for m in patch["items"] if m["id"] == "mohists-local")["attachments"] = ["image"]
            call("product.settings.by_domain.put", {"path": {"domain": "models"}, "revision": cfg["revision"], "body": {"schema_version": 1, "patch": patch}})
            owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists-route",
                "model_id": "mohists-local", "permission_profile": "full-access"}})["data"]["id"]
            ctx = {"project": "mohists", "session": owner}
            native = {"namespace": "route." + owner, "id": "speaker"}
            call("instance.create", {**native, "agent_id": "subagent.mohists-worker", "model_id": "mohists-local"}, context=ctx)
            call("instance.send", {**native, "message_id": "seed", "prompt": "Remember SEED-member-context"}, context=ctx)
            call("instance.step", native, context=ctx)
            def run(prompt, **fields):
                return call("run.start", {"path": {"project": "mohists", "session": owner}, "body": {"prompt": prompt, **fields}}, context=ctx)["data"]
            def wait(id):
                for _ in range(150):
                    result = call("run.get", {"path": {"run": id}}, context=ctx)["data"]
                    if result["terminal"]: return result
                    time.sleep(.05)
                raise AssertionError(result)
            model.server.reply = "完整主讲回复🙂" * 1800
            prompt = "FIRST-main-input\n" + "长输入必须完整保留。" * 1600
            active = run(prompt)
            result = wait(active["id"])
            assert result["state"] == "succeeded" and result["agent_id"] == "subagent.mohists-worker", result
            assert result["final_text"] == model.server.reply and not result["final_text_truncated"], result.keys()
            assert call("session.get", {"path": {"project": "mohists", "session": owner}}, context=ctx)["data"]["agent_id"] == "agent.mohists-route"
            users = [m.get("content") for m in model.server.requests[-1]["messages"] if m["role"] == "user"]
            assert "Remember SEED-member-context" in users and prompt in users
            cursor, records = 0, []
            while True:
                code, _, page = request("GET", f"/api/v1/projects/mohists/sessions/{owner}/events?after={cursor}&limit=1&full_text=1")
                assert code == 200, page
                page = page["data"]; records.extend(page["items"])
                cursor = page["next_cursor"]
                if cursor >= page["latest_event_id"]: break
            replies = [e for e in records if e["kind"] == "model_text_delta"]
            assert "".join(e["text"] for e in replies) == model.server.reply
            assert replies and all(e["source"] == {"namespace": native["namespace"], "member": "speaker", "agent": "subagent.mohists-worker"} for e in replies)
            assert next(e["text"] for e in records if e["kind"] == "agent_start") == prompt
            outcome = call("instance.result", {**native, "message_id": active["id"]}, context=ctx)
            assert outcome["result"]["text_truncated"], "Main reply must not be copied from the short member receipt"
            _, headers, _ = request("GET", "/api/v1/bootstrap")
            upload = http.client.HTTPConnection("127.0.0.1", environment()["port"], timeout=10)
            try:
                upload.request("POST", f"/api/v1/projects/mohists/sessions/{owner}/attachments",
                    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jF1sAAAAASUVORK5CYII="),
                    {"Content-Type": "image/png", "X-Mdo-File-Name": "pixel.png", "X-Mdo-Write-Token": headers["x-mdo-write-token"]})
                response = upload.getresponse(); import json
                image = json.loads(response.read()); assert response.status == 201, image
            finally: upload.close()
            model.server.reply = "image-and-tool-result"; model.server.tool_call = True
            model.server.tool_override = ("read", {"path": "README.md"})
            assert wait(run("IMAGE-native-input", attachments=[image["data"]["id"]])["id"])["state"] == "succeeded"
            assert any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"])
                for m in model.server.requests[-1]["messages"] if m["role"] == "user")
            code, _, tools = request("GET", f"/api/v1/projects/mohists/sessions/{owner}/events?after={cursor}&limit=32")
            assert code == 200 and any(e["kind"] == "tool_done" and e["tool_name"] == "read" and e["source"]["member"] == "speaker" for e in tools["data"]["items"]), tools
            model.server.tool_call = False
            model.server.blocked = True; model.server.entered.clear(); model.server.release.clear()
            active = run("SECOND-cancelled-input")
            assert model.server.entered.wait(3)
            call("instance.cancel", native, context=ctx); model.server.release.set()
            assert wait(active["id"])["state"] == "cancelled"
            member = call("instance.get", native, context=ctx)
            if member["state"] == "requires_review":
                call("instance.abandon", {**native, "expected_revision": member["revision"], "message_id": member["active_message"]}, context=ctx)
            model.server.entered.clear(); model.server.release.clear()
            interrupted = run("CRASH-main-input")
            assert model.server.entered.wait(3)
            stop(); model.server.release.set(); model.server.blocked = False; start()
            member = call("instance.get", native, context=ctx)
            assert member["state"] == "requires_review", member
            view = call("instance.recovery", native, context=ctx)
            assert view["resume_required"], view
            model.server.reply = "resume-main-route-result"
            resumed = call("instance.resume", {**native, "expected_revision": member["revision"], "message_id": member["active_message"],
                "expected_recovery_token": view["recovery_token"]}, context=ctx)
            assert resumed["last_outcome"]["outcome"] == "succeeded" and resumed["managed_run_id"], resumed
            managed = call("run.get", {"path": {"run": resumed["managed_run_id"]}}, context=ctx)["data"]
            assert managed["terminal"] and managed["resume"] and managed["agent_id"] == "subagent.mohists-worker", managed
            code, _, resumed_events = request("GET", f"/api/v1/projects/mohists/sessions/{owner}/events?after={cursor}&limit=32")
            assert code == 200 and any(e["kind"] == "model_text_delta" and e["text"] == "resume-main-route-result" and e["source"]["member"] == "speaker"
                for e in resumed_events["data"]["items"]), resumed_events
            model.server.blocked = False; model.server.reply = "coordinator-return"
            call("state.put", {"namespace": native["namespace"], "key": "off", "value": True, "expected_revision": 0}, context=ctx)
            direct = wait(run("THIRD-coordinator-input")["id"])
            assert direct["state"] == "succeeded" and direct["agent_id"] == "agent.mohists-route", direct
            assert len(model.server.requests) == 8, "Only actual native requests, including a tool continuation and an explicit recovery"
    finally:
        module.unlink(missing_ok=True); role.unlink(missing_ok=True)
        stop(); start()
    print("PASS native interactive member routing, long full input/output, true source, unchanged coordinator and shared cancellation")


if __name__ == "__main__": main()
