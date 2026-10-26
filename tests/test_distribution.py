"""Real plugin author/store lifecycle in the sole development Home; no vendors."""
import base64
import copy
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import ROOT, RUNTIME, call, request, stop, start
from package import build, payload, extension
from model_fixture import LocalModel


def restart():
    stop()
    start()


def plugin():
    return next((item for item in call("plugin.list")["items"] if item["id"] == "mohists"), None)


def enable(value):
    changes = [{"id": "mohists", "enabled": value}]
    plan = call("plugin.plan", {"changes": changes})
    assert plan["allowed"], plan
    return call("plugin.commit", {"changes": changes, "expected_revision": plan["base_revision"],
        "expected_plan": plan["plan_revision"]})


def ecosystem(action, status=200, **body):
    code, _, result = request("POST", "/api/v1/ecosystem", {"action": action, "single_kind": "plugins", **body}, timeout=60)
    assert code == status, (action, code, result)
    return result.get("data") if code == 200 else result["error"]


def receipt():
    code, _, result = request("GET", "/api/v1/ecosystem")
    assert code == 200, result
    records = result["data"]
    return next((v for v in records.values() if v.get("slug") == "mohists" and v.get("source") == "local"), None)


def main():
    original = plugin()
    assert original and original["enabled"] and original.get("source") != "store", "Use the owned Mohists development installation"
    assert receipt() is None, "Do not replace an existing ecosystem installation"
    others = [p for p in call("plugin.list")["items"] if p["id"] != "mohists"]
    source = payload()
    # The explicit serial describes this development host, not a published client.
    build_id = json.loads((RUNTIME / "release.json").read_text())["windows_build_id"]
    output = ROOT / "dist"
    paths = build(output, build_id)
    first = {p.name: p.read_bytes() for p in paths}
    assert first == {p.name: p.read_bytes() for p in build(output, build_id)}
    with zipfile.ZipFile(paths[0]) as archive:
        assert len(archive.namelist()) == len(source["files"]) + 1
        assert json.loads(archive.read("plugin.json")) == source["manifest"]
        assert not any(n.startswith(("runtime/", ".git/", "tests/", "dist/")) or n.endswith(".local.json") for n in archive.namelist())
        for f in source["files"]:
            assert archive.read(f["path"]) == base64.b64decode(f["base64"])
    package = json.loads(paths[1].read_text(encoding="utf-8"))
    assert package == extension(source, build_id)
    for invalid in (0, True, 30000125, 100000000):
        try:
            extension(source, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid ecosystem build accepted")

    restored = False
    try:
        with LocalModel() as model:
            model.configure(call)
            owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists", "model_id": "mohists-local"}})["data"]["id"]
            ctx = {"project": "mohists", "session": owner}
            def team(action, **body):
                return call("mohists.team", {"action": action, **body}, context=ctx)
            team("start", id="distribution", goal="Preserve members and user data through installation lifecycle")
            team("assign", id="seed", member="scholar", role="researcher", title="Keep history", prompt="Distribution history canary")
            assert team("execute", id="seed")["state"] == "succeeded"
            team("message", to="scholar", message_id="keep-mail", text="Keep this passive message")
            state_path = {"namespace": "mohists." + owner, "key": "team"}
            member_path = {"namespace": f"mohists.{owner}.g1", "id": "scholar"}
            saved_state = call("state.get", state_path, context=ctx)
            saved_member = call("instance.get", member_path, context=ctx)
            saved_history = call("instance.history", {**member_path, "limit": 64}, context=ctx)
            saved_team = team("get")
            def data_intact():
                assert call("state.get", state_path, context=ctx) == saved_state
                assert call("instance.get", member_path, context=ctx) == saved_member
                assert call("instance.history", {**member_path, "limit": 64}, context=ctx) == saved_history
                assert len(model.server.requests) == 1, "Lifecycle must never replay a model request"
                assert [p for p in call("plugin.list")["items"] if p["id"] != "mohists"] == others
            def active():
                assert call("mohists.status")["plugin"] == "mohists"
                assert team("get") == saved_team
                data_intact()

            current = plugin()
            call("plugin.apply", {**source, "expected_revision": current["revision"]})
            restart()
            active()
            initial_revision = plugin()["revision"]
            exported = ecosystem("export", references=[{"kind": "plugins", "id": "mohists"}])["resources"][0]
            assert json.loads(exported["content"]) == source["manifest"]
            assert {f["path"]: base64.b64decode(f["base64"]) for f in exported["files"]} == {
                f["path"]: base64.b64decode(f["base64"]) for f in source["files"]}
            # Update and rollback source without rolling back live task data.
            updated = copy.deepcopy(source)
            updated["manifest"]["version"] = "0.1.1"
            updated["manifest"]["description"] = "Local lifecycle regression only"
            call("plugin.apply", {**updated, "expected_revision": initial_revision})
            restart()
            assert plugin()["revision"] != initial_revision
            assert call("plugin.get", {"id": "mohists"})["manifest"]["version"] == "0.1.1"
            active()
            call("plugin.rollback", {"id": "mohists"})
            restart()
            assert plugin()["revision"] == initial_revision
            active()
            enable(False)
            restart()
            assert not plugin()["enabled"]
            assert call("mohists.status", status=404)["code"] == "sdk_method_missing"
            data_intact()
            call("plugin.remove", {"id": "mohists"})
            restart()
            assert plugin() is None
            data_intact()
            # Install the actual portable package via the client's preview,
            # trust and receipt path, without a second host or online account.
            denied = ecosystem("import", status=409, package=package)
            assert denied["code"] == "ecosystem_import_failed" and plugin() is None
            plan = ecosystem("plan_import", package=package)
            assert plugin() is None, "Preview must not install or execute the package"
            ecosystem("import", package=package, trust_code=True, expected_plan=plan["sha256"])
            restart()
            if not plugin()["enabled"]:
                enable(True)
                restart()
            active()
            installed = receipt()
            assert installed and installed["version"] == source["manifest"]["version"]
            # No direct author files or existing receipt are overwritten.
            ecosystem("uninstall", entry=installed)
            restart()
            assert plugin() is None and receipt() is None
            data_intact()
            call("plugin.apply", {**source, "expected_revision": ""})
            enable(True)
            restart()
            active()
            restored = True
    finally:
        if not restored:
            # Keep the development app usable even when an assertion fails.
            local = receipt()
            if local:
                ecosystem("uninstall", entry=local)
                restart()
            current = plugin()
            call("plugin.apply", {**source, "expected_revision": current["revision"] if current else ""})
            enable(True)
            restart()
    print("PASS reproducible source package, native update/rollback/disable/remove/reinstall, creator export, portable import and preserved member history; one local model call")


if __name__ == "__main__":
    main()
