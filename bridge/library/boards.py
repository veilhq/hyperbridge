"""Scratch boards: freeform canvases kept on this machine, each stored as one JSON Canvas document.

Image nodes are JSON Canvas file nodes that carry the library entry id in an "entry" field. Boards never
sync; promoting a board turns its images into an ordinary set and deletes the board.
"""

import json
from datetime import datetime

from bridge.core import db
from bridge.library import sets

MAX_NAME = 100
MAX_DOC_BYTES = 4 * 1024 * 1024
ADD_WIDTH = 240
ADD_GAP = 24
ADD_PER_ROW = 6


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def _parse(doc) -> dict | None:
    """Return a board document as a dict with node and edge lists, or None when it is not one."""
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except ValueError:
            return None
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes", []), list) or not isinstance(doc.get("edges", []), list):
        return None
    doc = dict(doc)
    doc["nodes"] = [node for node in doc.get("nodes", []) if isinstance(node, dict)]
    doc["edges"] = [edge for edge in doc.get("edges", []) if isinstance(edge, dict)]
    return doc


def entry_ids(doc) -> list[int]:
    """Return the library entry ids a board's image nodes point at, in document order, without repeats."""
    parsed = _parse(doc) or {"nodes": []}
    seen, found = set(), []
    for node in parsed["nodes"]:
        value = node.get("entry")
        if node.get("type") != "file" or isinstance(value, bool) or not isinstance(value, int) or value in seen:
            continue
        seen.add(value)
        found.append(value)
    return found


def _summary(row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "created_at": row["created_at"], "updated_at": row["updated_at"],
        "items": len(entry_ids(row["doc"])),
    }


def list_boards() -> list:
    """Return every board, most recently touched first."""
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM boards ORDER BY updated_at DESC, id DESC").fetchall()
    finally:
        conn.close()
    return [_summary(row) for row in rows]


def create_board(name="") -> dict:
    """Create an empty board, named "Untitled NN" when no name is given; returns {"ok": True, "board": {...}}."""
    conn = db.connect()
    try:
        name = _clean(name)
        if not name:
            count = conn.execute("SELECT COUNT(*) FROM boards").fetchone()[0]
            name = f"Untitled {count + 1:02d}"
        stamp = _now()
        cursor = conn.execute(
            "INSERT INTO boards (name, doc, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, json.dumps({"nodes": [], "edges": []}), stamp, stamp),
        )
        row = conn.execute("SELECT * FROM boards WHERE id = ?", (cursor.lastrowid,)).fetchone()
    finally:
        conn.close()
    return {"ok": True, "board": _summary(row)}


def get_board(board_id: int) -> dict | None:
    """Return a board's summary with its parsed document, or None when it is missing."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {**_summary(row), "doc": _parse(row["doc"]) or {"nodes": [], "edges": []}}


def save_board(board_id: int, doc) -> dict:
    """Replace a board's document and mark it touched; returns {"ok": True, "board": {...}} or an error."""
    parsed = _parse(doc)
    if parsed is None:
        return {"ok": False, "error": "That board could not be saved."}
    text = json.dumps(parsed, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_DOC_BYTES:
        return {"ok": False, "error": "That board is too large to save."}
    conn = db.connect()
    try:
        changed = conn.execute(
            "UPDATE boards SET doc = ?, updated_at = ? WHERE id = ?", (text, _now(), board_id)).rowcount
        row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    finally:
        conn.close()
    if not changed:
        return {"ok": False, "error": "That board is gone."}
    return {"ok": True, "board": _summary(row)}


def add_entries(board_id: int, tiles: list) -> dict:
    """Lay library images out in rows below a board's current content, skipping any already on it.

    tiles are {"id", "width", "height"} dicts in the order to place. Returns {"ok": True, "board": {...},
    "added": n} or {"ok": False, "error": "..."}.
    """
    board = get_board(board_id)
    if board is None:
        return {"ok": False, "error": "That board is gone."}
    doc = board["doc"]
    present = set(entry_ids(doc))
    fresh = []
    for tile in tiles:
        value = tile.get("id")
        if isinstance(value, int) and not isinstance(value, bool) and value not in present:
            present.add(value)
            fresh.append(tile)
    if not fresh:
        return {"ok": True, "board": _summary_of(board), "added": 0}
    placed = [node for node in doc["nodes"] if all(isinstance(node.get(k), (int, float)) for k in ("x", "y", "width", "height"))]
    left = min((node["x"] for node in placed), default=0)
    top = max((node["y"] + node["height"] for node in placed), default=-ADD_GAP * 2) + ADD_GAP * 2
    x, row_height = left, 0
    for index, tile in enumerate(fresh):
        if index and index % ADD_PER_ROW == 0:
            x, top, row_height = left, top + row_height + ADD_GAP, 0
        width, height = tile.get("width") or 0, tile.get("height") or 0
        tall = round(ADD_WIDTH * height / width) if width and height else round(ADD_WIDTH * 0.75)
        doc["nodes"].append({"id": f"e{tile['id']}-{len(doc['nodes'])}", "type": "file", "file": f"hyperbridge:entry/{tile['id']}",
                             "entry": tile["id"], "x": x, "y": top, "width": ADD_WIDTH, "height": tall})
        x += ADD_WIDTH + ADD_GAP
        row_height = max(row_height, tall)
    saved = save_board(board_id, doc)
    if not saved["ok"]:
        return saved
    return {**saved, "added": len(fresh)}


def _summary_of(board: dict) -> dict:
    return {key: board[key] for key in ("id", "name", "created_at", "updated_at", "items")}


def rename_board(board_id: int, name) -> dict:
    """Rename a board; a blank name is refused."""
    name = _clean(name)
    if not name:
        return {"ok": False, "error": "Name the board."}
    conn = db.connect()
    try:
        changed = conn.execute(
            "UPDATE boards SET name = ?, updated_at = ? WHERE id = ?", (name, _now(), board_id)).rowcount
        row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    finally:
        conn.close()
    if not changed:
        return {"ok": False, "error": "That board is gone."}
    return {"ok": True, "board": _summary(row)}


def delete_board(board_id: int) -> bool:
    """Delete a board; its images stay in the library. Returns False when the board is missing."""
    conn = db.connect()
    try:
        return conn.execute("DELETE FROM boards WHERE id = ?", (board_id,)).rowcount > 0
    finally:
        conn.close()


def promote_board(board_id: int, name, order=None) -> dict:
    """Make a set from a board's images, then delete the board.

    order lists entry ids in reading order; ids not on the board are ignored and board images it leaves out
    follow in document order. Returns {"ok": True, "set": {...}, "count": n} or {"ok": False, "error": "..."}.
    """
    board = get_board(board_id)
    if board is None:
        return {"ok": False, "error": "That board is gone."}
    on_board = entry_ids(board["doc"])
    wanted = [value for value in order or [] if isinstance(value, int) and not isinstance(value, bool)]
    ordered = list(dict.fromkeys(value for value in wanted if value in on_board))
    ordered += [value for value in on_board if value not in ordered]
    if not ordered:
        return {"ok": False, "error": "Add images before promoting."}
    made = sets.create_set(_clean(name) or board["name"])
    if not made["ok"]:
        return made
    count = sets.place_many(ordered, made["set"]["id"])
    delete_board(board_id)
    return {"ok": True, "set": made["set"], "count": count}
