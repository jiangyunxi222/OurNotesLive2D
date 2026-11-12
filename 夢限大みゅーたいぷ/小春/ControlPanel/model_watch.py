"""Start the bundled controller when ViewerEX loads one of our models."""

import ctypes
import hashlib
import json
from pathlib import Path
from functools import lru_cache
import subprocess
import sys
import time
import urllib.request


def command(panel):
    if getattr(sys, "frozen", False):
        return [str(panel / "ControlPanel.exe")]
    executable = Path(sys.executable).with_name("pythonw.exe")
    return [str(executable if executable.exists() else sys.executable), str(panel / "server.py")]


def launch(arguments, panel):
    return subprocess.Popen(arguments, cwd=panel, creationflags=subprocess.CREATE_NO_WINDOW)


def enable(panel):
    import winreg

    arguments = command(panel) + ["--watch-models"]
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        winreg.SetValueEx(key, "BandGDreamModels", 0, winreg.REG_SZ, subprocess.list2cmdline(arguments))
    launch(arguments, panel)


def acquire_instance(name):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.CreateMutexW(None, False, "Local\\" + name)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:
        kernel.CloseHandle(handle)
        return None
    return handle


@lru_cache(maxsize=128)
def controller_for(path):
    model = Path(path)
    panel = model.parent / "ControlPanel"
    if not panel.is_dir():
        panel = model.parent / "控制台"
    try:
        roles = json.loads((panel / "library.json").read_text("utf-8-sig"))
        role = roles[0]
        catalog = json.loads((panel / "data" / (role["id"] + ".json")).read_text("utf-8-sig"))
        files = {role["entry"], *(item["file"] for item in catalog["costumes"])}
        if len(roles) == 1 and model.name in files:
            return panel, role
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return None


def run(panel, native, read_native):
    mutex = acquire_instance("BandGDreamModelWatcher")
    if mutex is None:
        return
    executable = "ControlPanel.exe" if getattr(sys, "frozen", False) else "server.py"
    trusted = hashlib.sha256((panel / executable).read_bytes()).digest()
    retry_at = {}
    try:
        while True:
            slots = read_native(native / "save/autosave.dat").get("charDatas", [])
            for slot in slots:
                target = controller_for(slot.get("jsonFilePath") or "")
                if not target:
                    continue
                destination, role = target
                if time.monotonic() < retry_at.get(str(destination), 0):
                    continue
                retry_at[str(destination)] = time.monotonic() + 3
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{role['port']}/api/state", timeout=.5) as response:
                        state = json.load(response)
                    if state.get("role") == role["id"]:
                        continue
                except (OSError, ValueError):
                    pass
                try:
                    if hashlib.sha256((destination / executable).read_bytes()).digest() == trusted:
                        launch(command(destination) + ["--no-browser"], destination)
                except OSError:
                    pass
            time.sleep(.5)
    finally:
        kernel = ctypes.windll.kernel32
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel.CloseHandle(mutex)
