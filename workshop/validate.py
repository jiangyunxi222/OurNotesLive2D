"""Validate Workshop cards against the resources tracked in this repository."""

import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read_bytes(relative):
    file = ROOT / relative
    if file.is_file():
        return file.read_bytes()
    # Sparse worktrees retain the complete resource tree in Git.
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "show", "HEAD:" + relative]
    )


def read_json(relative):
    return json.loads(read_bytes(relative).decode("utf-8-sig"))


def validate():
    catalog = read_json("workshop/catalog.json")
    tracked = set(
        subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z"]
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
            assert entry[key] in tracked, (relative, key, "resource missing from Git")
        resources = read_json(entry["resourceManifest"])
        role_root = Path(entry["model"]).parent.as_posix()
        upload_files = [
            name for name in resources["files_sha256"]
            if name.startswith("assets/") or ".model" in name
        ]
        for name in upload_files:
            assert role_root + "/" + name in tracked, (relative, name)
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
