"""Capture owned avatar clicks before Windows delivers them to windows below."""

import ctypes
import json
import math
import queue
import struct
import threading
import time
from ctypes import wintypes
from pathlib import Path

REGIONS = ("expression", "voice", "left", "right", "body", "wardrobe", "menu")


class HitProjection:
    def __init__(self, regions, transform, options, viewport, canvas=None):
        self.regions = regions
        left, top, width, height = viewport
        self.center = (
            left + (0.5 + transform["x"]) * width,
            top + (0.5 - transform["y"]) * height,
        )
        world_height = transform["worldHeight"]
        pixels = height / world_height
        scale = transform.get("scale", 1)
        factor = options.get("ScaleFactor", options.get("scale_factor", 1))
        self.offset = (
            options.get("PositionX", options.get("position_x", 0)),
            options.get("PositionY", options.get("position_y", 0)),
        )
        self.scale = scale * pixels
        # ViewerEX's Model2Mesh spans 20 world units before the model scale.
        self.model_scale = factor * (20 / max(canvas) if canvas else world_height / 2)
        self.origin = (canvas[0] / 2, canvas[1] / 2) if canvas else (0, 0)
        self.mirror = -1 if transform.get("mirror") else 1
        # ViewerEX rotates the model plane around Unity's Y axis.
        angle = -math.radians(transform.get("rotate", 0))
        self.cosine, self.sine = math.cos(angle), math.sin(angle)

    def screen_point(self, x, y):
        x = (
            ((x - self.origin[0]) * self.model_scale + self.offset[0])
            * self.scale
            * self.mirror
        )
        y = (-(y - self.origin[1]) * self.model_scale + self.offset[1]) * self.scale
        return (
            self.center[0] + x * self.cosine - y * self.sine,
            self.center[1] - x * self.sine - y * self.cosine,
        )

    def region_at(self, point):
        if self.scale == 0 or self.model_scale == 0:
            return None
        x, y = point[0] - self.center[0], self.center[1] - point[1]
        x, y = (x * self.cosine + y * self.sine) * self.mirror / self.scale, (
            -x * self.sine + y * self.cosine
        ) / self.scale
        x = (x - self.offset[0]) / self.model_scale + self.origin[0]
        y = -(y - self.offset[1]) / self.model_scale + self.origin[1]
        for name in REGIONS:
            box = self.regions.get(name)
            if box and box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                return name
        return None


class MouseEvent(ctypes.Structure):
    _fields_ = [
        ("point", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extraInfo", ctypes.c_size_t),
    ]


class DesktopInput:
    def __init__(self, studio):
        self.studio = studio
        self.user32, self.kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self.projection = None
        self.press = None
        self.native_roots = set()
        self.last_anchor = None
        self.last_anchor_at = 0
        self.viewport = None
        self.updated_windows = 0
        self.model_key = None
        self.options = {}
        self.canvas = None
        self.active = False
        self.closed = False
        self.worker = None
        self.status = {"active": False, "capturedClicks": 0}
        self.commands = queue.Queue()
        self.configure_api()
        self.callback = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
        )(self.on_mouse)
        self.hook = self.user32.SetWindowsHookExW(
            14, self.callback, self.kernel32.GetModuleHandleW(None), 0
        )
        self.status["hookInstalled"] = bool(self.hook)
        if not self.hook:
            self.status["error"] = "Windows 鼠标拦截未能启动"
            return
        self.worker = threading.Thread(target=self.dispatch, daemon=True)
        self.worker.start()

    def configure_api(self):
        self.user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        )
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.CallNextHookEx.argtypes = (
            wintypes.HHOOK,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
        self.user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.GetTopWindow.argtypes = (wintypes.HWND,)
        self.user32.GetTopWindow.restype = wintypes.HWND
        self.user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user32.GetWindow.restype = wintypes.HWND
        self.user32.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
        self.user32.EnumChildWindows.argtypes = (wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM)
        self.user32.WindowFromPoint.argtypes = (wintypes.POINT,)
        self.user32.WindowFromPoint.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.user32.GetClientRect.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        )
        self.user32.ClientToScreen.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.POINT),
        )
        self.user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user32.IsIconic.argtypes = (wintypes.HWND,)
        self.user32.GetClassNameW.argtypes = (
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        )
        self.kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    def native_window(self, window):
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        process = self.kernel32.OpenProcess(0x1000, False, process_id.value)
        if not process:
            return False
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            return (
                bool(
                    self.kernel32.QueryFullProcessImageNameW(
                        process, 0, path, ctypes.byref(size)
                    )
                )
                and Path(path.value) == self.studio.native_executable
            )
        finally:
            self.kernel32.CloseHandle(process)

    def update_windows(self):
        native = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def inspect(window, _):
            name = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(window, name, 256)
            if (
                name.value == "UnityWndClass"
                and self.native_window(window)
                and self.user32.IsWindowVisible(window)
                and not self.user32.IsIconic(window)
            ):
                native.append(window)
            return True

        inspect_callback = callback_type(inspect)

        def visit(window, _):
            if self.user32.IsWindowVisible(window):
                inspect(window, 0)
                self.user32.EnumChildWindows(window, inspect_callback, 0)
            return True

        self.user32.EnumWindows(callback_type(visit), 0)
        self.native_roots = {self.user32.GetAncestor(window, 2) for window in native}
        self.status["nativeWindows"] = len(native)
        self.viewport = None
        for window in native:
            rectangle, origin = wintypes.RECT(), wintypes.POINT()
            if (
                self.user32.GetClientRect(window, ctypes.byref(rectangle))
                and self.user32.ClientToScreen(window, ctypes.byref(origin))
                and rectangle.right > 0
                and rectangle.bottom > 0
            ):
                self.viewport = (origin.x, origin.y, rectangle.right, rectangle.bottom)
                break

    def update(self, anchor):
        if self.closed:
            return anchor
        now = time.monotonic()
        if anchor:
            self.last_anchor, self.last_anchor_at = anchor, now
        elif self.studio.linked and now - self.last_anchor_at < 0.5:
            anchor = self.last_anchor
        if now - self.updated_windows > 0.5:
            self.update_windows()
            self.updated_windows = now
        self.active = bool(
            self.hook
            and anchor
            and self.viewport
            and self.studio.linked
            and self.studio.player.socket
            and self.studio.settings().get("preventClickThrough", True)
        )
        self.status["active"] = self.active
        if not self.active:
            self.projection = None
            return anchor
        costume = self.studio.costume()
        key = (self.studio.current, costume["id"])
        try:
            if key != self.model_key:
                model = json.loads(
                    (self.studio.root() / costume["file"]).read_text(encoding="utf-8-sig")
                )
                if not isinstance(model, dict):
                    raise ValueError("模型格式无效")
                self.options = model.get("Options", model.get("options", {}))
                if not isinstance(self.options, dict):
                    raise ValueError("模型参数无效")
                self.canvas = None
                if not costume.get("cubism3"):
                    self.canvas = struct.unpack(
                        ">ii", (self.studio.root() / model["model"]).read_bytes()[-12:-4]
                    )
                    if min(self.canvas) <= 0:
                        raise ValueError("模型画布无效")
            self.projection = HitProjection(
                costume["hitRegions"], anchor, self.options, self.viewport, self.canvas
            )
            self.model_key = key
        except (OSError, ValueError, KeyError, TypeError, struct.error):
            self.active = False
            self.status["active"] = False
            self.status["error"] = "触发区域读取失败"
            self.projection = None
            return anchor
        self.status.pop("error", None)
        self.projection_epoch = self.studio.input_epoch
        self.status["viewport"] = self.viewport
        return anchor

    def owns_point(self, point):
        window = self.user32.GetAncestor(
            self.user32.WindowFromPoint(wintypes.POINT(*point)), 2
        )
        if window in self.native_roots:
            return True
        candidate = self.user32.GetTopWindow(None)
        while candidate:
            if candidate == window:
                return False
            if candidate in self.native_roots and self.user32.IsWindowVisible(
                candidate
            ):
                return True
            candidate = self.user32.GetWindow(candidate, 2)
        return False

    def on_mouse(self, code, message, data):
        try:
            if code >= 0 and message in (0x200, 0x201, 0x202):
                point_struct = ctypes.cast(
                    data, ctypes.POINTER(MouseEvent)
                ).contents.point
                point = (point_struct.x, point_struct.y)
                if message == 0x201 and self.active and self.projection:
                    region = self.projection.region_at(point)
                    if region and self.owns_point(point):
                        self.press = {
                            "point": point,
                            "region": region,
                            "center": self.projection.center,
                            "epoch": self.projection_epoch,
                            "role": self.model_key[0],
                            "costume": self.model_key[1],
                            "drag": False,
                            "blocked": bool(
                                self.studio.popup and self.studio.popup.input_blocked
                            ),
                            "lastMove": 0,
                        }
                        return 1
                elif self.press and message in (0x200, 0x202):
                    press = self.press
                    dx, dy = point[0] - press["point"][0], point[1] - press["point"][1]
                    press["drag"] = press["drag"] or dx * dx + dy * dy > 36
                    now = time.monotonic()
                    if (
                        press["drag"]
                        and not press["blocked"]
                        and (message == 0x202 or now - press["lastMove"] >= 0.04)
                    ):
                        press["lastMove"] = now
                        self.commands.put(
                            (
                                "move",
                                press.copy(),
                                (press["center"][0] + dx, press["center"][1] + dy),
                            )
                        )
                    if message == 0x202:
                        self.press = None
                        if (
                            not press["drag"]
                            and not press["blocked"]
                            and self.active
                            and self.projection
                            and self.projection.region_at(point) == press["region"]
                        ):
                            self.commands.put(("tap", press, None))
                            self.status["capturedClicks"] += 1
                    if message == 0x202:
                        return 1
        except (OSError, ValueError, KeyError, TypeError):
            self.press = None
        return self.user32.CallNextHookEx(self.hook, code, message, data)

    def dispatch(self):
        while True:
            command = self.commands.get()
            if command is None:
                return
            kind, press, point = command
            with self.studio.lock:
                if (
                    self.closed
                    or not self.studio.linked
                    or press["role"] != self.studio.current
                    or press["epoch"] != self.studio.input_epoch
                    or press["costume"] != self.studio.settings()["costume"]
                ):
                    continue
                try:
                    if kind == "move":
                        if self.viewport is None or self.studio.slot_path() != self.studio.expected_path():
                            continue
                        left, top, width, height = self.viewport
                        self.studio.player.send(
                            13400,
                            {
                                "id": self.studio.slot,
                                "posX": round(point[0] - left - width / 2),
                                "posY": round(top + height / 2 - point[1]),
                            },
                        )
                    elif press["region"] == "menu":
                        self.studio.popup.show()
                    else:
                        region = press["region"]
                        kind = (
                            "costume"
                            if region == "wardrobe"
                            else (
                                "action"
                                if region in ("body", "left", "right")
                                else region
                            )
                        )
                        self.studio.operate(
                            kind, randomize=True, body=True, direction=region
                        )
                except (ValueError, ConnectionError, OSError) as error:
                    self.studio.emit("notice", str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.active = False
        self.status["active"] = False
        self.press = None
        self.projection = None
        if self.hook:
            self.user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        self.status["hookInstalled"] = False
        if self.worker is not None:
            self.commands.put(None)
            if self.worker is not threading.current_thread():
                self.worker.join(timeout=.5)
