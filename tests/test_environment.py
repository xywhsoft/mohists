"""Exercise the actual installed plugin in the project's sole mdo Home."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, environment, request

assert request("GET", "/api/v1/bootstrap")[0] == 200
value = call("mohists.status")
assert value == {"plugin": "mohists", "schema": "mohists.team.v1"}, value
plugins = call("plugin.list")["items"]
plugin = next(p for p in plugins if p["id"] == "mohists")
assert plugin["enabled"], plugin
print("PASS actual XS/TCC plugin activation and project-local mdo environment", environment()["port"])
