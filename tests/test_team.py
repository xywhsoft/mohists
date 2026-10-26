"""Team admission and ownership in the one project instance; no model calls."""
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import call


def session():
    value = call("session.create", {"body": {"project_id": "default"}})
    return {"project": "default", "session": value["data"]["id"]}


def main():
    a, b = session(), session()
    def team(action, status=200, **params):
        return call("mohists.team", {"action": action, **params}, context=a, status=status)
    started = team("start", id="analysis", goal="Research the project without modifying files")
    assert team("start", id="analysis", goal=started["goal"]) == started
    assert team("start", status=409, id="analysis", goal="different")["code"] == "mohists_identity_conflict"
    assert team("start", status=409, id="other", goal="another")["code"] == "mohists_team_open"
    first = team("get")
    assert first["generation"] == 1 and first["tasks"]["items"] == [] and first["members"] == []
    assert call("mohists.team", {"action": "get"}, context=b, status=404)["code"] == "mohists_team_missing"
    assert call("mohists.team", {"action": "get"}, status=400)["code"] == "mohists_session"
    assert team("configure", status=409, expected_revision=0, concurrency=1)["code"] == "mohists_conflict"
    team("configure", expected_revision=first["revision"], concurrency=2, max_calls=8)
    task = {"id": "investigate", "member": "research-a", "role": "researcher", "title": "Investigate",
        "prompt": "Read the source and report findings"}
    accepted = team("assign", **task)
    assert team("assign", **task) == accepted, "Repeated admission must be idempotent"
    assert team("assign", status=409, **{**task, "prompt": "changed"})["code"] == "mohists_identity_conflict"
    assert team("assign", status=409, **{**task, "id": "write", "role": "worker"})["code"] == "mohists_member_role"
    team("assign", id="review", member="review-a", role="reviewer", title="Review", prompt="Verify findings",
        depends_on=["investigate"])
    snapshot = team("get")
    assert len(snapshot["tasks"]["items"]) == 2 and len(snapshot["members"]) == 2
    tasks = {t["id"]: t for t in snapshot["tasks"]["items"]}
    assert tasks["investigate"]["ready"] and not tasks["review"]["ready"]
    assert snapshot["jobs"] == ["investigate", "review"] and snapshot["calls_used"] == 0
    team("assign", status=400, **{**task, "id": "../escape"})
    team("assign", status=404, **{**task, "id": "missing-dependency", "depends_on": ["unknown"]})
    assert len(team("get")["jobs"]) == 2, "Rejected dependencies must not publish a reservation"
    # Keep the durable identity for the explicit restart check in this same Home.
    from dev import RUNTIME, write_json
    write_json(RUNTIME / "last-team-test.json", {"context": a, "snapshot": team("get")})
    print("PASS session isolation, idempotent admission, revision checks, role ownership and task dependencies")


if __name__ == "__main__":
    if "--check-durable" in sys.argv:
        from dev import RUNTIME, read_json
        saved = read_json(RUNTIME / "last-team-test.json")
        actual = call("mohists.team", {"action": "get"}, context=saved["context"])
        assert actual == saved["snapshot"], "Restart must preserve the original team without replay"
        print("PASS team and native task/member state unchanged across project restart")
    else: main()
