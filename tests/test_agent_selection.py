"""Switch a populated main conversation using the existing project Home and a loopback model."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call, request, write_json, RUNTIME
from model_fixture import LocalModel


def main():
    with LocalModel() as model:
        model.configure(call)
        session = call("session.create", {"body": {"project_id": "default", "model_id": "mohists-local",
            "permission_profile": "read-only"}})["data"]
        ctx = {"project": "default", "session": session["id"]}
        path = f"/api/v1/projects/default/sessions/{session['id']}"
        def run(prompt):
            result = call("run.start", {"path": ctx, "body": {"prompt": prompt}}, context=ctx)["data"]
            for _ in range(200):
                state = call("run.get", {"path": {"run": result["id"]}}, context=ctx)["data"]
                if state["terminal"]:
                    assert state["state"] == "succeeded", state
                    return state
                time.sleep(.03)
            raise AssertionError("The loopback model did not finish")
        def switch(agent, expected=200):
            _, headers, current = request("GET", path)
            import http.client, json
            from dev import environment
            _, bootstrap_headers, _ = request("GET", "/api/v1/bootstrap")
            connection = http.client.HTTPConnection("127.0.0.1", environment()["port"], timeout=30)
            body = {key: current["data"][key] for key in ("model_id", "reasoning_effort", "permission_profile")}
            body["agent_id"] = agent
            connection.request("PUT", path + "/profile", json.dumps(body), {"Content-Type": "application/json",
                "If-Match": headers["etag"], "X-Mdo-Write-Token": bootstrap_headers["x-mdo-write-token"]})
            response = connection.getresponse(); result = json.loads(response.read()); code = response.status; connection.close()
            assert code == expected, (code, result)
            return result.get("data")
        run("agent-switch-before: preserve this marker")
        prefix = request("GET", path + "/events?limit=32")[2]["data"]["items"]
        requests_before = len(model.server.requests)
        switched = switch("agent.mohists")
        assert switched["agent_id"] == "agent.mohists" and switched["permission_profile"] == "read-only"
        assert switched["model_id"] == "mohists-local" and len(model.server.requests) == requests_before
        assert request("GET", path + "/events?limit=32")[2]["data"]["items"] == prefix
        run("agent-switch-after: answer directly without delegating")
        messages = model.server.requests[-1]["messages"]
        assert any("agent-switch-before" in str(message) for message in messages), "Previous conversation was lost"
        assert any("墨者" in str(message) for message in messages), "Coordinator role was not applied"
        assert not request("GET", path)[2]["data"]["runtime_open"], "Wait for the original runtime to release before testing an invalid main role"
        switch("subagent.mohists-worker", expected=409)
        assert request("GET", path)[2]["data"]["agent_id"] == "agent.mohists"
        switch("mdo.default")
        run("agent-switch-back: ordinary Agent")
        assert request("GET", path + "/events?limit=32")[2]["data"]["items"][:len(prefix)] == prefix
        model.server.blocked = True; model.server.entered.clear(); model.server.release.clear()
        running = call("run.start", {"path": ctx, "body": {"prompt": "busy-switch"}}, context=ctx)["data"]
        assert model.server.entered.wait(3)
        try: switch("agent.mohists", expected=409)
        finally: model.server.release.set()
        for _ in range(200):
            if call("run.get", {"path": {"run": running["id"]}}, context=ctx)["data"]["terminal"]: break
            time.sleep(.03)
        assert request("GET", path)[2]["data"]["agent_id"] == "mdo.default"
        result = {"history_preserved": True, "profile_preserved": True, "switch_does_not_run_model": True,
            "simple_task_runs": True, "busy_and_subagent_refused": True, "loopback_requests": len(model.server.requests), "vendor_calls": 0}
        write_json(RUNTIME / "acceptance/agent-selection.json", result)
        print(result)


if __name__ == "__main__": main()
