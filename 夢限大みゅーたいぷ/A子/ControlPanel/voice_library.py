"""Transactional edits to a standalone role's audio, captions and native routes."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import uuid
import wave


MAX_AUDIO_BYTES = 100 * 1024 * 1024


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").replace("\n", "\r\n").encode("utf-8")


def read(path):
    return json.loads(path.read_text("utf-8-sig"))


def panel_directory(root):
    current = root / "ControlPanel"
    return current if current.is_dir() else root / "控制台"


def native_event(c3, **fields):
    if c3:
        return fields
    names = {"MotionDuration": "motion_duration", "VarFloats": "var_floats", "PostCommand": "post_command"}
    result = {}
    for key, value in fields.items():
        if key == "VarFloats":
            value = [{name.lower(): item for name, item in variable.items()} for variable in value]
        result[names.get(key, key.lower())] = value
    return result


def recover(root):
    transaction = panel_directory(root) / ".local/voice-transaction"
    journal = transaction / "journal.json"
    if not journal.exists():
        if transaction.exists():
            shutil.rmtree(transaction)
        return
    state = read(journal)
    if not state.get("committed"):
        for number, entry in reversed(list(enumerate(state["files"]))):
            target = (root / entry["path"]).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError("语音恢复路径无效")
            backup = transaction / f"{number}.old"
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
            elif not entry["existed"]:
                target.unlink(missing_ok=True)
    shutil.rmtree(transaction)


def commit(root, changes):
    recover(root)
    transaction = panel_directory(root) / ".local/voice-transaction"
    transaction.mkdir(parents=True)
    entries = []
    try:
        for number, (relative, data) in enumerate(changes.items()):
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError("语音保存路径无效")
            entries.append({"path": relative, "existed": target.exists()})
            if data is not None:
                (transaction / f"{number}.new").write_bytes(data)
        journal = transaction / "journal.json"
        prepared = transaction / "prepared.tmp"
        prepared.write_bytes(encode({"files": entries}))
        os.replace(prepared, journal)
        for number, entry in enumerate(entries):
            target = root / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["existed"]:
                os.replace(target, transaction / f"{number}.old")
            staged = transaction / f"{number}.new"
            if staged.exists():
                os.replace(staged, target)
        marker = transaction / "committed.tmp"
        marker.write_bytes(encode({"files": entries, "committed": True}))
        os.replace(marker, journal)
    except BaseException:
        recover(root)
        raise
    # A committed edit remains valid if a virus scanner briefly holds a backup.
    try:
        shutil.rmtree(transaction)
    except OSError:
        pass


def validate_audio(data):
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError("音频为空或超过 100 MB")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            width = audio.getsampwidth()
            channels = audio.getnchannels()
            if not frames or not 8000 <= rate <= 192000 or channels not in (1, 2) or width not in (1, 2, 3, 4):
                raise ValueError("音频格式无效")
            if len(audio.readframes(frames)) != frames * width * channels:
                raise ValueError("音频文件不完整")
            return round(frames / rate, 6)
    except (wave.Error, EOFError) as error:
        raise ValueError("音频格式无效") from error


def edit(root, catalog, *, audio=None, subtitle=None, filename=None, delete_id=None):
    root = root.resolve()
    catalog = copy.deepcopy(catalog)
    manifest = read(root / "manifest.json")
    custom_path = "assets/voices/user-voices.json"
    custom = read(root / custom_path) if (root / custom_path).exists() else {"voices": []}
    changes = {}
    if audio is not None:
        if not isinstance(subtitle, str) or not subtitle.strip() or len(subtitle) > 2000 or "\x00" in subtitle:
            raise ValueError("请输入字幕，最多 2000 字")
        subtitle = subtitle.strip()
        duration = validate_audio(audio)
        item_id = max(catalog.get("nextVoiceId", 1000000), max((row["id"] + 1 for row in catalog["voices"]), default=0))
        token = uuid.uuid4().hex
        relative = f"assets/voices/user_{token}.wav"
        item = {"id": item_id, "name": " ".join(subtitle.split()), "caption": subtitle,
                "file": relative, "duration": duration, "flag": "heart_fav_" + token[:16], "uploaded": True}
        catalog["nextVoiceId"] = item_id + 1
        catalog["voices"].append(item)
        custom["voices"].append(dict(item, originalName=Path(str(filename or "audio")).name[:200]))
        changes[relative] = audio
    else:
        item = next((row for row in catalog["voices"] if row["id"] == delete_id), None)
        if item is None:
            raise ValueError("语音已删除，请刷新列表")
        catalog["voices"] = [row for row in catalog["voices"] if row["id"] != delete_id]
        custom["voices"] = [row for row in custom["voices"] if row["id"] != delete_id]
        if not any(row["file"] == item["file"] for row in catalog["voices"]):
            changes[item["file"]] = None
        source_path = "assets/voices/voice-sources.json"
        if (root / source_path).exists():
            sources = read(root / source_path)
            sources["voices"] = [row for row in sources["voices"] if row["path"] != item["file"]]
            changes[source_path] = encode(sources)
    changes[custom_path] = encode(custom)
    voice_group = f"web_uploaded_voice_{item['id']}#2"
    for costume in catalog["costumes"]:
        model = read(root / costume["file"])
        c3 = "FileReferences" in model
        refs = model["FileReferences"] if c3 else model
        groups = refs["Motions" if c3 else "motions"]
        name_key, sound_key, text_key = ("Name", "Sound", "Text") if c3 else ("name", "sound", "text")
        if audio is not None:
            rows = []
            for captions in (False, True):
                row = {"Name": "play", "Sound": item["file"], "Command": "lip_sync enforce",
                       "PostCommand": "lip_sync enable", "Priority": 9, "Interruptable": True,
                       "VarFloats": [{"Name": "voice_captions_enabled", "Type": 1, "Code": f"equal {int(captions)}"}]}
                if captions:
                    row["Text"] = item["caption"]
                rows.append(native_event(c3, **row))
            groups[voice_group] = rows
        else:
            groups.pop(voice_group, None)
            groups.pop(f"web_voice_{item['id']:03d}#6", None)
            for key, rows in groups.items():
                kept = []
                for row in rows:
                    matches = row.get(sound_key) == item["file"] and (item["file"] in changes or row.get(name_key) == f"voice_{item['id']:03d}")
                    if not matches:
                        kept.append(row)
                    elif row.get("File" if c3 else "file"):
                        row.pop(sound_key, None)
                        row.pop(text_key, None)
                        kept.append(row)
                groups[key] = kept
        changes[costume["file"]] = encode(model)
    parent = read(root / catalog["entry"])
    c3 = "FileReferences" in parent
    groups = (parent["FileReferences"] if c3 else parent)["Motions" if c3 else "motions"]
    parent_group = f"web_voice_{item['id']:03d}"
    if audio is not None:
        rows = []
        for costume in catalog["costumes"]:
            row = {"Name": f"costume_{costume['id']:03d}", "Priority": 9, "Interruptable": True,
                   "MotionDuration": 1, "Command": f"start_mtn {costume['modelId']} {voice_group}",
                   "VarFloats": [{"Name": "selected_costume", "Type": 1, "Code": f"equal {costume['id']}"},
                                 {"Name": "costume_loading", "Type": 1, "Code": "equal 0"}]}
            rows.append(native_event(c3, **row))
        groups[parent_group] = rows
        for value in (0, 1):
            groups[f"web_fav_{item['flag'].removeprefix('heart_fav_')}_{value}"] = [native_event(
                c3, Name="set", Priority=9, Interruptable=True, MotionDuration=1,
                VarFloats=[{"Name": item["flag"], "Type": 2, "Code": f"assign {value}"}])]
    else:
        groups.pop(parent_group, None)
        if item.get("uploaded"):
            for value in (0, 1):
                groups.pop(f"web_fav_{item['flag'].removeprefix('heart_fav_')}_{value}", None)
    revision = catalog.get("motionRigRevision", 1) + 1
    start = groups["Start" if c3 else "start"][0]
    for row in start.get("VarFloats" if c3 else "var_floats", []):
        if row.get("Name" if c3 else "name") == "motion_rig_revision":
            row["Code" if c3 else "code"] = f"assign {revision}"
    catalog["motionRigRevision"] = manifest["motion_rig_revision"] = revision
    catalog["voiceLibraryRevision"] = catalog.get("voiceLibraryRevision", 0) + 1
    changes[catalog["entry"]] = encode(parent)
    changes[(panel_directory(root) / "data" / f"{catalog['id']}.json").relative_to(root).as_posix()] = encode(catalog)
    for relative, data in changes.items():
        if data is None:
            manifest["files_sha256"].pop(relative, None)
        else:
            manifest["files_sha256"][relative] = hashlib.sha256(data).hexdigest()
    changes["manifest.json"] = encode(manifest)
    commit(root, changes)
    return catalog, item
