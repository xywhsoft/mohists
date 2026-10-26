"""Scale namespaces without rewriting legacy state or changing member identity."""
import hashlib
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from dev import RUNTIME, call, write_json, stop, start
from model_fixture import LocalModel

BASE = RUNTIME / "home/data/application/state"
CTX = {"project": "mohists"}
LIMIT = 16 * 1024 * 1024


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths(namespace):
    identity = hashlib.sha256((CTX["project"] + "\n" + namespace).encode()).hexdigest()
    return BASE / (identity + ".json"), BASE / identity[:2] / (identity + ".json")


def main():
    # Create one owned legacy-layout fixture in this same Home. Moving only its
    # state document must not change the native member's logical directory.
    with LocalModel() as model:
        model.configure(call)
        session = call("session.create", {"body": {"project_id": "mohists", "model_id": "mohists-local"}})["data"]["id"]
        owner = {"project": "mohists", "session": session}
        native = {"namespace": "legacy.scale." + session, "id": "writer"}
        call("instance.create", {**native, "agent_id": "mdo.default", "model_id": "mohists-local"}, context=owner)
        call("instance.send", {**native, "message_id": "seed", "prompt": "Retain this legacy member history"}, context=owner)
        call("instance.step", native, context=owner)
        assert len(model.server.requests) == 1
    before_member = call("instance.get", native, context=owner)
    before_history = call("instance.history", {**native, "limit": 64}, context=owner)
    assert len(before_history["items"]) >= 2
    flat, shard = paths(native["namespace"])
    assert not flat.exists() and shard.is_file()
    signature = checksum(shard)
    stop()
    try:
        assert flat.resolve().is_relative_to(BASE.resolve()) and shard.resolve().is_relative_to(BASE.resolve())
        assert not flat.exists() and checksum(shard) == signature
        shard.rename(flat)
    finally: start()
    original = {p: checksum(p) for p in BASE.glob("*.json")}
    assert call("instance.get", native, context=owner) == before_member
    assert call("instance.history", {**native, "limit": 64}, context=owner) == before_history
    owned = {}
    prefix = "scale." + uuid.uuid4().hex
    def seed(namespace, value=1):
        flat, shard = paths(namespace)
        assert not flat.exists() and not shard.exists()
        result = call("state.put", {"namespace": namespace, "key": "value", "expected_revision": 0, "value": value}, context=CTX)
        assert shard.is_file() and not flat.exists(), "New namespaces must not fill the legacy flat directory"
        owned[shard] = checksum(shard)
        return result
    try:
        names = [prefix + "." + str(i) for i in range(257)]
        for index, name in enumerate(names): seed(name, index)
        for index in (0, 128, 256):
            assert call("state.get", {"namespace": names[index], "key": "value"}, context=CTX)["value"] == index
        # Fill one bounded shard using real namespaces, not a changed limit.
        bucket = min((f"{i:02x}" for i in range(256)), key=lambda key: len(list((BASE / key).glob("*.json"))))
        target = 256 - len(list((BASE / bucket).glob("*.json")))
        generated = []
        counter = 0
        while len(generated) <= target:
            candidate = prefix + ".quota." + str(counter); counter += 1
            if paths(candidate)[1].parent.name == bucket: generated.append(candidate)
        for name in generated[:-1]: seed(name)
        denied = call("state.put", {"namespace": generated[-1], "key": "value", "expected_revision": 0, "value": 1}, context=CTX, status=413)
        assert denied["code"] == "sdk_state_limit" and not paths(generated[-1])[1].exists()
        existing = generated[0]
        call("state.put", {"namespace": existing, "key": "value", "expected_revision": 1, "value": 2}, context=CTX)
        owned[paths(existing)[1]] = checksum(paths(existing)[1])
        # Account actual disk bytes even when another document is opaque. This
        # temporary test-owned sparse file is removed after stopping this host.
        byte_bucket = next(f"{i:02x}" for i in range(256) if f"{i:02x}" != bucket and len(list((BASE / f"{i:02x}").glob("*.json"))) < 250)
        counter = 0
        while True:
            byte_name = prefix + ".bytes." + str(counter); counter += 1
            if paths(byte_name)[1].parent.name == byte_bucket: break
        directory = BASE / byte_bucket; directory.mkdir(exist_ok=True)
        filler = directory / (byte_bucket + "0" * 62 + ".json")
        assert not filler.exists()
        available = LIMIT - sum(p.stat().st_size for p in directory.iterdir())
        assert available > 0
        with filler.open("xb") as handle: handle.truncate(available)
        owned[filler] = checksum(filler)
        denied = call("state.put", {"namespace": byte_name, "key": "value", "expected_revision": 0, "value": 1}, context=CTX, status=413)
        assert denied["code"] == "sdk_state_limit" and not paths(byte_name)[1].exists()
        # Ambiguous copies are an explicit error, never a silent preference.
        flat, shard = paths(names[0]); flat.write_bytes(shard.read_bytes()); owned[flat] = checksum(flat)
        assert call("state.get", {"namespace": names[0], "key": "value"}, context=CTX, status=409)["code"] == "sdk_state_ambiguous"
        assert checksum(flat) == owned[flat] and checksum(shard) == owned[shard]
        # No legacy member rebasing or state migration occurred.
        assert all(checksum(path) == digest for path, digest in original.items())
        stop(); start()
        assert call("state.get", {"namespace": names[128], "key": "value"}, context=CTX)["value"] == 128
        assert call("instance.get", native, context=owner) == before_member
        assert call("instance.history", {**native, "limit": 64}, context=owner) == before_history
        assert all(checksum(path) == digest for path, digest in original.items())
        write_json(RUNTIME / "acceptance/state-scale.json", {"passed": True, "legacy_files_unchanged": len(original),
            "new_namespaces": len(names), "shard_file_limit": 256, "shard_bytes_limit": LIMIT,
            "legacy_member_history_unchanged": True, "duplicate_storage_rejected": True, "model_calls": 1})
    finally:
        # Only exact, hash-verified files created by this test are removed.
        # No recursive delete, other namespace or original record is touched.
        stop()
        try:
            for path, digest in owned.items():
                assert path.resolve().is_relative_to(BASE.resolve()) and checksum(path) == digest, "Preserve unexpected concurrent changes"
            for path in owned: path.unlink()
        finally: start()
    print("PASS more than 256 namespaces, bounded shard count/bytes, explicit duplicate rejection, unchanged legacy records/member history and durable restart; one local model call")


if __name__ == "__main__":
    main()
