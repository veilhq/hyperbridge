#!/usr/bin/env python3
"""
Hyperbridge - a local visual library for captured links and screenshots.

Part of the hyper ecosystem (Hypervisor, Hyperagent, HyperEye, Hyperbridge).

Usage:
    pythonw hyperbridge.py
"""

import json
import sys
import threading
import time
from pathlib import Path

import webview

# Paths
APP_DIR = Path(__file__).parent.resolve()
HYPERSPACE_ROOT = APP_DIR.parent
HYPERVISOR_DIR = HYPERSPACE_ROOT / ".hypervisor"
ICON_FILE = APP_DIR / "assets" / "hyperbridge.ico"
WINDOW_TITLE = "Hyperbridge"

sys.path.insert(0, str(HYPERSPACE_ROOT / ".hyperkit" / "python"))
from hyper_logging import setup_logger  # noqa: E402

logger = setup_logger("hyperbridge")

# Auto-build: regenerate generated_html.py from current source before import
from launch_build import build_or_warn, with_notice  # noqa: E402

_build_notice = build_or_warn(APP_DIR, "Hyperbridge")
from generated_html import HTML  # noqa: E402

HTML = with_notice(HTML, _build_notice)

import db  # noqa: E402


class HyperbridgeAPI:
    """PyWebView JS bridge for Hyperbridge."""

    def get_accent(self) -> dict:
        """Read the accent from Hypervisor's preferences.json."""
        prefs_file = HYPERVISOR_DIR / "preferences.json"
        try:
            data = json.loads(prefs_file.read_text(encoding="utf-8"))
            accent = data.get("hypervisor-accent", "#00ff41")
        except Exception:
            accent = "#00ff41"
        return {"accent": accent, "warm": "#ffb000", "cool": "#00cccc", "comp": "#ff3333"}

    def get_stats(self) -> dict:
        """Return library totals; a fresh connection per call keeps threads independent."""
        conn = db.connect()
        try:
            entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        finally:
            conn.close()
        return {"entries": entries}


def _apply_window_chrome(title: str):
    """Force a dark title bar and set the icon via the Windows DWM API."""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            return
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val)
        )
        if ICON_FILE.exists():
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            WM_SETICON = 0x0080
            hicon = ctypes.windll.user32.LoadImageW(0, str(ICON_FILE), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon)
    except Exception:
        pass


def _start_theme_watcher(window, api):
    """Poll Hypervisor's preferences.json and re-sync the accent when it changes."""
    prefs_file = HYPERVISOR_DIR / "preferences.json"
    last_mtime = prefs_file.stat().st_mtime if prefs_file.exists() else 0

    def _watch():
        nonlocal last_mtime
        while True:
            time.sleep(2)
            try:
                if not prefs_file.exists():
                    continue
                mtime = prefs_file.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    payload = (
                        json.dumps(api.get_accent())
                        .replace("\\", "\\\\")
                        .replace("`", "\`")
                        .replace("${", "\${")
                    )
                    window.evaluate_js(
                        f"if(window.applyAccent)window.applyAccent(JSON.parse(`{payload}`))"
                    )
            except Exception:
                pass

    threading.Thread(target=_watch, daemon=True).start()


def main():
    logger.info("hyperbridge starting")
    db.init_library().close()

    api = HyperbridgeAPI()
    icon_path = str(ICON_FILE) if ICON_FILE.exists() else None

    window = webview.create_window(
        WINDOW_TITLE,
        html=HTML,
        js_api=api,
        width=1200,
        height=800,
        min_size=(720, 480),
        background_color="#000000",
    )

    def on_start():
        time.sleep(0.5)
        _apply_window_chrome(WINDOW_TITLE)
        _start_theme_watcher(window, api)
        logger.info("hyperbridge ready")

    webview.start(on_start, icon=icon_path, debug=False)
    logger.info("hyperbridge shutdown")


if __name__ == "__main__":
    main()
