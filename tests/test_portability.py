"""Refuse incomplete session backups, including after the plugin is disabled."""
import sys
import time
import base64
import copy
import hashlib
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, request, stop, start
from model_fixture import LocalModel

QA = "mohists-portability-qa"


def changes(values):
    change = [{"id": key, "enabled": value} for key, value in values.items()]
    plan = call("plugin.plan", {"changes": change})
    assert plan["allowed"], plan
    call("plugin.commit", {"changes": change, "expected_revision": plan["base_revision"], "expected_plan": plan["plan_revision"]})


def restart():
    stop()
    start()


def main():
    assert not any(p["id"] == QA for p in call("plugin.list")["items"]), "Keep a pre-existing test plugin"
    source = Path(__file__).with_name("portability-service.c").read_text(encoding="utf-8")
    call("plugin.apply", {"id": QA, "expected_revision": "", "manifest": {
        "format": "mdo.plugin.v1", "id": QA, "name": "Portability acceptance", "version": "0.1.0",
        "description": "Temporary public native API acceptance", "author": "xywhsoft", "license": "MIT",
        "entry": {"native": "probe.c"}, "overrides": []}, "files": [{"path": "probe.c", "text": source}]})
    try:
        changes({QA: True})
        restart()
        with LocalModel() as model:
            model.configure(call)
            def create(agent="mdo.default"):
                owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": agent, "model_id": "mohists-local"}})["data"]["id"]
                return {"project": "mohists", "session": owner}
            def capture(ctx, action="backup", status=200):
                for _ in range(60):
                    code, _, value = request("GET", f"/api/v1/projects/mohists/sessions/{ctx['session']}/{action}", timeout=30)
                    if code == 409 and value.get("error", {}).get("code") in ("session_capture_busy", "session_state_conflict"):
                        time.sleep(.05)
                        continue
                    break
                assert code == status, (action, code, value)
                if code == 409:
                    assert value["error"]["code"] == "session_external_state", value
                return value
            plain, owner, native, gate = create(), create("agent.mohists"), create(), create()
            def stored(ctx, action="capture"):
                for _ in range(60):
                    value = call("mohists.portability.fixture", {"action": action, "session": ctx["session"]}, context={"project": ctx["project"]})
                    if value["message"] == "session data is busy; wait for the current task to finish":
                        time.sleep(.05)
                        continue
                    return value
                raise AssertionError(value)
            run = call("run.start", {"path": plain, "body": {"prompt": "Ordinary session remains portable"}}, context=plain)["data"]
            for _ in range(150):
                result = call("run.get", {"path": {"run": run["id"]}}, context=plain)["data"]
                if result["terminal"]: break
                time.sleep(.04)
            assert result["state"] == "succeeded", result
            ordinary = capture(plain)
            assert ordinary["format"] == "mdo-session-backup" and ordinary["file_count"] >= 2
            decoded = call("mohists.portability.fixture", {"action": "decode", "document": json.dumps(ordinary)}, context={"project": "mohists"})
            assert decoded["captured"], decoded
            incoming = copy.deepcopy(ordinary)
            marker = b'{"format":"mdo.session.external-state.v1"}\n'
            incoming["files"].append({"path": "external-state.json", "bytes": len(marker), "encoding": "base64",
                "sha256": hashlib.sha256(marker).hexdigest(), "data": base64.b64encode(marker).decode()})
            incoming["files"].sort(key=lambda f: f["path"])
            incoming["file_count"] += 1
            incoming["total_bytes"] += len(marker)
            decoded = call("mohists.portability.fixture", {"action": "decode", "document": json.dumps(incoming)}, context={"project": "mohists"})
            assert not decoded["captured"], "A declaration cannot stand in for the missing member contexts in an imported backup"
            # The marker must fail while capture owns the data gate, without
            # changing an otherwise portable conversation.
            probe = stored(gate, "gate")
            assert probe["captured"] and probe["mark_blocked"], probe
            def team(action, **body):
                return call("mohists.team", {"action": action, **body}, context=owner)
            team("start", id="portability", goal="Preserve all member data, including outside the root session directory")
            capture(owner, status=409)  # Even before the first member exists.
            team("assign", id="seed", member="scholar", role="researcher", title="Member history", prompt="Keep independent member context")
            assert team("execute", id="seed")["state"] == "succeeded"
            saved = team("get")
            history = team("history", member="scholar", limit=64)
            call("instance.create", {"namespace": "native.portability." + native["session"], "id": "standalone", "agent_id": "mdo.default", "model_id": "mohists-local"}, context=native)
            for ctx in (owner, native):
                capture(ctx, status=409)
                capture(ctx, action="export", status=409)
                probe = stored(ctx)
                assert not probe["captured"] and "outside its session directory" in probe["message"], probe
            # Declaring twice does not mutate native team/member revisions.
            assert call("session.mark_external_state", context=owner) == {"marked": True, "portable": False}
            assert team("get") == saved and team("history", member="scholar", limit=64) == history
            assert call("session.mark_external_state", status=400)["code"] == "sdk_session_external_state"
            changes({"mohists": False})
            restart()
            assert call("mohists.status", status=404)["code"] == "sdk_method_missing"
            for ctx in (owner, native):
                capture(ctx, status=409)
                probe = stored(ctx)
                assert not probe["captured"] and "outside its session directory" in probe["message"], probe
            assert capture(plain)["file_count"] == ordinary["file_count"], "Unrelated ordinary session backup must remain available"
            changes({"mohists": True, QA: False})
            call("plugin.remove", {"id": QA})
            restart()
            assert team("get") == saved and team("history", member="scholar", limit=64) == history
            assert len(model.server.requests) == 2
    finally:
        if any(p["id"] == QA for p in call("plugin.list")["items"]):
            changes({"mohists": True, QA: False})
            call("plugin.remove", {"id": QA})
            restart()
    print("PASS ordinary full backup, capture/mark exclusion, explicit incomplete-backup rejection, stored transfer capture guard and persistence across plugin disable; two local model calls")


if __name__ == "__main__":
    main()
