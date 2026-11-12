"""Validate Workshop cards against the resources tracked in this repository."""

import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read_bytes(relative):
    return (ROOT / relative).read_bytes()


def read_json(relative):
    return json.loads(read_bytes(relative).decode("utf-8-sig"))



def field(value, name, default=None):
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return value.get(name, value.get(snake, default))


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def check_native(root, reference_models):
    documents = {}
    pending = []
    for file in [*root.glob("*.model*.json"), *(root / "assets/hitareas").glob("*.json")]:
        if file.name in reference_models:
            continue
        model = json.loads(file.read_bytes())
        groups = field(field(model, "FileReferences", model), "Motions", {})
        if not groups:
            continue
        identity = field(field(model, "Options", {}), "Id")
        assert identity and identity not in documents, (file, "duplicate or missing model ID")
        documents[identity] = (file, groups)
        pending.extend((identity, name) for name in groups
                       if re.fullmatch(r"start|idle|tap.*|shake.*|tick.*|leave.*|enter.*", name.split("#")[0], re.I))
        outer = {key: value for key, value in model.items() if key not in ("FileReferences", "motions")}
        pending.extend((identity, value) for value in strings(outer) if value.split(":")[0] in groups)
    visited = set()
    allowed = {"循环动作", "停止动作", "循环语音", "停止语音", "循环换装", "停止换装", "恢复待机", "关闭菜单"}
    while pending:
        identity, target = pending.pop()
        group, _, motion = target.partition(":")
        assert identity in documents and group in documents[identity][1], (root, identity, target, "missing motion target")
        file, groups = documents[identity]
        rows = groups[group]
        assert not motion or any(field(row, "Name") == motion for row in rows), (file, target)
        if (identity, group) in visited:
            continue
        visited.add((identity, group))
        for row in rows:
            if group.startswith("ui_prepare_voice_"):
                assert "stop_mtn 4" in field(row, "Command", ""), (file, "manual voice leaves stale menu")
                assert any(field(variable, "Name") == "ws_menu_open" and field(variable, "Code") == "assign 0"
                           for variable in field(row, "VarFloats", [])), (file, "manual voice menu state")
            next_motion = field(row, "NextMtn")
            if next_motion:
                pending.append((identity, next_motion))
            choices = field(row, "Choices", [])
            if choices:
                assert group == "ui_main#4" and len(choices) <= 5, (file, group)
            for choice in choices:
                assert field(choice, "Text") in allowed, (file, choice)
                pending.append((identity, field(choice, "NextMtn")))
            for key in ("Command", "PostCommand"):
                command_text = field(row, key, "")
                assert not any(token in command_text for token in ("ControlPanel", "127.0.0.1", "page_open_panel")), (file, group)
                for command in command_text.split(";"):
                    words = command.split()
                    if words[:1] == ["start_mtn"]:
                        if len(words) == 2:
                            pending.append((identity, words[1]))
                        elif len(words) == 3:
                            pending.append((words[1], words[2]))
    expected = {(identity, name) for identity, (_, groups) in documents.items() for name in groups}
    assert visited == expected, (root, "unreachable native groups", sorted(expected - visited)[:10])
    assert not (root / "ControlPanel").exists(), (root, "unused panel runtime")


def validate():
    catalog = read_json("workshop/catalog.json")
    tracked = set(
        subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        ).decode("utf-8").split("\0")
    )
    identities = set()
    totals = {"roles": 0, "costumes": 0, "voices": 0, "resourceFiles": 0}
    pending_menus = 0
    pending_tags = 0
    for relative in catalog["characters"]:
        entry = read_json(relative)
        identity = entry["id"]
        assert identity not in identities, (relative, "duplicate role")
        identities.add(identity)
        assert entry["game"] == catalog["game"], relative
        metadata = read_json(entry["metadata"])
        assert metadata["title"] and metadata["description"] and metadata["changeNote"], relative
        assert not re.search(r'[<>:"/\\|?*]', metadata["title"]), relative
        assert metadata["visibility"] in (0, 1, 2, 3), relative
        assert metadata["tags"][0] in ("Female", "Male", "Other"), relative
        assert "G" in metadata["tags"], relative

        image = read_bytes(entry["preview"])
        assert image.startswith(b"\x89PNG\r\n\x1a\n"), relative
        assert struct.unpack(">II", image[16:24]) == (768, 768), relative
        assert hashlib.sha256(image).hexdigest() == entry["coverSha256"], relative

        for key in ("model", "resourceManifest", "sourceLock", "voiceCatalog"):
            assert entry[key] in tracked, (relative, key, "resource missing from project")
        resources = read_json(entry["resourceManifest"])
        role_root = Path(entry["model"]).parent.as_posix()
        upload_files = [
            name for name in resources["files_sha256"]
            if name.startswith("assets/") or ".model" in name
        ]
        for name in upload_files:
            assert role_root + "/" + name in tracked, (relative, name)
        for name, expected in resources["files_sha256"].items():
            actual = read_bytes(role_root + "/" + name)
            assert hashlib.sha256(actual).hexdigest() == expected, (relative, name, "content hash mismatch")
        check_native(ROOT / role_root, resources.get("reference_models", {}))
        native = read_json(entry["model"])
        assert native.get("FileReferences") or native.get("model"), relative

        role = read_json(entry["voiceCatalog"])
        expected = {
            "costumes": len(role["costumes"]),
            "voices": len(role["voices"]),
            "actions": sum(len(costume["actions"]) for costume in role["costumes"]),
            "expressions": sum(len(costume["expressions"]) for costume in role["costumes"]),
        }
        assert expected == entry["counts"], (relative, "counts differ")
        assert ("Voice" in metadata["tags"]) == bool(role["voices"]), relative
        assert entry["coverCostume"] in {costume["id"] for costume in role["costumes"]}, relative
        pending_menus += entry["release"]["nativeMenu"] == "pending"
        pending_tags += bool(entry["release"]["genderTagReview"])
        totals["roles"] += 1
        totals["costumes"] += expected["costumes"]
        totals["voices"] += expected["voices"]
        totals["resourceFiles"] += len(upload_files)
    print(json.dumps({"game": catalog["game"], **totals,
                      "pendingNativeMenus": pending_menus,
                      "pendingTagReviews": pending_tags,
                      "publication": catalog["publication"], "errors": []}))


if __name__ == "__main__":
    validate()
