"""Build only Mohists source assets, never its development Home or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ("runtime-src", "roles", "web")
DOCUMENTS = ("extension.json", "plugin.json", "README.md", "LICENSE", "mdo-runtime.json", "docs/user-guide.md", "docs/implementation.md")
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


def role_header(root=ROOT):
    """Compile the four authoritative role documents into public AddAgent descriptors."""
    rows = []
    for filename, ident, primary in (("coordinator", "agent.mohists", True),
            ("researcher", "subagent.mohists-researcher", False),
            ("worker", "subagent.mohists-worker", False),
            ("reviewer", "subagent.mohists-reviewer", False)):
        text = (Path(root) / "roles" / (filename + ".md")).read_text(encoding="utf-8")
        head, prompt = text.removeprefix("---\n").split("\n---\n", 1)
        config = {}
        for line in head.splitlines():
            key, value = line.split(":", 1); value = value.strip()
            try: value = json.loads(value)
            except json.JSONDecodeError: pass
            config[key] = value
        config.update(prompt=prompt, prompt_mode="replace")
        flags = "MDO_AGENT_MAIN" if primary else "MDO_AGENT_SUBAGENT"
        flags += "|MDO_AGENT_ALLOW_BACKGROUND"
        if config.get("read_only"): flags += "|MDO_AGENT_READ_ONLY"
        if config.get("allow_delegation"): flags += "|MDO_AGENT_ALLOW_DELEGATION"
        effects = "MDO_TOOL_EFFECT_READ" if config.get("read_only") else "MDO_TOOL_EFFECT_ALL"
        literal = lambda v: json.dumps(v, ensure_ascii=False)
        rows.append("    memset(&A,0,sizeof(A)); A.Size=sizeof(A); A.AbiVersion=1;\n"
            + f"    A.Id={literal(ident)}; A.Name={literal(config['name'])}; A.Description={literal(config['description'])};\n"
            + f"    A.SystemPrompt={literal(prompt)}; A.ConfigurationJson={literal(json.dumps(config,ensure_ascii=False))};\n"
            + f"    A.Flags={flags}; A.AllowedEffects={effects}; A.MaxTurns={128 if primary else 64}; A.TimeoutMilliseconds=120000; A.MaxFinalBytes=65536; A.MaxDepth={4 if primary else 1};\n"
            + "    if(R->AddAgent(R->Context,&A,Error,Capacity)!=MDO_RESULT_OK)return MDO_RESULT_ERROR;\n")
    return ("/* Generated from roles/*.md by tools/package.py. */\n"
        "static mdo_result MhRegisterRoles(const mdo_registrar_v1* R,char* Error,size_t Capacity){\n"
        "    mdo_agent_v1 A;\n" + "".join(rows) + "    return MDO_RESULT_OK;\n}\n").encode("utf-8")


def build(output, root=ROOT):
    root = Path(root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
    recipe = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    files = source_files(root)
    files["runtime-src/roles.inc.h"] = role_header(root)
    if any(name not in files for name in recipe["entry"].values()):
        raise ValueError("Plugin entry must be inside its published directory")
    stem = f"mohists-{manifest['version']}"
    archive = output / (stem + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            handle.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    artifacts = [archive]
    inventory = {"plugin": manifest["alias"], "version": manifest["version"],
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "artifacts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts}}
    (output / (stem + ".checksums.json")).write_bytes(encode(inventory))
    return artifacts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for artifact in build(args.output):
        print(f"{artifact.name}: {artifact.stat().st_size} bytes")
