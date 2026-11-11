"""Local, offline control page for the resource libraries and Live2DViewerEX."""

import argparse
import base64
import copy
import hashlib
import json
import mimetypes
import math
import os
import random
import secrets
import socket
import struct
import threading
import time
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
REPO = HERE.parent
PORT = 25000
if (HERE / "library.json").exists():
    PORT = json.loads((HERE / "library.json").read_text(encoding="utf-8-sig"))[0][
        "port"
    ]
NATIVE = (
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    / "Steam/steamapps/common/Live2DViewerEX/bin"
)
KINDS = ("action", "expression", "costume", "voice")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def native_data(path):
    try:
        data = path.read_bytes()
        key = data[0] ^ 123
        return json.loads(bytes(value ^ key for value in data))
    except (OSError, ValueError, IndexError):
        return {}


class Player:
    def __init__(self):
        self.socket = None
        self.lock = threading.RLock()
        self.port = 0
        self.on_tap = None
        self.last_received = time.monotonic()

    def connect(self):
        with self.lock:
            self.close()
            try:
                self.port = int((NATIVE / "app_port").read_text().strip())
            except (OSError, ValueError):
                self.port = 10086
            connection = socket.create_connection(("127.0.0.1", self.port), timeout=3)
            key = base64.b64encode(secrets.token_bytes(16)).decode()
            connection.sendall(
                (
                    f"GET /api HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
                ).encode()
            )
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = connection.recv(4096)
                if not chunk:
                    raise ConnectionError("播放器未响应")
                response += chunk
                if len(response) > 16384:
                    raise ConnectionError("播放器握手无效")
            expected = base64.b64encode(
                hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                ).digest()
            )
            headers = {
                line.partition(b":")[0].lower(): line.partition(b":")[2].strip()
                for line in response.split(b"\r\n")[1:]
                if b":" in line
            }
            if (
                not response.startswith(b"HTTP/1.1 101")
                or headers.get(b"sec-websocket-accept") != expected
            ):
                connection.close()
                raise ConnectionError("播放器接口未就绪")
            connection.settimeout(None)
            self.socket = connection
            self.last_received = time.monotonic()
            threading.Thread(
                target=self.listen, args=(connection,), daemon=True
            ).start()
            self.send(10000, None)

    def close(self):
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.socket.close()
            except OSError:
                pass
        self.socket = None

    def send(self, message, data):
        with self.lock:
            if not self.socket:
                raise ConnectionError("请先连接桌面播放器")
            payload = json.dumps(
                {
                    "msg": message,
                    "msgId": int(time.time() * 1000) % 2147483647,
                    "data": data,
                },
                ensure_ascii=False,
            ).encode()
            mask = secrets.token_bytes(4)
            size = len(payload)
            header = (
                bytes((129, 128 | size))
                if size < 126
                else bytes((129, 254)) + struct.pack("!H", size)
            )
            try:
                self.socket.sendall(
                    header
                    + mask
                    + bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
                )
            except OSError:
                self.close()
                raise ConnectionError("桌面连接已断开，请重新连接")

    def listen(self, connection):
        def exact(size):
            data = b""
            while len(data) < size:
                part = connection.recv(size - len(data))
                if not part:
                    raise ConnectionError()
                data += part
            return data

        try:
            while True:
                header = exact(2)
                length = header[1] & 127
                if length == 126:
                    length = struct.unpack("!H", exact(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", exact(8))[0]
                if length > 1024 * 1024:
                    raise ConnectionError()
                mask = exact(4) if header[1] & 128 else None
                payload = exact(length)
                self.last_received = time.monotonic()
                if mask:
                    payload = bytes(
                        value ^ mask[i % 4] for i, value in enumerate(payload)
                    )
                opcode = header[0] & 15
                if opcode == 8:
                    break
                if opcode == 9:
                    mask = secrets.token_bytes(4)
                    with self.lock:
                        connection.sendall(
                            bytes((138, 128 | len(payload)))
                            + mask
                            + bytes(
                                value ^ mask[i % 4] for i, value in enumerate(payload)
                            )
                        )
                if opcode == 1 and self.on_tap:
                    try:
                        message = json.loads(payload)
                        if message.get("msg") == 10002:
                            self.on_tap(message.get("data") or {})
                    except (ValueError, KeyError):
                        pass
        except (OSError, ConnectionError):
            pass
        finally:
            if self.socket is connection:
                self.close()


class Studio:
    def __init__(self):
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.events = []
        self.sequence = 0
        self.roles = {}
        self.roots = {}
        self.catalogs = {}
        self.player = Player()
        self.slot = None
        self.linked = False
        self.player.on_tap = self.on_native_tap
        self.loading = False
        self.reconnect_requested = False
        self.monitor_started = False
        candidates = [REPO]
        for root in dict.fromkeys(path.resolve() for path in candidates):
            catalog = root / "控制台/library.json"
            if not catalog.exists():
                continue
            for role in read(catalog):
                self.roles[role["id"]] = role
                self.roots[role["id"]] = root
        self.state_path = HERE / ".local/state.json"
        try:
            self.saved = read(self.state_path)
        except (OSError, ValueError):
            self.saved = {"roles": {}}
        self.current = self.saved.get("current")
        if self.current not in self.roles:
            self.current = next(
                (
                    key
                    for key, role in self.roles.items()
                    if role["game"] == "OurNotes" and role["name"] == "千早爱音"
                ),
                next(iter(self.roles), None),
            )
        self.jobs = {kind: 0 for kind in ("action", "voice", "costume")}
        self.looping = {kind: False for kind in self.jobs}
        self.cursors = {}
        self.timers = {}
        self.costume_due = False
        self.popup = None
        self.input_router = None
        self.input_epoch = 0
        self.native_executable = NATIVE / "lw/lw.exe"
        self.last_menu_request = None
        self.last_native_toggles = {}
        self.next_reconnect_at = 0
        self.playing = {}
        if self.saved.get("desktop_requested"):
            self.reconnect_requested = True
            self.monitor_started = True
            threading.Thread(target=self.maintain_connection, daemon=True).start()

    def catalog(self, role_id=None):
        role_id = role_id or self.current
        if role_id not in self.roles:
            raise ValueError("角色不存在")
        if role_id not in self.catalogs:
            self.catalogs[role_id] = read(
                self.roots[role_id] / "控制台/data" / (role_id + ".json")
            )
        return self.catalogs[role_id]

    def root(self, role_id=None):
        role = self.catalog(role_id)
        return (self.roots[role["id"]] / role["directory"]).resolve()

    def settings(self, role_id=None):
        role_id = role_id or self.current
        if role_id not in self.saved["roles"]:
            values = {}
            target = str(self.root(role_id)).replace("\\", "/").casefold() + "/"
            profiles = NATIVE / "save/cha"
            favorites = set()
            if profiles.exists():
                paths = [self.root(role_id) / self.catalog(role_id)["entry"]] + [
                    self.root(role_id) / costume["file"]
                    for costume in self.catalog(role_id)["costumes"]
                ]
                files = [
                    profiles
                    / hashlib.md5(str(path).replace("\\", "/").encode()).hexdigest()
                    for path in paths
                ]
                for file in sorted(
                    (file for file in files if file.exists()),
                    key=lambda file: file.stat().st_mtime,
                ):
                    data = native_data(file)
                    variables = data.get("varFloats") or {}
                    values.update(variables)
                    favorites.update(
                        name
                        for name, value in variables.items()
                        if name.startswith("heart_fav_") and value == 1
                    )
            self.saved["roles"][role_id] = {
                "costume": int(values.get("selected_costume", 1)),
                "favorites": sorted(favorites),
                "captions": bool(values.get("voice_captions_enabled", 1)),
                "bodyOnly": bool(values.get("heart_body_only", 0)),
                "actionScope": int(values.get("heart_action_scope", 0)),
                "voiceScope": int(values.get("heart_voice_scope", 0)),
            }
        settings = self.saved["roles"][role_id]
        settings.setdefault("costumeScope", 0)
        for kind, interval in (("action", 12), ("voice", 2.5), ("costume", 15)):
            settings.setdefault(kind + "Order", "random")
            settings.setdefault(kind + "Interval", interval)
        valid = {costume["id"] for costume in self.catalog(role_id)["costumes"]}
        if settings["costume"] not in valid:
            settings["costume"] = min(valid)
        return settings

    def costume(self):
        return next(
            costume
            for costume in self.catalog()["costumes"]
            if costume["id"] == self.settings()["costume"]
        )

    def save(self):
        self.saved["current"] = self.current
        atomic_write(self.state_path, self.saved)

    def snapshot(self):
        return {
            "role": self.current,
            "settings": copy.deepcopy(self.settings()),
            "linked": self.linked and self.player.socket is not None,
            "reconnecting": self.reconnect_requested
            and (not self.linked or self.player.socket is None),
            "slot": self.slot,
            "looping": self.looping.copy(),
            "playing": self.playing.copy(),
            "sequence": self.sequence,
            "waitingForCostume": self.costume_due,
            "menu": self.popup.status.copy() if self.popup else None,
            "input": self.input_router.status.copy() if self.input_router else None,
        }

    def emit(self, kind, data=None):
        with self.changed:
            self.sequence += 1
            event = {
                "id": self.sequence,
                "type": kind,
                "data": data,
                "state": self.snapshot(),
            }
            self.events.append(event)
            self.events = self.events[-80:]
            self.changed.notify_all()

    def native(self, group):
        if self.linked:
            if self.player.socket is None:
                self.linked = False
                self.emit("connection")
                return False
            if not self.loading:
                actual = self.slot_path()
                expected = self.expected_path()
                if actual and actual != expected:
                    self.linked = False
                    self.reconnect_requested = False
                    self.saved["desktop_requested"] = False
                    self.save()
                    self.slot = None
                    self.player.close()
                    self.emit("connection")
                    self.emit("notice", "桌面模型已发生变化，页面预览仍可继续使用")
                    return False
            try:
                self.player.send(13200, {"id": self.slot, "type": 0, "mtn": group})
                return True
            except ConnectionError:
                self.linked = False
                self.emit("connection")
                self.emit("notice", "桌面连接已断开，页面预览仍可继续使用")
        return False

    def expected_path(self):
        return str(self.root() / self.catalog()["entry"]).replace("\\", "/").casefold()

    def slot_path(self):
        slots = native_data(NATIVE / "save/autosave.dat").get("charDatas", [])
        if self.slot is None or self.slot >= len(slots):
            return ""
        if not slots[self.slot].get("jsonFilePath") and any(
            slots[self.slot].get(key) for key in ("zipFilePath", "workshopFileId")
        ):
            return "@other-model"
        return (
            str(slots[self.slot].get("jsonFilePath") or "")
            .replace("\\", "/")
            .casefold()
        )

    def maintain_connection(self):
        """Reattach the same loaded character after a dropped socket."""
        last_ping = time.monotonic()
        while True:
            time.sleep(0.25)
            with self.lock:
                if not self.reconnect_requested:
                    continue
                try:
                    if (
                        self.player.socket
                        and time.monotonic() - self.player.last_received > 35
                    ):
                        self.player.close()
                    if self.player.socket and self.linked:
                        if not self.adopt_native_costume():
                            self.native_menu_events()
                        if time.monotonic() - last_ping >= 10:
                            self.player.send(10000, None)
                            last_ping = time.monotonic()
                        continue
                    self.linked = False
                    if time.monotonic() < self.next_reconnect_at:
                        continue
                    self.next_reconnect_at = time.monotonic() + 2
                    if self.slot is None:
                        slots = native_data(NATIVE / "save/autosave.dat").get(
                            "charDatas", []
                        )
                        self.slot = next(
                            (
                                index
                                for index, slot in enumerate(slots)
                                if str(slot.get("jsonFilePath") or "")
                                .replace("\\", "/")
                                .casefold()
                                == self.expected_path()
                            ),
                            None,
                        )
                    actual = self.slot_path()
                    if actual and actual != self.expected_path():
                        self.reconnect_requested = False
                        self.saved["desktop_requested"] = False
                        self.save()
                        self.slot = None
                        self.emit("connection")
                        continue
                    self.emit("connection")
                    if not actual:
                        continue
                    self.player.connect()
                    self.linked = True
                    self.adopt_native_costume()
                    variables = self.native_variables()
                    if (
                        variables.get("page_menu_version") != 7
                        or variables.get("page_input_revision") != 2
                        or variables.get("motion_rig_revision") != 1
                    ):
                        self.load_native()
                    self.sync_preferences()
                    self.sync_favorites()
                    self.sync_loop_flags()
                    self.emit("connection")
                    last_ping = time.monotonic()
                except (OSError, ConnectionError):
                    self.linked = False
                    self.player.close()

    def thumbnail_path(self, role_id, costume_id):
        costume = next(
            (
                item
                for item in self.catalog(role_id)["costumes"]
                if item["id"] == costume_id
            ),
            None,
        )
        if costume is None:
            raise ValueError("衣装不存在")
        stamp = (self.root(role_id) / costume["file"]).stat().st_mtime_ns
        return HERE / ".local/thumbnails" / f"{role_id}-{costume_id}-{stamp}.webp"

    def page_catalog(self, role_id):
        catalog = copy.deepcopy(self.catalog(role_id))
        for costume in catalog["costumes"]:
            if self.thumbnail_path(role_id, costume["id"]).is_file():
                costume["thumbnail"] = f'/api/thumbnail/{role_id}/{costume["id"]}'
        return catalog

    def save_thumbnail(self, role_id, costume_id, image):
        if not isinstance(image, str) or not image.startswith(
            "data:image/webp;base64,"
        ):
            raise ValueError("预览图片格式无效")
        data = base64.b64decode(image.partition(",")[2], validate=True)
        if (
            not 12 <= len(data) <= 1024 * 1024
            or data[:4] != b"RIFF"
            or data[8:12] != b"WEBP"
        ):
            raise ValueError("预览图片格式无效")
        path = self.thumbnail_path(role_id, costume_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return {"saved": True}

    def stop(self, kind):
        if kind not in self.jobs:
            raise ValueError("操作类型无效")
        self.jobs[kind] += 1
        timer = self.timers.pop(kind, None)
        if timer:
            timer.cancel()
        self.looping[kind] = False
        resume = kind == "costume" and self.costume_due
        if kind == "costume":
            self.costume_due = False
        self.playing.pop(kind, None)
        self.native(f"web_set_page_loop_{kind}_0")
        if kind != "costume":
            self.native("web_stop_voice" if kind == "voice" else "web_idle")
        if kind == "voice":
            self.native("carrier_hide_text#5")
        self.emit("stop", kind)
        if resume:
            self.resume_playback_loops(only_paused=True)

    def select(self, role_id, costume_id=None, from_loop=False):
        catalog = self.catalog(role_id)
        if costume_id is not None and costume_id not in {
            costume["id"] for costume in catalog["costumes"]
        }:
            raise ValueError("衣装不存在")
        if role_id == self.current and (
            costume_id is None or costume_id == self.settings()["costume"]
        ):
            if from_loop:
                self.resume_playback_loops(only_paused=True)
            return self.snapshot()
        if not from_loop:
            self.costume_due = False
            self.stop("costume")
        self.input_epoch += 1
        for kind in ("action", "voice"):
            self.jobs[kind] += 1
            timer = self.timers.pop(kind, None)
            if timer:
                timer.cancel()
            self.playing.pop(kind, None)
            self.emit("stop", kind)
        previous = self.current
        self.current = role_id
        if costume_id is not None:
            self.settings()["costume"] = costume_id
        if self.linked:
            try:
                if previous != role_id:
                    self.load_native()
                else:
                    self.native(f'web_costume_{self.settings()["costume"]:03d}')
                    if self.linked:
                        self.wait_native()
                        self.sync_preferences()
                        self.sync_favorites()
            except (OSError, ConnectionError):
                self.linked = False
                self.player.close()
                self.emit("notice", "桌面换装仍在恢复连接，页面循环继续运行")
        self.save()
        self.emit("selection")
        self.sync_loop_flags()
        self.resume_playback_loops()
        return self.snapshot()

    def connect(self, attach=False):
        try:
            self.player.connect()
        except OSError:
            raise ConnectionError("请先启动 Live2DViewerEX，再点击连接桌面") from None
        attached = False
        slots = native_data(NATIVE / "save/autosave.dat").get("charDatas", [])
        expected = (
            str(self.root() / self.catalog()["entry"]).replace("\\", "/").casefold()
        )
        if self.slot is not None:
            actual = (
                str(slots[self.slot].get("jsonFilePath") or "")
                .replace("\\", "/")
                .casefold()
                if self.slot < len(slots)
                else ""
            )
            if actual != expected:
                self.slot = None
        if self.slot is None:
            slots = native_data(NATIVE / "save/autosave.dat").get("charDatas", [])
            expected = (
                str(self.root() / self.catalog()["entry"]).replace("\\", "/").casefold()
            )
            self.slot = next(
                (
                    index
                    for index, slot in enumerate(slots)
                    if str(slot.get("jsonFilePath") or "").replace("\\", "/").casefold()
                    == expected
                ),
                None,
            )
            if self.slot is not None:
                variables = self.native_variables()
                self.adopt_native_costume()
                attached = (
                    variables.get("page_menu_version") == 7
                    and variables.get("page_input_revision") == 2
                    and variables.get("motion_rig_revision") == 1
                )
            if self.slot is None:
                self.slot = next(
                    (
                        index
                        for index in range(8)
                        if index >= len(slots)
                        or not any(
                            slots[index].get(key)
                            for key in ("jsonFilePath", "zipFilePath", "workshopFileId")
                        )
                    ),
                    None,
                )
            if self.slot is None:
                raise ValueError("桌面模型位已满，请先空出一个模型位后重试")
        self.linked = True
        try:
            if attached:
                self.adopt_native_costume()
                self.wait_native()
                self.sync_preferences()
                self.sync_favorites()
                self.sync_loop_flags()
            else:
                self.load_native()
        except (OSError, ConnectionError):
            self.linked = False
            self.player.close()
            self.emit("connection")
            raise
        self.reconnect_requested = True
        self.saved["desktop_requested"] = True
        self.save()
        if not self.monitor_started:
            self.monitor_started = True
            threading.Thread(target=self.maintain_connection, daemon=True).start()
        self.emit("connection")
        return self.snapshot()

    def load_native(self):
        self.loading = True
        try:
            previous_count = self.native_variables().get("page_load_count", 0)
            self.player.send(
                13000,
                {"id": self.slot, "file": str(self.root() / self.catalog()["entry"])},
            )
            self.wait_native(any_costume=True, minimum_load_count=previous_count + 1)
            self.native(f'web_costume_{self.settings()["costume"]:03d}')
            self.wait_native()
            self.sync_preferences()
            self.sync_favorites()
            self.sync_loop_flags()
        finally:
            self.loading = False

    def native_variables(self):
        path = str(self.root() / self.catalog()["entry"]).replace("\\", "/")
        profile = NATIVE / "save/cha" / hashlib.md5(path.encode()).hexdigest()
        return native_data(profile).get("varFloats") or {}

    def desktop_anchor(self):
        slots = native_data(NATIVE / "save/autosave.dat").get("charDatas", [])
        if self.slot is None or self.slot >= len(slots):
            return None
        slot = slots[self.slot]
        if (
            str(slot.get("jsonFilePath") or "").replace("\\", "/").casefold()
            != self.expected_path()
        ):
            return None
        path = str(self.root() / self.catalog()["entry"]).replace("\\", "/")
        profile = native_data(
            NATIVE / "save/cha" / hashlib.md5(path.encode()).hexdigest()
        )
        transform = (profile.get("transforms") or {}).get(slot.get("lastTransKey"))
        if not transform:
            return None
        world_height = 18.0
        if abs(transform.get("viewportY", 0)) > 0.00001:
            world_height = abs(transform.get("y", 0) / transform["viewportY"])
        elif abs(transform.get("viewportX", 0)) > 0.00001:
            import ctypes

            width = ctypes.windll.user32.GetSystemMetrics(78)
            height = ctypes.windll.user32.GetSystemMetrics(79)
            world_height = (
                abs(transform.get("x", 0) / transform["viewportX"]) * height / width
            )
        if not math.isfinite(world_height) or world_height <= 0:
            return None
        return {
            "x": transform.get("viewportX", 0),
            "y": transform.get("viewportY", 0),
            "scale": transform.get("scale", 1),
            "mirror": transform.get("mirror", False),
            "rotate": transform.get("rotate", 0),
            "worldHeight": world_height,
        }

    def adopt_native_costume(self):
        variables = self.native_variables()
        costume_id = variables.get("selected_costume")
        if variables.get("costume_loading") != 0 or costume_id not in {
            item["id"] for item in self.catalog()["costumes"]
        }:
            return False
        if costume_id != self.settings()["costume"]:
            self.settings()["costume"] = int(costume_id)
            self.save()
            self.emit("selection")
            self.sync_preferences()
            self.sync_favorites()
            self.sync_loop_flags()
            self.resume_playback_loops()
            return True
        return False

    def sync_loop_flags(self):
        self.native("web_set_page_backend_connected_1")
        for kind in self.jobs:
            self.native(f"web_set_page_loop_{kind}_{int(self.looping[kind])}")

    def resume_playback_loops(self, only_paused=False):
        for kind in ("action", "voice"):
            if self.looping[kind] and (not only_paused or kind not in self.playing):
                try:
                    self.operate(kind, loop=True, randomize=True)
                except (ValueError, ConnectionError):
                    self.stop(kind)
                    self.emit(
                        "notice",
                        "当前衣装的循环范围为空，已停止"
                        + ("动作" if kind == "action" else "语音")
                        + "循环",
                    )

    def native_menu_events(self):
        variables = self.native_variables()
        request = variables.get("page_menu_request", 0)
        if request != self.last_menu_request:
            if (
                self.last_menu_request is not None
                and request > self.last_menu_request
                and self.popup
            ):
                self.popup.show()
            self.last_menu_request = request
        for kind in self.jobs:
            counter = variables.get("page_toggle_request_" + kind, 0)
            previous = self.last_native_toggles.get(kind)
            self.last_native_toggles[kind] = counter
            if (
                previous is None
                or counter <= previous
                or int(counter - previous) % 2 == 0
            ):
                continue
            try:
                if self.looping[kind]:
                    self.stop(kind)
                else:
                    self.operate(kind, loop=True, randomize=True)
            except (ValueError, ConnectionError) as error:
                self.stop(kind)
                self.emit("notice", str(error))

    def wait_native(self, any_costume=False, minimum_load_count=0):
        for attempt in range(120):
            variables = self.native_variables()
            if (
                variables.get("page_load_count", 0) >= minimum_load_count
                and variables.get("costume_loading") == 0
                and (
                    any_costume
                    or variables.get("selected_costume") == self.settings()["costume"]
                )
            ):
                return
            time.sleep(0.05)
        raise ConnectionError("桌面角色仍在加载，请稍后重新连接")

    def sync_preferences(self):
        for key, variable in (
            ("captions", "voice_captions_enabled"),
            ("bodyOnly", "heart_body_only"),
            ("actionScope", "heart_action_scope"),
            ("voiceScope", "heart_voice_scope"),
        ):
            self.native(f"web_set_{variable}_{int(self.settings()[key])}")

    def on_native_tap(self, data):
        if self.input_router and self.input_router.active:
            return
        if self.popup and self.popup.input_blocked:
            return
        with self.lock:
            if self.popup and self.popup.input_blocked:
                return
            if not self.linked or data.get("id") != self.slot:
                return
            if not str(data.get("modelId") or "").startswith(
                self.catalog().get("modelId", "not-current-role")
            ):
                return
            name = data.get("hitArea") or ""
            kinds = []
            if "语音" in name:
                kinds = ["voice"]
            elif "换装" in name:
                kinds = ["costume"]
            elif any(word in name for word in ("动作", "左臂", "右臂", "上身")):
                kinds = ["action"]
            for kind in kinds:
                self.jobs[kind] += 1
                self.looping[kind] = False
                self.playing.pop(kind, None)
                self.native(f"web_set_page_loop_{kind}_0")
                self.emit("stop", kind)

    def sync_favorites(self):
        available = {item["flag"] for kind in KINDS for item in self.entries(kind)}
        settings = self.settings()
        dirty = set(settings.get("dirty", []))
        for flag in (set(settings["favorites"]) | dirty) & available:
            self.native(
                f'web_fav_{flag.removeprefix("heart_fav_")}_{int(flag in settings["favorites"])}'
            )
        settings["dirty"] = sorted(dirty - available)

    def entries(self, kind):
        if kind == "voice":
            return self.catalog()["voices"]
        if kind == "costume":
            return self.catalog()["costumes"]
        return self.costume()["actions" if kind == "action" else "expressions"]

    def favorite(self, flag, enabled):
        catalog = self.catalog()
        flags = {voice["flag"] for voice in catalog["voices"]}
        for costume in catalog["costumes"]:
            flags.add(costume["flag"])
            flags.update(
                entry["flag"]
                for kind in ("actions", "expressions")
                for entry in costume[kind]
            )
        if flag not in flags:
            raise ValueError("收藏条目不存在")
        favorites = set(self.settings()["favorites"])
        if enabled:
            favorites.add(flag)
        else:
            favorites.discard(flag)
        self.settings()["favorites"] = sorted(favorites)
        dirty = set(self.settings().get("dirty", [])) | {flag}
        available = {item["flag"] for kind in KINDS for item in self.entries(kind)}
        if self.linked and flag in available:
            if self.native(f'web_fav_{flag.removeprefix("heart_fav_")}_{int(enabled)}'):
                dirty.discard(flag)
        self.settings()["dirty"] = sorted(dirty)
        self.save()
        self.emit("settings")
        return self.snapshot()

    def preference(self, key, value):
        variables = {
            "captions": "voice_captions_enabled",
            "bodyOnly": "heart_body_only",
            "actionScope": "heart_action_scope",
            "voiceScope": "heart_voice_scope",
            "costumeScope": None,
        }
        orders = {kind + "Order" for kind in self.jobs}
        intervals = {kind + "Interval" for kind in self.jobs}
        if key in orders:
            if value not in ("random", "sequence"):
                raise ValueError("播放顺序无效")
        elif key in intervals:
            minimum = 1 if key == "costumeInterval" else 0
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not minimum <= value <= 3600
            ):
                raise ValueError("间隔需在" + str(minimum) + "至3600秒之间")
        elif key not in variables or value not in (True, False, 0, 1):
            raise ValueError("设置无效")
        self.settings()[key] = value
        if variables.get(key):
            self.native(f"web_set_{variables[key]}_{int(value)}")
        if key in intervals:
            kind = key.removesuffix("Interval")
            if self.looping[kind]:
                if kind == "costume" and self.costume_due:
                    self.costume_due = False
                    self.resume_playback_loops()
                self.jobs[kind] += 1
                playing = self.playing.get(kind, {})
                item = next(
                    (
                        entry
                        for entry in self.entries(kind)
                        if entry["id"] == playing.get("id")
                    ),
                    {},
                )
                elapsed = time.time() - playing.get("startedAt", time.time())
                remaining = max(
                    0,
                    value
                    + (0 if kind == "costume" else item.get("duration", 0))
                    - elapsed,
                )
                self.schedule(kind, remaining, self.repeat, self.jobs[kind])
        self.save()
        self.emit("settings")
        return self.snapshot()

    def operate(
        self,
        kind,
        item_id=None,
        loop=False,
        randomize=False,
        body=False,
        direction=None,
    ):
        if kind not in KINDS:
            raise ValueError("操作类型无效")
        if kind == "expression" and item_id == -1:
            self.native("web_clear_expression")
            self.playing.pop("expression", None)
            self.emit("clear-expression")
            return self.snapshot()
        entries = self.entries(kind)
        if body and kind == "action":
            categories = {entry["category"] for entry in entries}
            direction = (
                direction
                if direction in categories
                else "body" if "body" in categories else "other"
            )
            entries = [entry for entry in entries if entry["category"] == direction]
        if randomize:
            only = (
                self.settings().get(kind + "Scope", 0)
                if kind in self.jobs and not body
                else self.settings()["bodyOnly"]
            )
            entries = [
                entry
                for entry in entries
                if not only or entry["flag"] in self.settings()["favorites"]
            ]
            if kind == "costume" and (
                not loop
                or (
                    len(entries) > 1 and self.settings().get(kind + "Order") == "random"
                )
            ):
                entries = [
                    entry
                    for entry in entries
                    if entry["id"] != self.settings()["costume"]
                ]
            if not entries:
                if body:
                    return self.snapshot()
                raise ValueError(
                    "当前范围为空，请先添加❤收藏" if only else "当前没有可播放的内容"
                )
            if loop and self.settings()[kind + "Order"] == "sequence":
                cursor_key = (kind, self.costume()["id"] if kind == "action" else 0)
                last_id = self.cursors.get(cursor_key, -1)
                item = next(
                    (entry for entry in entries if entry["id"] > last_id), entries[0]
                )
                self.cursors[cursor_key] = item["id"]
            else:
                item = random.choice(entries)
        else:
            item = next((entry for entry in entries if entry["id"] == item_id), None)
        if item is None:
            raise ValueError("条目不存在")
        if kind == "costume" and loop and not self.looping[kind]:
            self.jobs[kind] += 1
            self.looping[kind] = True
            self.cursors[(kind, 0)] = self.settings()["costume"]
            self.playing[kind] = {
                "id": self.costume()["id"],
                "name": self.costume()["name"],
                "startedAt": time.time(),
            }
            self.native("web_set_page_loop_costume_1")
            self.schedule(
                kind, self.settings()["costumeInterval"], self.repeat, self.jobs[kind]
            )
            self.emit("loop")
            return self.snapshot()
        if kind in self.jobs:
            self.jobs[kind] += 1
            generation = self.jobs[kind]
            self.looping[kind] = bool(loop)
        else:
            generation = 0
        if kind == "costume":
            self.select(self.current, item["id"], from_loop=loop)
        else:
            group = (
                f'web_{kind}_{item["id"]:03d}'
                if kind == "voice"
                else f'web_{kind}_{self.costume()["id"]:03d}_{item["id"]:03d}'
            )
            self.native(group)
        if kind in self.jobs:
            self.native(f"web_set_page_loop_{kind}_{int(loop)}")
        self.playing[kind] = {
            "id": item["id"],
            "startedAt": time.time(),
            "name": item["name"],
        }
        if kind != "costume":
            self.emit(
                "play",
                {
                    "kind": kind,
                    "item": item,
                    "generation": generation,
                    "costume": self.costume()["id"],
                },
            )
        if loop:
            duration = self.settings()[kind + "Interval"] + (
                0 if kind == "costume" else item.get("duration", 4)
            )
            self.schedule(kind, duration, self.repeat, generation)
        elif kind in self.jobs:
            self.schedule(kind, item.get("duration", 4), self.finish, generation)
        return self.snapshot()

    def schedule(self, kind, delay, callback, generation):
        previous = self.timers.pop(kind, None)
        if previous:
            previous.cancel()
        timer = threading.Timer(delay, callback, args=(kind, generation))
        timer.daemon = True
        self.timers[kind] = timer
        timer.start()

    def reset(self):
        self.input_epoch += 1
        self.costume_due = False
        for kind in self.jobs:
            self.stop(kind)
        self.operate("expression", item_id=-1)
        self.native("web_reset")
        self.native("carrier_hide_text#5")
        self.playing.clear()
        self.emit("reset")
        return self.snapshot()

    def finish(self, kind, generation):
        with self.lock:
            if self.jobs[kind] != generation:
                return
            self.playing.pop(kind, None)
            self.emit("ended", kind)

    def repeat(self, kind, generation):
        with self.lock:
            if self.jobs[kind] != generation or not self.looping[kind]:
                return
            if kind != "costume" and self.costume_due:
                self.playing.pop(kind, None)
                self.emit("ended", kind)
                return
            if kind == "costume":
                pool = [
                    item
                    for item in self.entries(kind)
                    if not self.settings()["costumeScope"]
                    or item["flag"] in self.settings()["favorites"]
                ]
                if pool and all(
                    item["id"] == self.settings()["costume"] for item in pool
                ):
                    self.costume_due = False
                    self.resume_playback_loops(only_paused=True)
                    self.schedule(
                        kind,
                        self.settings()["costumeInterval"],
                        self.repeat,
                        generation,
                    )
                    return
                self.costume_due = True
                remaining = 0
                for playing_kind in ("action", "voice"):
                    playing = self.playing.get(playing_kind)
                    if not playing:
                        continue
                    item = next(
                        (
                            entry
                            for entry in self.entries(playing_kind)
                            if entry["id"] == playing["id"]
                        ),
                        {},
                    )
                    remaining = max(
                        remaining,
                        item.get("duration", 0) - (time.time() - playing["startedAt"]),
                    )
                if remaining > 0:
                    self.schedule(kind, remaining + 0.05, self.repeat, generation)
                    self.emit("waiting")
                    return
                self.costume_due = False
            try:
                self.operate(kind, loop=True, randomize=True)
            except (ValueError, ConnectionError):
                self.stop(kind)
                if kind == "costume":
                    self.resume_playback_loops(only_paused=True)

    def preview(self, role_id, costume_id):
        role = self.catalog(role_id)
        costume = next(c for c in role["costumes"] if c["id"] == costume_id)
        model = read(self.root(role_id) / costume["file"])
        c3 = "FileReferences" in model
        refs = model["FileReferences"] if c3 else model
        groups = refs.get("Motions" if c3 else "motions", {})
        startup = groups["Start" if c3 else "start"][0]
        import re

        textures = refs.get("Textures" if c3 else "textures", []).copy()
        for index, path in re.findall(
            r"replace_tex (\d+) ([^;\s]+)",
            startup.get("PostCommand" if c3 else "post_command", ""),
        ):
            textures[int(index)] = path
        base = "/assets/" + role_id + "/"
        motions = {}
        for item in costume["actions"]:
            motions["page_" + str(item["id"])] = [
                {"File" if c3 else "file": base + item["file"]}
            ]
        idle = groups.get("Idle" if c3 else "idle", [])
        if idle:
            motions["Idle" if c3 else "idle"] = [
                {
                    "File" if c3 else "file": base
                    + idle[0]["File" if c3 else "file"]
                }
            ]
        expressions = [
            {
                "Name" if c3 else "name": str(item["id"]),
                "File" if c3 else "file": base + item["file"],
            }
            for item in costume["expressions"]
            if item["file"]
        ]
        if c3:
            result = {
                "Version": 3,
                "FileReferences": {
                    "Moc": base + refs["Moc"],
                    "Textures": [base + path for path in textures],
                    "Motions": motions,
                    "Expressions": expressions,
                },
            }
            for key in ("Physics", "Pose"):
                if refs.get(key):
                    result["FileReferences"][key] = base + refs[key]
        else:
            result = {
                "version": "Live2DViewerEX",
                "model": base + refs["model"],
                "textures": [base + path for path in textures],
                "motions": motions,
                "expressions": expressions,
            }
            for key in ("physics", "pose"):
                if refs.get(key):
                    result[key] = base + refs[key]
        controller = model.get("Controllers" if c3 else "controllers", {}).get(
            "LipSync" if c3 else "lip_sync", {}
        )
        result["pageMouthIds"] = [
            item.get("Id", item.get("id"))
            for item in controller.get("Items", controller.get("items", []))
        ]
        return result


STUDIO = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def respond(self, status, value, content_type="application/json; charset=utf-8"):
        data = (
            value
            if isinstance(value, bytes)
            else json.dumps(value, ensure_ascii=False).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/library":
                return self.respond(200, list(STUDIO.roles.values()))
            if path == "/api/state":
                return self.respond(200, STUDIO.snapshot())
            if path.startswith("/api/catalog/"):
                return self.respond(200, STUDIO.page_catalog(path.rsplit("/", 1)[1]))
            if path.startswith("/api/thumbnail/"):
                _, _, _, role_id, costume_id = path.split("/")
                return self.respond(
                    200,
                    STUDIO.thumbnail_path(role_id, int(costume_id)).read_bytes(),
                    "image/webp",
                )
            if path == "/api/events":
                return self.events()
            if path.startswith("/api/preview/"):
                _, _, _, role_id, costume_id = path.split("/")
                return self.respond(200, STUDIO.preview(role_id, int(costume_id)))
            if path.startswith("/assets/"):
                _, _, role_id, relative = path.split("/", 3)
                root = STUDIO.root(role_id)
                file = (root / relative).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    raise ValueError("资源不存在")
            else:
                root = HERE / "web"
                file = (root / (path.lstrip("/") or "index.html")).resolve()
                if not file.is_relative_to(root) or not file.is_file():
                    return self.respond(404, {"error": "页面不存在"})
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            data = file.read_bytes()
            self.respond(200, data, mime)
        except (ValueError, KeyError, StopIteration, OSError) as error:
            self.respond(404, {"error": str(error)})

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sequence = min(
            int(self.headers.get("Last-Event-ID", str(STUDIO.sequence))),
            STUDIO.sequence,
        )
        try:
            while True:
                with STUDIO.changed:
                    pending = [
                        event for event in STUDIO.events if event["id"] > sequence
                    ]
                    if not pending:
                        STUDIO.changed.wait(timeout=15)
                if not pending:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                for event in pending:
                    self.wfile.write(
                        (
                            "id: "
                            + str(event["id"])
                            + "\ndata: "
                            + json.dumps(event, ensure_ascii=False)
                            + "\n\n"
                        ).encode()
                    )
                    sequence = event["id"]
                self.wfile.flush()
        except (OSError, ConnectionError):
            return

    def do_POST(self):
        origin = self.headers.get("Origin")
        if self.headers.get("X-Studio-Request") != "1" or origin not in (
            None,
            f"http://127.0.0.1:{PORT}",
            f"http://localhost:{PORT}",
        ):
            return self.respond(403, {"error": "请求来源无效"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > (1500000 if self.path == "/api/thumbnail" else 65536):
                raise ValueError("请求过大")
            data = json.loads(self.rfile.read(length))
            with STUDIO.lock:
                if self.path == "/api/select":
                    result = STUDIO.select(data["role"], data.get("costume"))
                elif self.path == "/api/favorite":
                    result = STUDIO.favorite(data["flag"], bool(data["enabled"]))
                elif self.path == "/api/preference":
                    result = STUDIO.preference(data["key"], data["value"])
                elif self.path == "/api/operate":
                    result = STUDIO.operate(
                        data["kind"],
                        data.get("id"),
                        bool(data.get("loop")),
                        bool(data.get("random")),
                        bool(data.get("body")),
                        data.get("direction"),
                    )
                elif self.path == "/api/stop":
                    STUDIO.stop(data["kind"])
                    result = STUDIO.snapshot()
                elif self.path == "/api/connect":
                    result = STUDIO.connect(bool(data.get("attach")))
                elif self.path == "/api/thumbnail":
                    result = STUDIO.save_thumbnail(
                        data["role"], int(data["costume"]), data["image"]
                    )
                elif self.path == "/api/menu":
                    if STUDIO.popup:
                        STUDIO.popup.show()
                    result = STUDIO.snapshot()
                elif self.path == "/api/reset":
                    result = STUDIO.reset()
                else:
                    return self.respond(404, {"error": "操作不存在"})
            self.respond(200, result)
        except (ValueError, KeyError, ConnectionError, OSError) as error:
            self.respond(400, {"error": str(error)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    STUDIO = Studio()
    if not STUDIO.roles:
        raise SystemExit("没有找到资源目录，请将控制台保留在项目目录内。")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{PORT}")
        raise SystemExit(0)
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    from compact_menu import CompactMenu

    STUDIO.popup = CompactMenu(STUDIO, PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    STUDIO.popup.run()
