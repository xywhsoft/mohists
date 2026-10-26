"""Use the source-packed Windows host with the sole existing development Home.

The temporary directory contains only explicitly selected application sources,
never another Home, SDK runtime or user data. It is removed after packaging.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import ROOT, RUNTIME, call, environment, request, start, stop, write_json
from model_fixture import LocalModel
from test_coordinator_flow import main as coordinator_flow


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    env = environment()
    assert os.name == "nt", "This acceptance case targets the current Windows pack host"
    host = Path(env["host"])
    assert digest(host) == env["host_sha256"], "Shared host changed; inspect before acceptance"
    code, _, runs = request("GET", "/api/v1/runs")
    assert code == 200 and not any(r["state"] in ("queued", "running", "cancelling") for r in runs["data"]["items"])
    installed = call("plugin.list")["items"]
    preferences = call("mohists.settings", {"action": "get"})
    stage = RUNTIME / "package-source"
    assert not stage.exists(), "Preserve an existing package directory for inspection"
    stage.mkdir()
    inventory = {}
    source = Path(env["mdo"]) / "app"
    try:
        for tree in ("src", "include", "generated", "default-home", "web"):
            for path in sorted((source / tree).rglob("*")):
                assert not path.is_symlink() and not getattr(path, "is_junction", lambda: False)()
                if not path.is_file(): continue
                name = path.relative_to(source).as_posix()
                data = path.read_bytes()
                assert len(inventory) < 4096 and len(data) < 8 * 1024 * 1024
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                inventory[name] = hashlib.sha256(data).hexdigest()
        for name in ("command-worker.c", "release.json"):
            target = stage / name
            target.write_bytes((source / name).read_bytes())
            inventory[name] = digest(target)
        # Use our owned loopback listener, not a concurrent edit to app/xs.json.
        write_json(stage / "xs.json", json.loads((RUNTIME / "xs.json").read_text(encoding="utf-8")))
        inventory["xs.json"] = digest(stage / "xs.json")
        assert sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) < 32 * 1024 * 1024
        assert not any(name.startswith(("home/", "data/", "sessions/")) for name in inventory)
        output = ROOT / "dist/mdo-mohists-acceptance.exe"
        output.parent.mkdir(exist_ok=True)
        subprocess.run([str(host), "pack", str(stage), "-o", str(output)], cwd=ROOT, check=True, capture_output=True)
        candidate_hash = digest(output)
        assert all(digest(stage / name) == checksum for name, checksum in inventory.items())
        assert all(digest(source / name) == checksum for name, checksum in inventory.items() if name != "xs.json")
    finally:
        assert stage.resolve().parent == RUNTIME.resolve() and stage.name == "package-source"
        actual = {p.relative_to(stage).as_posix(): digest(p) for p in stage.rglob("*") if p.is_file()}
        assert actual == inventory, "Keep changed staging files rather than deleting unexpected data"
        shutil.rmtree(stage)

    process = None
    stop()
    try:
        def launch():
            # dist has no external xs.json, app sources or user Home. Actual
            # application code and browser assets must come from the archive.
            assert not (output.parent / "xs.json").exists()
            with (RUNTIME / "packaged-host.log").open("ab") as log:
                child = subprocess.Popen([str(output), "--", "--home", str(RUNTIME / "home")],
                    cwd=output.parent, env={**os.environ, "USE_WEBVIEW": "0"}, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(150):
                    assert child.poll() is None, "Inspect runtime/packaged-host.log; candidate exited"
                    try:
                        if request("GET", "/api/v1/bootstrap", timeout=1)[0] == 200: return child
                    except OSError: pass
                    time.sleep(.1)
                raise AssertionError("Packaged candidate startup deadline")
            except BaseException:
                if child.poll() is None: child.terminate()
                child.wait(timeout=10)
                raise

        process = launch()
        assert call("mohists.status")["plugin"] == "mohists"
        assert call("plugin.list")["items"] == installed
        coordinator_flow()
        with LocalModel() as model:
            model.configure(call)
            owner = call("session.create", {"body": {"project_id": "mohists", "agent_id": "agent.mohists", "model_id": "mohists-local"}})["data"]["id"]
            ctx = {"project": "mohists", "session": owner}
            def team(action, **params): return call("mohists.team", {"action": action, **params}, context=ctx)
            team("start", id="packaged", goal="Preserve native member history across packed/unpacked startup")
            team("assign", id="seed", member="reader", role="researcher", title="Seed", prompt="Remember packed host marker")
            assert team("execute", id="seed")["state"] == "succeeded"
            saved = team("get")
            history = team("history", member="reader", limit=64)
            process.terminate(); process.wait(timeout=10); process = launch()
            assert team("get") == saved and team("history", member="reader", limit=64) == history
            assert len(model.server.requests) == 1, "Restart must never replay the native member"
        # The coordinator test deliberately saves and restores defaults using
        # CAS. Values must match; that real save legitimately advances revision.
        assert call("mohists.settings", {"action": "get"})["value"] == preferences["value"]
        assert digest(output) == candidate_hash
    finally:
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=10)
        start()
    assert team("get") == saved and team("history", member="reader", limit=64) == history
    assert call("plugin.list")["items"] == installed
    assert call("mohists.settings", {"action": "get"})["value"] == preferences["value"]
    write_json(RUNTIME / "acceptance/packaged-host.json", {"passed": True, "host_sha256": env["host_sha256"],
        "candidate_sha256": candidate_hash, "candidate_bytes": output.stat().st_size,
        "embedded_files": len(inventory), "no_home_in_package": True, "same_home": True,
        "coordinator_model_requests": 17, "restart_model_requests": 1, "real_provider_calls": 0,
        "history_preserved": True, "other_plugins_preserved": True, "preferences_preserved": True,
        "development_host_restored": True, "public_release": False})
    print("PASS packed Windows host: embedded app, actual coordinator tools, durable history, same Home, restored development host; no public release")


if __name__ == "__main__":
    main()
