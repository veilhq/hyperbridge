"""Image embeddings: index the library, then score and de-duplicate feed candidates by visual similarity to it."""

import io
import logging
import os
import threading
from datetime import datetime

import db

logger = logging.getLogger("hyperbridge.embed")

MODEL = "google/siglip2-base-patch16-224"
EDGE = 256
BATCH = 16
NEAREST = 5
MIN_LIBRARY = 3
DUPLICATE_SIMILARITY = 0.97
FLOOR_PERCENTILE = 20
FLOOR_SAMPLE = 300
MIN_KEPT = 3
_model = None
_lock = threading.Lock()


def available() -> bool:
    """Whether the optional embedding dependencies are installed and the feature is not switched off."""
    if os.environ.get("HYPERBRIDGE_EMBEDDINGS") == "0":
        return False
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _load():
    global _model
    if _model is None:
        from fastembed import ImageEmbedding

        logger.info("loading embedding model %s (downloads on first use)", MODEL)
        _model = ImageEmbedding(model_name=MODEL)
    return _model


def embed_bytes(bodies) -> list:
    """Return a unit-length float32 vector per image body, or None for any body that cannot be read."""
    import numpy as np
    from PIL import Image

    images, positions = [], []
    for position, body in enumerate(bodies):
        try:
            with Image.open(io.BytesIO(body)) as image:
                image = image.convert("RGB")
                image.thumbnail((EDGE, EDGE))
                images.append(image.copy())
            positions.append(position)
        except Exception:  # noqa: BLE001 - an unreadable image simply gets no vector
            continue
    result = [None] * len(bodies)
    if not images:
        return result
    with _lock:
        vectors = list(_load().embed(images, batch_size=BATCH))
    for position, vector in zip(positions, vectors):
        vector = np.asarray(vector, dtype="float32")
        norm = float(np.linalg.norm(vector))
        result[position] = vector / norm if norm else None
    return result


def _pending(conn, limit):
    return conn.execute(
        "SELECT e.id, COALESCE(t.path, a.path) AS path FROM entries e"
        " JOIN assets a ON a.entry_id = e.id AND a.kind = 'original' AND a.position = 0"
        " LEFT JOIN assets t ON t.entry_id = e.id AND t.kind = 'thumbnail' AND t.position = 0"
        " WHERE NOT EXISTS (SELECT 1 FROM entry_vectors v WHERE v.entry_id = e.id AND v.model = ?)"
        " ORDER BY e.id DESC LIMIT ?", (MODEL, limit)).fetchall()


def index_library(conn, embedder=None, limit=64) -> int:
    """Embed up to limit captured entries that have no vector for the current model; returns how many were stored."""
    embedder = embedder or embed_bytes
    stored = 0
    rows = _pending(conn, limit)
    for start in range(0, len(rows), BATCH):
        chunk, bodies = [], []
        for row in rows[start:start + BATCH]:
            try:
                bodies.append((db.data_dir() / row["path"]).read_bytes())
                chunk.append(row)
            except OSError:
                continue
        for row, vector in zip(chunk, embedder(bodies)):
            if vector is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO entry_vectors (entry_id, model, dim, vector, created_at) VALUES (?, ?, ?, ?, ?)",
                (row["id"], MODEL, len(vector), vector.tobytes(), datetime.now().isoformat(timespec="seconds")))
            stored += 1
    return stored


def library_matrix(conn):
    """Return an (entries x dimensions) float32 matrix of the library's vectors for the current model."""
    import numpy as np

    rows = conn.execute("SELECT vector FROM entry_vectors WHERE model = ?", (MODEL,)).fetchall()
    if not rows:
        return np.zeros((0, 0), dtype="float32")
    return np.vstack([np.frombuffer(row["vector"], dtype="float32") for row in rows])


def score(matrix, vector) -> tuple:
    """Return (affinity, closest): the mean of the nearest library similarities, and the single closest."""
    import numpy as np

    sims = np.sort(matrix @ vector)[::-1]
    return float(sims[:NEAREST].mean()), float(sims[0])


def rank(conn, items, fetch_thumb, embedder=None) -> list:
    """Score items against the library, drop near-copies of saved images and failed reads, and order best first.

    Returns the items unchanged when embeddings are unavailable or the library is too small to steer by.
    """
    if embedder is None and not available():
        return items
    embedder = embedder or embed_bytes
    index_library(conn, embedder)
    matrix = library_matrix(conn)
    if len(matrix) < MIN_LIBRARY or not items:
        return items
    from concurrent.futures import ThreadPoolExecutor

    def body(item):
        try:
            return fetch_thumb(item.get("thumb") or item["url"])
        except Exception:  # noqa: BLE001 - a thumbnail that cannot be read drops the item
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = list(pool.map(body, items))
    kept = [(item, data) for item, data in zip(items, bodies) if data]
    ranked = []
    for (item, _), vector in zip(kept, embedder([data for _, data in kept])):
        if vector is None:
            continue
        affinity, closest = score(matrix, vector)
        if closest < DUPLICATE_SIMILARITY:
            ranked.append({**item, "score": affinity})
    ranked.sort(key=lambda item: -item["score"])
    floor = quality_floor(matrix)
    kept = [item for item in ranked if item["score"] >= floor]
    return kept if len(kept) >= max(MIN_KEPT, len(ranked) // 4) else ranked[:max(MIN_KEPT, len(ranked) // 4)]


def quality_floor(matrix) -> float:
    """Return the affinity a candidate must reach: that of the library's less typical images (a low percentile).

    Each sampled library image is scored against the rest, excluding itself, the same way candidates are scored.
    """
    import numpy as np

    sample = matrix if len(matrix) <= FLOOR_SAMPLE else matrix[np.random.default_rng(0).choice(len(matrix), FLOOR_SAMPLE, False)]
    sims = np.sort(sample @ matrix.T, axis=1)[:, ::-1][:, 1:NEAREST + 1]
    return float(np.percentile(sims.mean(axis=1), FLOOR_PERCENTILE))
