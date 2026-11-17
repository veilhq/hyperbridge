"""Finds AI-generation labels written into image files, so the discovery feed can hide labeled images."""

import struct
from concurrent.futures import ThreadPoolExecutor

HEAD_BYTES = 256 * 1024
CHECK_LIMIT = 120
WORKERS = 6
C2PA = "Content Credentials say AI-generated"
IPTC = "Image data says AI-generated"
GENERATOR = "Has image generator settings"
_AI_SOURCE_TYPES = (b"trainedAlgorithmicMedia", b"compositeWithTrainedAlgorithmicMedia")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_GENERATOR_KEYS = {"parameters", "prompt", "workflow", "invokeai_metadata", "invokeai_graph", "sd-metadata", "dream"}
_GENERATOR_SOFTWARE = (b"novelai",)


def _png_text(body):
    """Yield (keyword, value) for each text chunk in the readable part of a PNG."""
    position = len(_PNG_SIGNATURE)
    while position + 8 <= len(body):
        length, kind = struct.unpack(">I4s", body[position:position + 8])
        data = body[position + 8:position + 8 + length]
        if kind in (b"tEXt", b"zTXt", b"iTXt"):
            keyword, _, value = data.partition(b"\x00")
            yield keyword.decode("latin-1").lower(), value
        if kind == b"IEND" or len(data) < length:
            return
        position += 12 + length


def ai_label(body) -> str:
    """Return why an image's own bytes mark it as AI-generated, or "" when they carry no such label.

    Reads the IPTC digital source type (in XMP or a C2PA manifest) and PNG text chunks written by image generators.
    """
    body = bytes(body or b"")
    if any(marker in body for marker in _AI_SOURCE_TYPES):
        return C2PA if b"c2pa" in body else IPTC
    if body.startswith(_PNG_SIGNATURE):
        for keyword, value in _png_text(body):
            if keyword in _GENERATOR_KEYS or (keyword == "software" and value.lower().startswith(_GENERATOR_SOFTWARE)):
                return GENERATOR
    return ""


def _read_label(fetcher, url) -> str:
    """Fetch the start of an image file and return its label; a file that cannot be read counts as unlabeled."""
    try:
        head = fetcher(url, max_bytes=HEAD_BYTES, partial=True, headers={"Range": f"bytes=0-{HEAD_BYTES - 1}"})
        return ai_label(head.body)
    except Exception:  # noqa: BLE001 - an unreadable file is shown, the same as one with no label
        return ""


def check_new(conn, fetcher, limit=CHECK_LIMIT) -> int:
    """Check the newest unchecked feed images for AI labels and record what was found; returns how many were labeled."""
    rows = conn.execute("SELECT id, url FROM feed_items WHERE state = 'new' AND ai_checked = 0 ORDER BY id DESC LIMIT ?",
                        (int(limit),)).fetchall()
    if not rows:
        return 0
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(rows))) as pool:
        found = list(pool.map(lambda row: _read_label(fetcher, row["url"]), rows))
    conn.executemany("UPDATE feed_items SET ai_label = ?, ai_checked = 1 WHERE id = ?",
                     [(label, row["id"]) for row, label in zip(rows, found)])
    return sum(1 for label in found if label)
