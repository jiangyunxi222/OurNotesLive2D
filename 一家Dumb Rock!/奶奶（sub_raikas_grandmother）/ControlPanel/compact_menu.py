"""A heading-free desktop menu owned by one character's control panel."""

import queue
import threading
import time
import tkinter as tk
import webbrowser
import ctypes
import sys
from pathlib import Path
from tkinter import font as tkfont


class CompactMenu:
    def __init__(self, studio, port):
        self.studio = studio
        self.port = port
        self.messages = queue.Queue()
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError):
                ctypes.windll.user32.SetProcessDPIAware()
            panel = self.studio.state_path.parent.parent
            font = panel / "web/fonts/BandoriLove-Menu.otf"
            if font.is_file():
                ctypes.windll.gdi32.AddFontResourceExW(str(font), 0x10, None)
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(studio.catalog()["name"] + " · 角色菜单")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.80)
        installed = {family.casefold(): family for family in tkfont.families(self.root)}
        self.menu_font = next(
            (
                installed[name.casefold()]
                for name in ("BandoriLove Rounded", "Microsoft YaHei UI", "Microsoft YaHei")
                if name.casefold() in installed
            ),
            "Microsoft YaHei UI",
        )
        self.rounded_size = None
        self.rounded_applied = False
        self.position = None
        self.status = {"visible": False}
        self.input_blocked = False
        self.last_input_heartbeat = 0
        self.input_release = None
        self.root.configure(
            background="#403b46", highlightbackground="#756976", highlightthickness=1
        )
        self.frame = tk.Frame(self.root, background="#403b46")
        self.frame.pack(padx=7, pady=7)
        self.buttons = {}
        entries = [
            ("panel", "打开面板", self.open_panel),
            ("action", "循环动作", lambda: self.toggle("action")),
            ("voice", "循环语音", lambda: self.toggle("voice")),
            ("costume", "循环换装", lambda: self.toggle("costume")),
            ("idle", "恢复待机", self.reset),
            ("close", "关闭菜单", self.hide),
        ]
        for key, label, callback in entries:
            button = tk.Button(
                self.frame,
                text=label,
                command=callback,
                width=19,
                font=(self.menu_font, 18, "bold"),
                foreground="#f7f0f6",
                background="#403b46",
                activeforeground="#ffffff",
                activebackground="#6d566b",
                borderwidth=0,
                relief="flat",
                cursor="hand2",
                pady=9,
                takefocus=True,
            )
            button.pack(fill="x", pady=1)
            self.buttons[key] = button
        self.error = tk.Label(
            self.frame,
            text="",
            wraplength=230,
            background="#403b46",
            foreground="#ffd6e2",
            font=("Microsoft YaHei UI", 10),
        )
        self.root.bind("<Escape>", lambda event: self.hide())
        self.root.bind("<Configure>", self.round_corners)
        if sys.platform == "win32":
            from desktop_input import DesktopInput

            self.studio.input_router = DesktopInput(studio)
            self.root.bind("<Destroy>", self.on_destroy)
        self.root.after(100, self.poll)

    def on_destroy(self, event):
        if event.widget is self.root and self.studio.input_router:
            self.studio.input_router.close()

    def show(self):
        with self.studio.lock:
            if not self.studio.linked:
                return
            self.input_blocked = True
            self.studio.native("carrier_hide_text#5")
            self.studio.native("web_block_input#8")
            request = (self.studio.current, self.studio.input_epoch)
        self.messages.put(("show", request))

    def hide(self):
        self.root.withdraw()
        if self.input_release is not None:
            self.root.after_cancel(self.input_release)
        # Keep the release of this click from reaching the avatar underneath.
        self.input_release = self.root.after(180, self.release_input)

    def release_input(self):
        self.input_release = None
        self.input_blocked = False

        def allow():
            if not self.input_blocked and not (
                self.studio.input_router and self.studio.input_router.active
            ):
                self.studio.native("web_allow_input#8")

        self.run_action(allow)

    def window_handle(self):
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        user32.GetAncestor.restype = ctypes.c_void_p
        return user32.GetAncestor(self.root.winfo_id(), 2)

    def round_corners(self, event=None):
        if sys.platform != "win32":
            return
        size = (self.root.winfo_width(), self.root.winfo_height())
        if (size == self.rounded_size and self.rounded_applied) or min(size) < 4:
            return
        self.rounded_size = size
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        user32.SetWindowRgn.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
        window = self.window_handle()
        region = gdi32.CreateRoundRectRgn(0, 0, size[0] + 1, size[1] + 1, 22, 22)
        self.rounded_applied = bool(user32.SetWindowRgn(window, region, True))
        if not self.rounded_applied:
            gdi32.DeleteObject(ctypes.c_void_p(region))

    def display(self, request=None):
        if request is not None and request != (self.studio.current, self.studio.input_epoch):
            self.hide()
            return
        anchor = self.studio.desktop_anchor() if self.studio.linked else None
        if anchor is None:
            self.hide()
            return
        if self.input_release is not None:
            self.root.after_cancel(self.input_release)
            self.input_release = None
        self.input_blocked = True
        self.error.pack_forget()
        self.refresh()
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.update_idletasks()
        self.round_corners()
        self.align_window(anchor)
        self.root.lift()
        self.root.focus_force()

    def run_action(self, callback):
        def perform():
            try:
                with self.studio.lock:
                    callback()
            except (ValueError, ConnectionError, OSError) as error:
                self.messages.put(("error", str(error)))

        threading.Thread(target=perform, daemon=True).start()

    def toggle(self, kind):
        def perform():
            if self.studio.looping[kind]:
                self.studio.stop(kind)
            else:
                self.studio.operate(kind, loop=True, randomize=True)

        self.run_action(perform)

    def reset(self):
        self.run_action(self.studio.reset)

    def open_panel(self):
        self.hide()
        with self.studio.lock:
            role = self.studio.current
            costume = self.studio.settings()["costume"]
            desktop = "&desktop=1" if self.studio.linked else ""
        webbrowser.open(
            f"http://127.0.0.1:{self.port}/?role={role}&costume={costume}{desktop}"
        )

    def refresh(self):
        if not self.studio.lock.acquire(blocking=False):
            return
        try:
            looping = self.studio.looping.copy()
            anchor = self.studio.desktop_anchor() if self.studio.linked else None
            if self.studio.input_router:
                self.studio.input_router.update(anchor)
            # The native lease expires on its own if this process exits.
            now = time.monotonic()
            owns_input = self.input_blocked or (
                self.studio.input_router and self.studio.input_router.active
            )
            if owns_input and now - self.last_input_heartbeat >= 0.3:
                self.studio.native("web_block_input#8")
                self.last_input_heartbeat = now
        finally:
            self.studio.lock.release()
        for kind, label in (("action", "动作"), ("voice", "语音"), ("costume", "换装")):
            self.buttons[kind].configure(
                text="停止" + label + "循环" if looping[kind] else "循环" + label,
                foreground="#ffd4e8" if looping[kind] else "#f7f0f6",
                background="#654d62" if looping[kind] else "#403b46",
            )
        self.align_window(anchor)

    def align_window(self, anchor=None):
        if self.root.state() == "withdrawn":
            return
        if not self.studio.linked:
            self.hide()
            return
        if anchor is None:
            anchor = self.studio.desktop_anchor()
        if anchor is None:
            self.hide()
            return
        left, top = 0, 0
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        popup_width, popup_height = (
            self.root.winfo_reqwidth(),
            self.root.winfo_reqheight(),
        )
        center_x = left + (0.5 + anchor["x"]) * width
        center_y = top + (0.5 - anchor["y"]) * height
        x = round(
            min(
                max(left + 8, center_x - popup_width / 2),
                left + width - popup_width - 8,
            )
        )
        y = round(
            min(
                max(top + 8, center_y - popup_height / 2),
                top + height - popup_height - 8,
            )
        )
        if self.position == (x, y):
            return
        self.position = (x, y)
        if sys.platform == "win32":
            window = self.window_handle()
            user32.SetWindowPos.argtypes = (
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            )
            user32.SetWindowPos(window, None, x, y, 0, 0, 0x15)
        else:
            self.root.geometry(f"{x:+d}{y:+d}")

    def poll(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "show":
                    self.display(value)
                elif kind == "panel":
                    self.open_panel()
                elif kind == "error":
                    self.error.configure(text=value)
                    self.error.pack(fill="x", padx=8, pady=(5, 4))
        except queue.Empty:
            pass
        self.refresh()
        self.status = {
            "visible": bool(self.root.winfo_viewable()),
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
            "width": self.root.winfo_width(),
            "height": self.root.winfo_height(),
            "font": self.menu_font,
            "opacity": float(self.root.attributes("-alpha")),
            "rounded": self.rounded_applied,
            "blocksBodyInput": self.input_blocked,
            "labels": [button.cget("text") for button in self.buttons.values()],
        }
        self.root.after(100, self.poll)

    def run(self):
        self.root.mainloop()
