#!/usr/bin/env python3
"""
Hyperbridge - a local visual library for captured links and screenshots.

Part of the hyper ecosystem (Hypervisor, Hyperagent, HyperEye, Hyperbridge).

Usage:
    pythonw hyperbridge.py
"""

import base64
import json
import re
import shutil
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

import capture  # noqa: E402
import db  # noqa: E402
import library  # noqa: E402
import sets  # noqa: E402

_MIME = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
_MAX_PAGE = 200


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 prefix query (every word must match)."""
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    return " ".join(f'"{word}"*' for word in words)


def _thumb_uri(relative: str | None) -> str | None:
    """Return a data URI for a stored thumbnail, or None when it is missing."""
    if not relative:
        return None
    path = db.data_dir() / relative
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


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

    def list_entries(self, query: str = "", offset: int = 0, limit: int = 60, set_id: int | None = None) -> dict:
        """Return a page of entries, newest first, optionally filtered by a text query and a set."""
        offset = max(0, int(offset or 0))
        limit = min(_MAX_PAGE, max(1, int(limit or 60)))
        match = _fts_query(query or "")
        clauses, params = [], []
        if match:
            clauses.append("e.id IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?)")
            params.append(match)
        if set_id:
            clauses.append("e.id IN (SELECT entry_id FROM set_entries WHERE set_id = ?)")
            params.append(int(set_id))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        conn = db.connect()
        try:
            total = conn.execute(f"SELECT COUNT(*) FROM entries e {where}", params).fetchone()[0]
            rows = conn.execute(
                "SELECT e.id, e.title, e.domain, e.state, a.path AS thumb_path, a.width, a.height"
                f" FROM entries e LEFT JOIN assets a ON a.entry_id = e.id AND a.kind = 'thumbnail' AND a.position = 0"
                f" {where} ORDER BY e.created_at DESC, e.id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        finally:
            conn.close()
        entries = [
            {
                "id": row["id"], "title": row["title"], "domain": row["domain"], "state": row["state"],
                "thumb": _thumb_uri(row["thumb_path"]), "width": row["width"], "height": row["height"],
            }
            for row in rows
        ]
        return {"entries": entries, "total": total}

    def get_entry(self, entry_id: int) -> dict | None:
        """Return one entry's fields, assets, tags and sets for the lightbox."""
        return library.get_entry(int(entry_id))

    def get_asset(self, asset_id: int) -> str | None:
        """Return a stored asset image as a data URI."""
        return library.get_asset_uri(int(asset_id))

    def update_entry(self, entry_id: int, fields: dict) -> dict | None:
        """Save edited fields; edited fields are recorded as manual."""
        try:
            return library.update_entry(int(entry_id), fields if isinstance(fields, dict) else {})
        except Exception as err:
            logger.warning("update_entry failed: %s", err)
            return None

    def discard_entry(self, entry_id: int) -> bool:
        """Delete an entry and its files."""
        try:
            return library.discard_entry(int(entry_id))
        except Exception as err:
            logger.warning("discard_entry failed: %s", err)
            return False

    def list_sets(self) -> list:
        """Return every set with its entry count."""
        return sets.list_sets()

    def create_set(self, name: str) -> dict:
        """Create a set."""
        return sets.create_set(name)

    def rename_set(self, set_id: int, name: str) -> dict:
        """Rename a set."""
        return sets.rename_set(int(set_id), name)

    def delete_set(self, set_id: int) -> bool:
        """Delete a set; its entries stay in the library."""
        return sets.delete_set(int(set_id))

    def place_entry(self, entry_id: int, set_id: int) -> bool:
        """Place an entry in a set."""
        return sets.place(int(entry_id), int(set_id))

    def remove_entry(self, entry_id: int, set_id: int) -> bool:
        """Take an entry out of a set."""
        return sets.remove(int(entry_id), int(set_id))

    def save_asset(self, asset_id: int) -> str:
        """Ask where to save one asset and copy it there; returns saved, cancelled or failed."""
        found = library.asset_file(int(asset_id))
        if found is None:
            return "failed"
        source, name = found
        try:
            chosen = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG, save_filename=name
            )
            if not chosen:
                return "cancelled"
            dest = chosen if isinstance(chosen, str) else chosen[0]
            shutil.copyfile(source, dest)
            return "saved"
        except Exception as err:
            logger.warning("save_asset failed: %s", err)
            return "failed"

    def save_entry_assets(self, entry_id: int) -> dict:
        """Ask for a folder and copy every asset of an entry into it."""
        files = library.entry_files(int(entry_id))
        if not files:
            return {"status": "failed", "count": 0}
        try:
            chosen = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if not chosen:
                return {"status": "cancelled", "count": 0}
            folder = chosen if isinstance(chosen, str) else chosen[0]
            return {"status": "saved", "count": library.copy_files(files, folder)}
        except Exception as err:
            logger.warning("save_entry_assets failed: %s", err)
            return {"status": "failed", "count": 0}

    def add_link(self, url: str) -> dict:
        """Capture a link: create a pending entry and queue its capture job."""
        try:
            conn = db.connect()
            try:
                result = capture.add_link(conn, (url or "").strip())
            finally:
                conn.close()
        except ValueError:
            return {"ok": False, "error": "Not a web link."}
        except Exception as err:
            logger.warning("add_link failed: %s", err)
            return {"ok": False, "error": "Could not capture that link."}
        return {"ok": True, "entry_id": result["entry_id"], "already_captured": result["already_captured"]}


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
    capture.Worker().start()

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
