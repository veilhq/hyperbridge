#!/usr/bin/env python3
"""
Hyperbridge - a local visual library for captured links and screenshots.

Part of the hyper ecosystem (Hypervisor, Hyperagent, HyperEye, Hyperbridge).

Usage:
    pythonw hyperbridge.py
"""

import base64
import json
import random
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
APP_USER_MODEL_ID = "Hyper.Hyperbridge"
WINDOW_TITLE = "Hyperbridge"

sys.path.insert(0, str(HYPERSPACE_ROOT / ".hyperkit" / "python"))
from hyper_logging import setup_logger  # noqa: E402
from palette import GRADIENT_MAPS, build_palette_oklch  # noqa: E402

logger = setup_logger("hyperbridge")

# Auto-build: regenerate generated_html.py from current source before import
from launch_build import build_or_warn, with_notice  # noqa: E402

_build_notice = build_or_warn(APP_DIR, "Hyperbridge")
from generated_html import HTML  # noqa: E402

HTML = with_notice(HTML, _build_notice)

import arena  # noqa: E402
import capture  # noqa: E402
import discover  # noqa: E402
import feed  # noqa: E402
import feed_sources  # noqa: E402
import db  # noqa: E402
import library  # noqa: E402
import screenshot  # noqa: E402
import sets  # noqa: E402
import social  # noqa: E402
import swatches  # noqa: E402
import sync  # noqa: E402
import lan  # noqa: E402
import transfer  # noqa: E402
import tumblr  # noqa: E402

_MIME = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
_MAX_PAGE = 200
_MAX_BULK = 1000


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 prefix query (every word must match)."""
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    return " ".join(f'"{word}"*' for word in words)


_GROUPS = ("color", "year", "source")
_ORDERS = {
    "oldest": "e.created_at ASC, e.id ASC",
    "title": "(e.title = '') ASC, lower(e.title) ASC, e.id DESC",
    "source": "lower(e.domain) ASC, e.created_at DESC, e.id DESC",
}


def _entry_year(row) -> str:
    """Return the entry's year field, else the year it was captured."""
    match = re.search(r"\d{4}", row["year"] or "")
    return match.group(0) if match else (row["created_at"] or "")[:4]


def _group_label(row, group: str) -> str:
    """Return the section label an entry falls under for a grouping."""
    if group == "color":
        return swatches.entry_family(row["swatches"])
    if group == "year":
        return _entry_year(row) or "No year"
    return row["domain"] or "No source"


def _group_rank(labels: list, group: str) -> dict:
    """Map each label to its sort position: color by hue order, year newest first, source by size."""
    unique = sorted(set(labels))
    if group == "color":
        order = [*swatches.FAMILIES, swatches.NO_COLOR]
        return {label: order.index(label) if label in order else len(order) for label in unique}
    if group == "year":
        ranked = sorted(unique, key=lambda label: (not label.isdigit(), -int(label) if label.isdigit() else 0, label))
    else:
        ranked = sorted(unique, key=lambda label: (-labels.count(label), label.lower()))
    return {label: index for index, label in enumerate(ranked)}


GIF_GRID_BYTES = 1024 * 1024


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


def _grid_path(row) -> str | None:
    """Pick the file a grid card shows: a small GIF keeps its original so it animates, else the thumbnail."""
    original = row["original_path"]
    if original and original.lower().endswith(".gif") and (row["original_bytes"] or 0) <= GIF_GRID_BYTES:
        return original
    return row["thumb_path"]


class HyperbridgeAPI:
    """PyWebView JS bridge for Hyperbridge."""

    def get_accent(self) -> dict:
        """Return the palette derived from Hypervisor's accent, preset, and palette mode."""
        prefs_file = HYPERVISOR_DIR / "preferences.json"
        try:
            data = json.loads(prefs_file.read_text(encoding="utf-8"))
            gradient_map = data.get("hypervisor-gradient-map", "")
            if data.get("hypervisor-theme-mode", "custom") == "preset" and gradient_map:
                preset = GRADIENT_MAPS.get(gradient_map) or data.get("userGradientMaps", {}).get(gradient_map)
                if preset:
                    return {key: preset[key] for key in ("accent", "warm", "cool", "comp")}
            accent = data.get("hypervisor-accent", "#00ff41")
            mode = data.get("hypervisor-palette-mode", "split")
            return build_palette_oklch(accent, mode)
        except Exception:
            return build_palette_oklch("#00ff41", "split")

    def get_stats(self) -> dict:
        """Return library totals; a fresh connection per call keeps threads independent."""
        conn = db.connect()
        try:
            entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        finally:
            conn.close()
        return {"entries": entries}

    def list_entries(self, query: str = "", offset: int = 0, limit: int = 60, set_id: int | None = None,
                     group: str = "", tag: str = "", color: str = "", order: str = "") -> dict:
        """Return a page of entries, newest first unless order is oldest, title or source; filtered by text, set, tag and color, and optionally grouped."""
        offset = max(0, int(offset or 0))
        limit = min(_MAX_PAGE, max(1, int(limit or 60)))
        group = group if group in _GROUPS else ""
        match = _fts_query(query or "")
        clauses, params = [], []
        if match:
            clauses.append("e.id IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?)")
            params.append(match)
        if set_id:
            clauses.append("e.id IN (SELECT entry_id FROM set_entries WHERE set_id = ?)")
            params.append(int(set_id))
        if tag:
            clauses.append(
                "e.id IN (SELECT et.entry_id FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE t.name = ?)"
            )
            params.append(str(tag))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT e.id, e.title, e.domain, e.state, e.year, e.creator, e.publisher, e.type, e.created_at, e.swatches,"
                " a.path AS thumb_path, a.width, a.height, o.path AS original_path, o.bytes AS original_bytes"
                " FROM entries e LEFT JOIN assets a ON a.entry_id = e.id AND a.kind = 'thumbnail' AND a.position = 0"
                " LEFT JOIN assets o ON o.entry_id = e.id AND o.kind = 'original' AND o.position = 0"
                f" {where} ORDER BY {_ORDERS.get(order, 'e.created_at DESC, e.id DESC')}",
                params,
            ).fetchall()
        finally:
            conn.close()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color or ""):
            rows = [row for row in rows if swatches.near(row["swatches"], color)]
        if order == "color":
            rows = sorted(rows, key=lambda row: swatches.gradient_key(row["swatches"]))
        labels = [_group_label(row, group) for row in rows] if group else [""] * len(rows)
        order = list(range(len(rows)))
        if group:
            rank = _group_rank(labels, group)
            order.sort(key=lambda index: (rank[labels[index]], index))
        years = [year for year in (_entry_year(row) for row in rows) if year]
        entries = [
            {
                "id": rows[i]["id"], "title": rows[i]["title"], "domain": rows[i]["domain"],
                "state": rows[i]["state"], "thumb": _thumb_uri(_grid_path(rows[i])),
                "width": rows[i]["width"], "height": rows[i]["height"], "group": labels[i],
                "caption": [rows[i][name] for name in ("creator", "publisher", "type", "year") if rows[i][name]],
            }
            for i in order[offset:offset + limit]
        ]
        return {
            "entries": entries, "total": len(rows),
            "years": [min(years), max(years)] if years else [],
        }

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

    def discover_images(self, url: str) -> dict:
        """List the usable images on a pasted page for adding to a set."""
        try:
            conn = db.connect()
            try:
                result = discover.discover(conn, (url or "").strip())
            finally:
                conn.close()
        except ValueError:
            return {"ok": False, "error": "Not a web link."}
        except Exception as err:
            logger.warning("discover_images failed: %s", err)
            return {"ok": False, "error": "Could not read that page."}
        return {"ok": True, **result}

    def add_discovered(self, urls: list, page_url: str, set_id: int | None = None) -> dict:
        """Capture the chosen image URLs, crediting the page, and place them in a set."""
        try:
            conn = db.connect()
            try:
                result = discover.add_candidates(conn, list(urls or [])[:_MAX_BULK], str(page_url or ""), set_id)
            finally:
                conn.close()
        except Exception as err:
            logger.warning("add_discovered failed: %s", err)
            return {"ok": False, "error": "Could not add those images."}
        return {"ok": True, **result}

    def list_feed_sources(self) -> list:
        """Return the outside services Hyperbridge can or cannot follow."""
        return feed_sources.list_sources()

    def _feed_call(self, name, action, fallback):
        """Run a feed action on its own connection, returning the fallback on failure."""
        try:
            conn = db.connect()
            try:
                return action(conn)
            finally:
                conn.close()
        except Exception as err:
            logger.warning("%s failed: %s", name, err)
            return fallback

    def refresh_feed(self, replace: bool = False) -> dict:
        """Pull new images from the followed sources into the discovery feed, replacing the unseen ones when asked."""
        result = self._feed_call("refresh_feed", lambda conn: feed.refresh(conn, replace=bool(replace)), None)
        return {"ok": False, "error": "Could not refresh the feed."} if result is None else {"ok": True, **result}

    def list_feed(self, offset: int = 0, limit: int = 60) -> dict:
        """Return unseen discovery feed items and whether a refresh is due."""
        return self._feed_call("list_feed", lambda conn: feed.list_items(conn, offset, limit),
                               {"items": [], "total": 0, "stale": False})

    def dismiss_feed(self, ids: list) -> int:
        """Hide feed items the Operator does not want."""
        return self._feed_call("dismiss_feed", lambda conn: feed.dismiss(conn, list(ids or [])[:_MAX_BULK]), 0)

    def accept_feed(self, ids: list, set_id: int | None = None) -> dict:
        """Save the chosen feed items to the library and optionally place them in a set."""
        result = self._feed_call("accept_feed", lambda conn: feed.accept(conn, list(ids or [])[:_MAX_BULK], set_id), None)
        return {"ok": False, "error": "Could not save those images."} if result is None else {"ok": True, **result}

    def list_followed(self) -> list:
        """Return the Are.na channels and users followed for the discovery feed."""
        return self._feed_call("list_followed", arena.list_followed, [])

    def follow_source(self, url: str) -> dict:
        """Follow an Are.na channel or user link, or a Tumblr blog, for the discovery feed."""
        try:
            conn = db.connect()
            try:
                return {"ok": True, "item": (arena.follow if arena.target(str(url or "").strip()) else tumblr.follow)(conn, str(url or ""), capture.default_fetcher())}
            finally:
                conn.close()
        except ValueError as err:
            return {"ok": False, "error": str(err)}
        except Exception as err:
            logger.warning("follow_source failed: %s", err)
            return {"ok": False, "error": "Could not follow that link."}

    def unfollow_source(self, source_id: int) -> bool:
        """Stop following a source."""
        return self._feed_call("unfollow_source", lambda conn: arena.unfollow(conn, source_id), False)

    def toggle_fullscreen(self) -> bool:
        """Switch the window between fullscreen and windowed; returns whether it is now fullscreen."""
        try:
            webview.windows[0].toggle_fullscreen()
            return True
        except Exception as err:
            logger.warning("toggle_fullscreen failed: %s", err)
            return False

    def list_tags(self) -> list:
        """Return every tag with its entry count."""
        return library.list_tags()

    def add_tags(self, entry_ids: list, tags) -> int:
        """Add tags to the given entries and return how many entries were tagged."""
        try:
            return library.add_tags(list(entry_ids or [])[:_MAX_BULK], tags)
        except Exception as err:
            logger.warning("add_tags failed: %s", err)
            return 0

    def list_sets(self) -> list:
        """Return every set with its entry count."""
        return sets.list_sets()

    def create_set(self, name: str, description: str = "") -> dict:
        """Create a set."""
        return sets.create_set(name, description)

    def rename_set(self, set_id: int, name: str, description: str | None = None) -> dict:
        """Rename a set and optionally replace its description."""
        return sets.rename_set(int(set_id), name, description)

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

    def save_entries_assets(self, entry_ids: list) -> dict:
        """Ask for a folder and copy every asset of the given entries into it."""
        try:
            files = library.entries_files(entry_ids or [])
            if not files:
                return {"status": "failed", "count": 0}
            chosen = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if not chosen:
                return {"status": "cancelled", "count": 0}
            folder = chosen if isinstance(chosen, str) else chosen[0]
            return {"status": "saved", "count": library.copy_files(files, folder)}
        except Exception as err:
            logger.warning("save_entries_assets failed: %s", err)
            return {"status": "failed", "count": 0}

    def export_library(self) -> dict:
        """Ask where to save and write the whole library as one zip; returns status and counts."""
        try:
            name = f"hyperbridge-library-{time.strftime('%Y%m%d')}.zip"
            chosen = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG, save_filename=name, file_types=("Hyperbridge library (*.zip)",)
            )
            if not chosen:
                return {"status": "cancelled"}
            dest = chosen if isinstance(chosen, str) else chosen[0]
            conn = db.connect()
            try:
                return {"status": "saved", **transfer.export_library(conn, dest)}
            finally:
                conn.close()
        except Exception as err:
            logger.warning("export_library failed: %s", err)
            return {"status": "failed", "error": "Could not export the library."}

    def import_library(self) -> dict:
        """Ask for a library zip and merge it in; entries already present are skipped."""
        try:
            chosen = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG, file_types=("Hyperbridge library (*.zip)",)
            )
            if not chosen:
                return {"status": "cancelled"}
            source = chosen if isinstance(chosen, str) else chosen[0]
            conn = db.connect()
            try:
                return {"status": "imported", **transfer.import_library(conn, source)}
            finally:
                conn.close()
        except transfer.TransferError as err:
            return {"status": "failed", "error": str(err)}
        except Exception as err:
            logger.warning("import_library failed: %s", err)
            return {"status": "failed", "error": "Could not import that library."}

    def start_share(self) -> dict:
        """Open a short-lived read-only share on the local network; returns its address, code and lifetime."""
        try:
            current = getattr(self, "_share", None)
            if current is not None:
                current.stop()
            self._share = lan.Share()
            return {"status": "sharing", "address": self._share.address, "addresses": self._share.addresses,
                    "code": self._share.code,
                    "seconds": lan.SHARE_SECONDS}
        except Exception as err:
            logger.warning("start_share failed: %s", err)
            return {"status": "failed", "error": "Could not start sharing."}

    def stop_share(self) -> dict:
        """Close the share if one is open."""
        current = getattr(self, "_share", None)
        if current is not None:
            current.stop()
            self._share = None
        return {"status": "stopped"}

    def fetch_from_share(self, address: str, code: str) -> dict:
        """Fetch the entries this library lacks from another machine that is sharing."""
        try:
            conn = db.connect()
            try:
                return {"status": "imported", **lan.fetch(conn, address, code)}
            finally:
                conn.close()
        except (lan.LanError, transfer.TransferError) as err:
            return {"status": "failed", "error": str(err)}
        except Exception as err:
            logger.warning("fetch_from_share failed: %s", err)
            return {"status": "failed", "error": "Could not fetch from that machine."}

    def _sync(self):
        machines = getattr(self, "sync", None)
        if machines is None:
            raise lan.LanError("Sync is not running.")
        return machines

    def sync_status(self) -> dict:
        """This machine, its pairing window and the machines found on the network."""
        try:
            return {"status": "ok", **self._sync().status()}
        except Exception as err:
            logger.warning("sync_status failed: %s", err)
            return {"status": "failed", "error": "Sync is not available."}

    def start_pairing(self) -> dict:
        """Open a pairing window and return its code."""
        try:
            return {"status": "ok", **self._sync().start_pairing()}
        except Exception as err:
            logger.warning("start_pairing failed: %s", err)
            return {"status": "failed", "error": "Could not open pairing."}

    def stop_pairing(self) -> dict:
        """Close the pairing window."""
        try:
            self._sync().stop_pairing()
            return {"status": "ok"}
        except Exception as err:
            logger.warning("stop_pairing failed: %s", err)
            return {"status": "failed", "error": "Could not close pairing."}

    def pair_with(self, machine_id: str, code: str) -> dict:
        """Pair with a machine that is showing a pairing code."""
        try:
            return {"status": "ok", **self._sync().pair(str(machine_id), code)}
        except lan.LanError as err:
            return {"status": "failed", "error": str(err)}
        except Exception as err:
            logger.warning("pair_with failed: %s", err)
            return {"status": "failed", "error": "Could not pair with that machine."}

    def sync_with(self, machine_id: str) -> dict:
        """Pull a paired machine's new entries and ask it to pull ours."""
        try:
            return {"status": "ok", **self._sync().sync_with(str(machine_id))}
        except (lan.LanError, transfer.TransferError) as err:
            return {"status": "failed", "error": str(err)}
        except Exception as err:
            logger.warning("sync_with failed: %s", err)
            return {"status": "failed", "error": "Could not sync with that machine."}

    def unpair(self, machine_id: str) -> dict:
        """Forget a paired machine on this side."""
        try:
            self._sync().store.remove(str(machine_id))
            return {"status": "ok"}
        except Exception as err:
            logger.warning("unpair failed: %s", err)
            return {"status": "failed", "error": "Could not unpair."}

    def add_image_data(self, data: str, name: str = "") -> dict:
        """Create an entry from a pasted image sent as base64 text."""
        try:
            body = base64.b64decode(str(data or "").split(",", 1)[-1], validate=False)
            return self._store_image_bytes(body, name)
        except Exception as err:
            logger.warning("add_image_data failed: %s", err)
            return {"ok": False, "error": "Could not add that image."}

    def _store_image_bytes(self, body: bytes, name: str) -> dict:
        if len(body) > capture.MAX_FILE_BYTES:
            return {"ok": False, "error": "That image is too large."}
        conn = db.connect()
        try:
            result = capture.add_image(conn, body, name)
        except capture.CaptureError:
            return {"ok": False, "error": "That is not a usable image."}
        finally:
            conn.close()
        return {"ok": True, "entry_id": result["entry_id"]}

    def add_image_paths(self, paths: list) -> dict:
        """Create an entry for each image file path; non-images are skipped and counted."""
        added = skipped = 0
        conn = db.connect()
        try:
            for path in paths or []:
                try:
                    capture.add_image_file(conn, path)
                    added += 1
                except Exception as err:  # noqa: BLE001 - one bad file does not stop the batch
                    logger.info("image drop skipped: %s", err)
                    skipped += 1
        finally:
            conn.close()
        return {"ok": added > 0, "added": added, "skipped": skipped}

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


def _backfill_swatches():
    """Fill swatches for entries captured before palettes were stored."""
    conn = db.connect()
    try:
        capture.fix_image_types(conn)
        capture.fix_domains(conn)
        capture.fix_file_name_titles(conn)
        swatches.backfill(conn)
    except Exception:  # noqa: BLE001 - a failed backfill only leaves entries ungrouped
        logger.exception("swatch backfill failed")
    finally:
        conn.close()


def _backfill_origins():
    """Fill source details (Are.na blocks, Tumblr post tags and dates) for saved images that lack them."""
    time.sleep(5)
    conn = db.connect()
    try:
        for name, step in (("arena", lambda: arena.backfill_origins(
                conn, capture.default_fetcher(), random.Random(), max_channels=None, retries=arena.RETRIES)),
                           ("tumblr", lambda: tumblr.backfill(conn, capture.default_fetcher())),
                           ("social", lambda: social.backfill(conn, capture.default_fetcher()))):
            try:
                step()
            except Exception:  # noqa: BLE001 - a failed backfill is retried at the next start
                logger.exception("%s backfill failed", name)
    finally:
        conn.close()


def _watch_drops(window, api):
    """Turn files dropped on the window into entries and tell the page how many landed."""
    from webview.dom import DOMEventHandler

    def on_drop(event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [item.get("pywebviewFullPath") for item in files if item.get("pywebviewFullPath")]
        if not paths:
            return
        result = api.add_image_paths(paths)
        window.evaluate_js(
            "document.dispatchEvent(new CustomEvent('hyperbridge:dropped', {detail: %s}))" % json.dumps(result)
        )

    window.dom.document.events.dragover += DOMEventHandler(lambda event: None, True, True)
    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)


def main():
    logger.info("hyperbridge starting")
    try:
        import ctypes

        # A distinct taskbar identity so the pinned shortcut and the running window share one icon.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001 - cosmetic; the app runs without it
        logger.warning("could not set the taskbar identity")
    conn = db.init_library()
    conn.close()
    capture.Worker(screenshotter=screenshot.capture_page).start()
    threading.Thread(target=_backfill_swatches, daemon=True).start()
    threading.Thread(target=_backfill_origins, daemon=True).start()

    api = HyperbridgeAPI()
    try:
        api.sync = sync.Sync()
    except Exception:  # noqa: BLE001 - the library works without sync
        logger.exception("sync failed to start")
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
        try:
            _watch_drops(window, api)
        except Exception:  # noqa: BLE001 - paste and link capture still work without drop support
            logger.exception("drop handler failed to register")
        logger.info("hyperbridge ready")

    webview.start(on_start, icon=icon_path, debug=False)
    if getattr(api, "sync", None):
        api.sync.stop()
    logger.info("hyperbridge shutdown")


if __name__ == "__main__":
    main()
