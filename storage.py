"""Sharded asset folders: assets/<uid[:2]>/<uid>/ holds one entry's files."""

import re
import uuid
from pathlib import Path

from db import data_dir

ASSET_KINDS = ("original", "thumbnail", "screenshot")
_UID = re.compile(r"^[0-9a-f]{32}$")


def new_uid() -> str:
    """Return a fresh 32-character hex id for an entry."""
    return uuid.uuid4().hex


def assets_root() -> Path:
    """Return the root folder that holds every entry's assets."""
    return data_dir() / "assets"


def entry_dir(uid: str) -> Path:
    """Return the sharded folder for an entry; rejects ids that are not 32 hex characters."""
    if not _UID.match(uid):
        raise ValueError(f"Invalid entry uid: {uid!r}")
    return assets_root() / uid[:2] / uid


def asset_path(uid: str, kind: str, position: int, suffix: str) -> Path:
    """Return the file path for one asset, for example original-0.png."""
    if kind not in ASSET_KINDS:
        raise ValueError(f"Unknown asset kind: {kind!r}")
    if position < 0:
        raise ValueError("Asset position must be zero or greater")
    clean = suffix if suffix.startswith(".") else f".{suffix}"
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", clean):
        raise ValueError(f"Invalid asset suffix: {suffix!r}")
    return entry_dir(uid) / f"{kind}-{position}{clean}"


def relative_path(path: Path) -> str:
    """Return a path relative to the data folder with forward slashes, for storing in the database."""
    return path.resolve().relative_to(data_dir().resolve()).as_posix()
