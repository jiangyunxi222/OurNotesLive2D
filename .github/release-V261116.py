"""Build verified, source-free role ZIPs for the existing releases."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile


def run(*arguments, **options):
    return subprocess.check_output(arguments, **options)


def api(path):
    return json.loads(run("gh", "api", path))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(role, item):
    manifest_path = role / "manifest.json"
    assert digest(manifest_path) == item["manifestSha256"]
    manifest = json.loads(manifest_path.read_bytes())
    files = {
        name: checksum for name, checksum in manifest["files_sha256"].items()
        if not (name.startswith("ControlPanel/") and name.endswith((".py", "/.gitignore")))
    }
    assert manifest["entry"] in files and "ControlPanel/EnableAutoStart.cmd" in files
    manifest["files_sha256"] = files
    archive = Path(item["asset"])
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zipped:
        for name, checksum in sorted(files.items()):
            path = role / name
            assert path.is_file() and path.resolve().is_relative_to(role.resolve()), name
            data = path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == checksum, name
            entry = zipfile.ZipInfo(f"{role.name}/{name}", (2026, 11, 16, 0, 0, 0))
            zipped.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=3)
        zipped.writestr(f"{role.name}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert set(zipped.namelist()) == {f"{role.name}/{name}" for name in (*files, "manifest.json")}
    return archive


repo = os.environ["SOURCE_REPO"]
inventory = json.loads(Path("inventory.json").read_bytes())
release_id = inventory["releaseId"]
release = api(f"repos/{repo}/releases/{release_id}")
assert release["tag_name"] == "V261115" and not release["draft"]
url = release["upload_url"].split("{", 1)[0]
assert url == f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
asset_path = f"repos/{repo}/releases/{release_id}/assets?per_page=100"
roles = inventory["roles"][int(os.environ["SHARD"])::6]
commit = inventory["commit"]

run("git", "init", "source")
run("git", "-C", "source", "remote", "add", "origin", f"https://github.com/{repo}.git")
run("git", "-C", "source", "config", "remote.origin.promisor", "true")
run("git", "-C", "source", "config", "remote.origin.partialclonefilter", "blob:none")
run("git", "-C", "source", "fetch", "--depth=1", "--filter=blob:none", "origin", commit)
run("git", "-C", "source", "sparse-checkout", "set", "--cone", "--stdin",
    input=("\n".join(role["directory"] for role in roles) + "\n").encode())
run("git", "-C", "source", "checkout", "--detach", commit)

for item in roles:
    archive = build(Path("source") / item["directory"], item)
    checksum = "sha256:" + digest(archive)
    size = archive.stat().st_size
    for attempt in range(3):
        assets = api(asset_path)
        existing = next((row for row in assets if row["name"] == archive.name), None)
        if existing and existing["state"] == "uploaded":
            assert existing["digest"] == checksum and existing["size"] == size, archive.name
            break
        if existing and existing["state"] == "starter":
            run("gh", "api", "--method", "DELETE", f"repos/{repo}/releases/assets/{existing['id']}")
        try:
            run("gh", "release", "upload", "V261115", "-R", repo, str(archive), timeout=180)
            uploaded = next(row for row in api(asset_path) if row["name"] == archive.name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, StopIteration):
            time.sleep(3 * (attempt + 1))
            continue
        assert uploaded["name"] == archive.name and uploaded["digest"] == checksum and uploaded["size"] == size
        break
    else:
        raise RuntimeError(f"Upload failed: {archive.name}")
    print(f"VERIFIED {archive.name} {checksum} {size}", flush=True)
    archive.unlink()
