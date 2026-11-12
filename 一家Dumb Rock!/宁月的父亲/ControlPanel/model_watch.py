"""Start the bundled controller when ViewerEX loads one of our models."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
from functools import lru_cache
import shutil
import subprocess
import sys
import time
import urllib.request


def command(panel):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--panel-dir", str(panel.resolve())]
    executable = Path(sys.executable).with_name("pythonw.exe")
    return [str(executable if executable.exists() else sys.executable),
            str(Path(__file__).with_name("server.py")), "--panel-dir", str(panel.resolve())]


def instance_id(panel):
    return hashlib.sha256(str(panel.resolve()).replace("\\", "/").casefold().encode()).hexdigest()[:24]


def endpoint_record(panel):
    try:
        record = json.loads((panel / ".local/endpoint.json").read_text("utf-8-sig"))
        port = record["port"]
        if record["instance"] != instance_id(panel) or type(port) is not int or not 1 <= port <= 65535:
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError):
        return None


def endpoint_for(panel):
    """Reuse a controller only when its live identity matches this directory."""
    record = endpoint_record(panel)
    if record is None:
        return None
    port = record["port"]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=.5) as response:
            state = json.load(response)
        return port if isinstance(state, dict) and state.get("instance") == instance_id(panel) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


@lru_cache(maxsize=128)
def model_files(path, modified, size):
    catalog = json.loads(Path(path).read_text("utf-8-sig"))
    return {item["file"] for item in catalog["costumes"]}


def launch(arguments, panel):
    return subprocess.Popen(arguments, cwd=panel, creationflags=subprocess.CREATE_NO_WINDOW)


def enable(panel):
    import winreg

    arguments = command(panel) + ["--watch-models"]
    if getattr(sys, "frozen", False):
        source = Path(sys.executable)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "BandoriLove/Runtime"
        directory.mkdir(parents=True, exist_ok=True)
        runtime = directory / ("ControlPanel-" + digest[:16] + ".exe")
        if not runtime.exists() or hashlib.sha256(runtime.read_bytes()).hexdigest() != digest:
            temporary = directory / (str(os.getpid()) + ".new")
            try:
                shutil.copy2(source, temporary)
                try:
                    os.replace(temporary, runtime)
                except PermissionError:
                    if not runtime.exists() or hashlib.sha256(runtime.read_bytes()).hexdigest() != digest:
                        raise
            finally:
                temporary.unlink(missing_ok=True)
        marker = directory / (str(os.getpid()) + ".json.tmp")
        marker.write_text(json.dumps({"executable": runtime.name}), encoding="utf-8")
        os.replace(marker, directory / "current.json")
        arguments = [str(runtime), "--watch-models"]
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


def controller_for(path):
    model = Path(path)
    panel = model.parent / "ControlPanel"
    if not panel.is_dir():
        panel = model.parent / "控制台"
    try:
        roles = json.loads((panel / "library.json").read_text("utf-8-sig"))
        role = roles[0]
        catalog = panel / "data" / (role["id"] + ".json")
        info = catalog.stat()
        files = {role["entry"], *model_files(str(catalog), info.st_mtime_ns, info.st_size)}
        if len(roles) == 1 and model.name in files:
            return panel, role
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    return None


def run(panel, native, read_native):
    mutex = acquire_instance("BandGDreamModelWatcher")
    if mutex is None and getattr(sys, "frozen", False):
        for attempt in range(20):
            time.sleep(.1)
            mutex = acquire_instance("BandGDreamModelWatcher")
            if mutex is not None:
                break
    if mutex is None:
        return
    retry_at = {}
    try:
        while True:
            marker = Path(sys.executable).parent / "current.json"
            if getattr(sys, "frozen", False) and marker.exists():
                try:
                    current_runtime = json.loads(marker.read_text("utf-8"))["executable"]
                    if isinstance(current_runtime, str) and current_runtime and current_runtime != Path(sys.executable).name:
                        return
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            data = read_native(native / "save/autosave.dat")
            slots = data.get("charDatas", []) if isinstance(data, dict) else []
            if not isinstance(slots, list):
                slots = []
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                target = controller_for(slot.get("jsonFilePath") or "")
                if not target:
                    continue
                destination, _ = target
                if time.monotonic() < retry_at.get(str(destination), 0):
                    continue
                retry_at[str(destination)] = time.monotonic() + 3
                if endpoint_for(destination) is not None:
                    continue
                try:
                    # Use the running runtime with the loaded copy's own data.
                    launch(command(destination) + ["--no-browser"], destination)
                except OSError:
                    pass
            time.sleep(.5)
    finally:
        kernel = ctypes.windll.kernel32
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel.CloseHandle(mutex)
