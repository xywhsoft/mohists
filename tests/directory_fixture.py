"""Small QA extensions use the same directory APIs as product extensions."""
from dev import call, request, stop, start

_owned = set()

def create(kind, alias, entry, files):
    prefix = {"agents": "agent", "tools": "tool", "commands": "command", "plugins":"plugin"}[kind]
    assert not any(x.get("directory_id") == alias for x in call("extension.list", {"kind":kind})), "Keep an existing extension"
    result = call("extension.save", {"kind":kind,"id":alias,"expected_revision":"","trust_code":True,
        "manifest":{"kind":kind,"id":prefix+":"+alias,"name":alias,"alias":alias,"entry":entry,"platforms":["any"]},
        "edits":[{"path":path,"text":text} for path,text in files.items()]})
    _owned.add((kind,alias))
    code, _, plan = request("POST","/api/v1/ecosystem",dict(action="dependency_plan",operation="enable",ref=prefix+":"+alias,cascade=True))
    assert code == 200 and plan["data"]["ready"], plan
    code, _, applied = request("POST","/api/v1/ecosystem",dict(action="apply_plan",plan_id=plan["data"]["id"],revision=plan["data"]["revision"],trust_code=True))
    if code != 200 or kind != "plugins" and applied.get("data",{}).get("runtime_ready") is False:
        _, _, diagnostics = request("GET","/api/v1/diagnostics")
        raise AssertionError((applied,diagnostics.get("data",{})))
    return result

def remove(kind, alias):
    if (kind,alias) in _owned and any(x.get("directory_id") == alias for x in call("extension.list", {"kind":kind})):
        if kind == "plugins":
            call("plugin.disable", {"id":"plugin:"+alias})
            stop(); start()
        return call("extension.remove", {"kind":kind,"id":alias,
            "expected_revision":call("extension.fingerprint", {"kind":kind,"id":alias})["sha256"]})
