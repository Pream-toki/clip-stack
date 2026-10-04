"""Tray clipboard stack. Last 15 text copies, click to put one back."""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
STARTUP_NAME = "ClipStack.vbs"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]

stop_event = threading.Event()
lock = threading.Lock()
stack: list[str] = []
last_seen = ""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text('{"enabled": true, "max_items": 15}\n', encoding="utf-8")
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": True, "max_items": 15}


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def startup_path() -> Path:
    return (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft/Windows/Start Menu/Programs/Startup"
        / STARTUP_NAME
    )


def set_startup(icon, want: bool) -> None:
    p = startup_path()
    script = Path(__file__).resolve()
    try:
        if want:
            p.write_text(
                'Set sh = CreateObject("WScript.Shell")\n'
                f'sh.CurrentDirectory = "{script.parent}"\n'
                f'sh.Run "pythonw ""{script}""", 0, False\n',
                encoding="ascii",
            )
        elif p.exists():
            p.unlink()
        cfg = load_config()
        cfg["start_with_windows"] = want
        save_config(cfg)
        icon.update_menu()
    except OSError:
        pass


def get_clip() -> str:
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clip(text: str) -> None:
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


def worker() -> None:
    global last_seen
    while not stop_event.is_set():
        cfg = load_config()
        if cfg.get("enabled", True):
            try:
                text = get_clip()
            except Exception:
                text = ""
            if text and text != last_seen:
                last_seen = text
                with lock:
                    if text not in stack:
                        stack.insert(0, text)
                    cap = max(5, int(cfg.get("max_items") or 15))
                    del stack[cap:]
        stop_event.wait(0.8)


def pick(text: str):
    def _go(icon, item):
        global last_seen
        last_seen = text
        set_clip(text)

    return _go


def label(text: str) -> str:
    one = " ".join(text.split())
    if len(one) > 42:
        one = one[:40] + "…"
    return one or "(empty)"


def menu(icon):
    cfg = load_config()
    en = bool(cfg.get("enabled", True))
    items = [
        pystray.MenuItem("Clip stack", None, enabled=False),
        pystray.MenuItem("ON", lambda i, _: toggle(i, True), checked=lambda _: en, radio=True),
        pystray.MenuItem("OFF", lambda i, _: toggle(i, False), checked=lambda _: not en, radio=True),
        pystray.MenuItem(
            "Start with Windows",
            lambda i, _: set_startup(i, not startup_path().exists()),
            checked=lambda _: startup_path().exists(),
        ),
        pystray.Menu.SEPARATOR,
    ]
    with lock:
        clips = list(stack[:12])
    if not clips:
        items.append(pystray.MenuItem("(copy something)", None, enabled=False))
    else:
        for t in clips:
            items.append(pystray.MenuItem(label(t), pick(t)))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Clear", lambda i, _: clear()))
    items.append(pystray.MenuItem("Quit", quit_app))
    return pystray.Menu(*items)


def toggle(icon, on: bool) -> None:
    cfg = load_config()
    cfg["enabled"] = on
    save_config(cfg)
    try:
        icon.update_menu()
    except Exception:
        pass


def clear() -> None:
    with lock:
        stack.clear()


def quit_app(icon, _item=None) -> None:
    stop_event.set()
    icon.stop()


def icon_img():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 8, 52, 56), 8, fill=(90, 80, 50, 255))
    d.rectangle((20, 18, 44, 22), fill="white")
    d.rectangle((20, 28, 44, 32), fill="white")
    d.rectangle((20, 38, 36, 42), fill="white")
    return img


def main() -> None:
    load_config()
    threading.Thread(target=worker, daemon=True).start()
    icon = pystray.Icon("ClipStack", icon_img(), "Clip stack", menu=pystray.Menu(lambda: menu(icon)))
    icon.run()


if __name__ == "__main__":
    main()
