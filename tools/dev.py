"""Run one project deployment with the existing shared mdo native host."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def environment():
    return read_json(RUNTIME / "environment.json")


def request(method, path, body=None, timeout=10):
    env = environment()
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if method not in ("GET", "HEAD", "OPTIONS"):
        _, bootstrap_headers, _ = request("GET", "/api/v1/bootstrap")
        headers["X-Mdo-Write-Token"] = bootstrap_headers.get("x-mdo-write-token", "")
    client = http.client.HTTPConnection("127.0.0.1", env["port"], timeout=timeout)
    try:
        client.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        response = client.getresponse()
        data = response.read()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, json.loads(data)
    finally:
        client.close()


def call(method, params=None, context=None, status=200):
    code, _, value = request("POST", "/api/v1/application/call", {
        "method": method, "params": params or {}, "context": context or {"project": "default"}}, timeout=60)
    if code != status:
        raise AssertionError((method, code, value))
    return value["data"] if code == 200 else value["error"]


def setup(mdo, port):
    if (RUNTIME / "process.json").exists():
        raise RuntimeError("Stop the project instance before changing its environment")
    mdo = mdo.resolve()
    host = mdo / ".build/host" / ("xs.exe" if os.name == "nt" else "linux-server-glibc/xs")
    if not host.is_file() or not (mdo / "app/generated/mdo_unity.c").is_file():
        raise RuntimeError("The referenced mdo runtime and generated application must already exist")
    if not port:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    source = subprocess.check_output(["git", "-C", str(mdo), "rev-parse", "HEAD"], text=True).strip()
    # XS deliberately rejects directory junction traversal. Deploy the small
    # application once in our sole working directory; share its large host/SDK.
    RUNTIME.mkdir(exist_ok=True)
    for name in ("src", "include", "generated", "default-home", "web"):
        link, target = RUNTIME / name, mdo / "app" / name
        if link.exists() and link.resolve() == target.resolve():
            # Remove only a verified source link, never recurse into its target.
            if link.is_symlink(): link.unlink()
            else: os.rmdir(link)
        shutil.copytree(target, link, dirs_exist_ok=True)
    for name in ("release.json", "command-worker.c"):
        shutil.copy2(mdo / "app" / name, RUNTIME / name)
    config = {"engine": {"workers": 1}, "services": [{"enabled": True, "class": "http",
        "name": "mohists-development", "ip": "127.0.0.1", "port": port,
        "recv_limit": 8388608, "body_limit": 8388608,
        "host_default": {"enabled": True, "name": "mdo", "path": "web",
            "devlang": "c", "devfile": "generated/mdo_unity.c"}}]}
    write_json(RUNTIME / "xs.json", config)
    write_json(RUNTIME / "environment.json", {"mdo": str(mdo), "host": str(host), "port": port,
        "source_commit": source, "host_sha256": hashlib.sha256(host.read_bytes()).hexdigest()})
    print(f"mdo source {source}; shared runtime {host}; Home {RUNTIME / 'home'}")


def start():
    env = environment()
    try:
        if request("GET", "/api/v1/bootstrap")[0] == 200:
            raise RuntimeError("The configured port is already serving; use status")
    except (OSError, http.client.HTTPException):
        pass
    with (RUNTIME / "host.log").open("ab") as log:
        child = subprocess.Popen([env["host"], str(RUNTIME / "xs.json"), "--", "--home", str(RUNTIME / "home")],
            cwd=ROOT, env=dict(os.environ, USE_WEBVIEW="0"), stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    write_json(RUNTIME / "process.json", {"pid": child.pid})
    for _ in range(120):
        if child.poll() is not None:
            (RUNTIME / "process.json").unlink(missing_ok=True)
            raise RuntimeError((RUNTIME / "host.log").read_text(encoding="utf-8", errors="replace")[-6000:])
        try:
            if request("GET", "/api/v1/bootstrap", timeout=1)[0] == 200:
                ensure_project()
                print(f"mdo ready: http://127.0.0.1:{env['port']} (PID {child.pid})")
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(.25)
    raise RuntimeError("Host startup timed out; inspect runtime/host.log")


def ensure_project():
    projects = call("project.list")["data"]["items"]
    project = next((p for p in projects if p["id"] == "mohists"), None)
    if project is None:
        call("project.create", {"body": {"id": "mohists", "name": "墨者 · Mohists", "workspace_root": str(ROOT)}})
        project = call("project.get", {"path": {"project": "mohists"}})["data"]
    if Path(project["workspace_root"]).resolve() != ROOT:
        raise RuntimeError("Existing Mohists project points elsewhere; its binding was preserved")


def stop():
    path = RUNTIME / "process.json"
    if not path.exists():
        print("No project host is recorded")
        return
    # Verify the command line before signalling a potentially recycled PID.
    pid = int(read_json(path)["pid"])
    if os.name == "nt":
        script = f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if($p){{$p.CommandLine}}"
        line = subprocess.check_output(["powershell", "-NoProfile", "-Command", script], text=True).strip()
        if line and str(RUNTIME / "xs.json").lower() not in line.lower():
            raise RuntimeError("Recorded PID no longer belongs to this project")
        if line:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=True, capture_output=True)
    else:
        import signal
        proc = Path(f"/proc/{pid}/cmdline")
        if proc.exists():
            if str(RUNTIME / "xs.json").encode() not in proc.read_bytes():
                raise RuntimeError("Recorded PID no longer belongs to this project")
            os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        try: request("GET", "/api/v1/bootstrap", timeout=.2)
        except (OSError, http.client.HTTPException): break
        time.sleep(.1)
    path.unlink(missing_ok=True)
    print("Project mdo stopped")


def install():
    manifest = read_json(ROOT / "plugin.json")
    files = [{"path": path.relative_to(ROOT).as_posix(), "text": path.read_text(encoding="utf-8")}
        for directory in ("runtime-src", "roles", "web")
        for path in sorted((ROOT / directory).rglob("*")) if path.is_file()]
    applied = call("plugin.apply", {"id": manifest["id"], "manifest": manifest, "files": files})
    if any(p["id"] == manifest["id"] and p["enabled"] for p in applied["items"]):
        print(json.dumps({k: applied.get(k) for k in ("pending", "restart_required", "recovery_mode")}))
        return
    plan = call("plugin.plan", {"changes": [{"id": manifest["id"], "enabled": True}]})
    if not plan["allowed"]:
        raise RuntimeError(plan)
    result = call("plugin.commit", {"changes": [{"id": manifest["id"], "enabled": True}],
        "expected_revision": plan["base_revision"], "expected_plan": plan["plan_revision"]})
    print(json.dumps({k: result.get(k) for k in ("pending", "restart_required", "recovery_mode")}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("setup", "start", "stop", "status", "install"))
    p.add_argument("--mdo", type=Path, default=ROOT.parent / "mdo")
    p.add_argument("--port", type=int, default=0)
    args = p.parse_args()
    if args.command == "setup": setup(args.mdo, args.port)
    elif args.command == "start": start()
    elif args.command == "stop": stop()
    elif args.command == "install": install()
    else:
        code, _, data = request("GET", "/api/v1/bootstrap")
        print(f"HTTP {code}; project Home {RUNTIME / 'home'}; {environment()['source_commit']}")


if __name__ == "__main__":
    main()
