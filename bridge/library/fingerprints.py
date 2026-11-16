"""Image fingerprints for duplicate detection: an exact content hash and a perceptual difference hash per original."""

import hashlib
import io

from bridge.core import db

NEAR_BITS = 4  # difference-hash bits two images may differ by and still count as the same picture
MAX_DUPLICATES = 12
_MASK = (1 << 64) - 1
_PLAIN_BITS = 4  # hashes this close to all-zero or all-one come from flat images and match too much
_ORIENTATION = {2: "FLIP_LEFT_RIGHT", 3: "ROTATE_180", 4: "FLIP_TOP_BOTTOM", 5: "TRANSPOSE",
                6: "ROTATE_270", 7: "TRANSVERSE", 8: "ROTATE_90"}


def _signed(value: int) -> int:
    """Fold an unsigned 64-bit hash into SQLite's signed integer range."""
    return value - (1 << 64) if value >= 1 << 63 else value


def difference_hash(body: bytes) -> int | None:
    """Return the 64-bit difference hash of an image's first frame, upright, or None when it is unreadable or too plain to compare."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(body)) as image:
            orientation = image.getexif().get(0x0112)
            image.draft("L", (64, 64))
            grey = image.convert("L").resize((32, 32), Image.Resampling.BOX)
    except Exception:  # noqa: BLE001 - an unreadable image has no visual fingerprint
        return None
    if orientation in _ORIENTATION:
        grey = grey.transpose(getattr(Image.Transpose, _ORIENTATION[orientation]))
    pixels = grey.resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | (pixels[row * 9 + col] < pixels[row * 9 + col + 1])
    if value.bit_count() <= _PLAIN_BITS or value.bit_count() >= 64 - _PLAIN_BITS:
        return None
    return _signed(value)


def fingerprint(body: bytes) -> tuple[str, int | None]:
    """Return (SHA-256 hex, signed difference hash or None) for image bytes."""
    return hashlib.sha256(body).hexdigest(), difference_hash(body)


def distance(first, second) -> int | None:
    """Return how many bits two stored difference hashes differ by, or None when either is missing."""
    if first is None or second is None:
        return None
    return ((first ^ second) & _MASK).bit_count()


def register(conn) -> None:
    """Expose the hash distance to SQL for the duplicate lookup."""
    conn.create_function("hb_hash_distance", 2, distance, deterministic=True)


def duplicates(conn, entry_id: int) -> list[dict]:
    """Return other entries with an original that is byte-identical or visually near one of this entry's originals."""
    rows = conn.execute(
        "SELECT DISTINCT e.id, e.title FROM assets mine"
        " JOIN assets other ON other.kind = 'original' AND other.entry_id != mine.entry_id"
        " JOIN entries e ON e.id = other.entry_id"
        " WHERE mine.entry_id = ? AND mine.kind = 'original' AND ("
        "   (mine.sha256 != '' AND other.sha256 = mine.sha256)"
        "   OR hb_hash_distance(mine.dhash, other.dhash) <= ?)"
        " ORDER BY e.id LIMIT ?",
        (entry_id, NEAR_BITS, MAX_DUPLICATES),
    ).fetchall()
    return [{"id": row["id"], "title": row["title"]} for row in rows]


def backfill(conn) -> int:
    """Fingerprint stored originals that have none yet; return how many were filled. Missing files are retried next time."""
    rows = conn.execute("SELECT id, path FROM assets WHERE kind = 'original' AND sha256 IS NULL").fetchall()
    filled = 0
    for row in rows:
        try:
            body = (db.data_dir() / row["path"]).read_bytes()
        except OSError:
            continue
        digest, visual = fingerprint(body)
        conn.execute("UPDATE assets SET sha256 = ?, dhash = ? WHERE id = ?", (digest, visual, row["id"]))
        filled += 1
    conn.commit()
    return filled
