"""Build only Mohists source assets, never its development Home or credentials."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ("runtime-src", "roles", "web")
DOCUMENTS = ("README.md", "LICENSE", "mdo-runtime.json", "docs/user-guide.md", "docs/implementation.md")
PLATFORMS = ["windows-x86_64", "linux-x86_64", "android-arm64-v8a"]


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def source_files(root=ROOT):
    root = Path(root).resolve()
    paths = [root / name for name in DOCUMENTS]

    def check(path):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Package source must be an ordinary in-repository path: {path}")

    def walk(directory):
        check(directory)
        for path in sorted(directory.iterdir()):
            check(path)
            if path.is_dir():
                walk(path)
            elif path.is_file():
                paths.append(path)
            else:
                raise ValueError(f"Unsupported package source: {path}")

    for name in TREES:
        walk(root / name)
    result = {}
    total = 0
    for path in sorted(paths):
        for parent in (path, *path.parents):
            if parent == root:
                break
            check(parent)
        data = path.read_bytes()
        total += len(data)
        if len(result) >= 128 or total > 64 * 1024 * 1024:
            raise ValueError("Plugin exceeds mdo's 128-file / 64 MiB limit")
        result[path.relative_to(root).as_posix()] = data
    return result


def payload(root=ROOT):
    manifest_path = Path(root) / "plugin.json"
    if manifest_path.is_symlink() or getattr(manifest_path, "is_junction", lambda: False)():
        raise ValueError("plugin.json must be an ordinary source file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = source_files(root)
    # All native entry and overlay references must travel with the package.
    references = list(manifest["entry"].values()) + [x["source"] for x in manifest["overrides"]]
    if any(name not in files for name in references):
        raise ValueError("Plugin manifest refers to an unpackaged entry or overlay")
    return {"id": manifest["id"], "manifest": manifest,
        "files": [{"path": name, "base64": base64.b64encode(data).decode("ascii")}
            for name, data in files.items()]}


def extension(source, min_build_id):
    if isinstance(min_build_id, bool) or not 30000126 <= min_build_id <= 99999999:
        raise ValueError("Supply an explicit mdo build_id for the intended host")
    manifest = source["manifest"]
    return {"format": "mdo.extension.v2", "manifest": {
        "slug": manifest["id"], "name": manifest["name"], "version": manifest["version"],
        "description": manifest["description"], "author": manifest["author"],
        "copyright": "Copyright (c) 2026 xywhsoft", "license": manifest["license"],
        "readme": (ROOT / "docs/user-guide.md").read_text(encoding="utf-8"),
        "min_build_id": min_build_id, "platforms": PLATFORMS},
        "resources": [{"kind": "plugins", "id": source["id"],
            "content": json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            "files": source["files"]}]}


def build(output, min_build_id=None):
    source = payload()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stem = f"mohists-{source['manifest']['version']}"
    archive = output / (stem + ".zip")
    files = {entry["path"]: base64.b64decode(entry["base64"]) for entry in source["files"]}
    files["plugin.json"] = encode(source["manifest"])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            handle.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    artifacts = [archive]
    if min_build_id is not None:
        path = output / (stem + ".mdo-extension.json")
        path.write_bytes(encode(extension(source, min_build_id)))
        artifacts.append(path)
    inventory = {"plugin": source["id"], "version": source["manifest"]["version"],
        "runtime": json.loads((ROOT / "mdo-runtime.json").read_text(encoding="utf-8")),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "artifacts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts}}
    (output / (stem + ".checksums.json")).write_bytes(encode(inventory))
    return artifacts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--min-build-id", type=int,
        help="Explicit installation build serial; omit until a compatible mdo release is assigned")
    args = parser.parse_args()
    for artifact in build(args.output, args.min_build_id):
        print(f"{artifact.name}: {artifact.stat().st_size} bytes")
