"""SQLite access for Hyperbridge: connections, numbered migrations, data paths."""

import os
import re
import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = APP_DIR / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def data_dir() -> Path:
    """Return the library folder; HYPERBRIDGE_DATA_DIR overrides the default (tests)."""
    override = os.environ.get("HYPERBRIDGE_DATA_DIR")
    return Path(override).resolve() if override else APP_DIR / "data"


def db_path() -> Path:
    """Return the path of the library database file."""
    return data_dir() / "hyperbridge.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a connection in autocommit mode with WAL, foreign keys and a busy timeout."""
    target = Path(path) if path else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def list_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """Return (version, file) pairs sorted by version; versions must be unique and gapless."""
    found = []
    for item in sorted(directory.iterdir()):
        match = _MIGRATION_NAME.match(item.name)
        if match:
            found.append((int(match.group(1)), item))
    versions = [version for version, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"Migration versions must run 1..N without gaps, found {versions}")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the applied migration count stored in PRAGMA user_version."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _split_statements(script: str) -> list[str]:
    """Split a script into complete statements, keeping trigger bodies whole."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise RuntimeError("Migration ends with an incomplete statement")
    return statements


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> int:
    """Apply pending migrations, each in its own transaction; return the new version."""
    current = schema_version(conn)
    for version, item in list_migrations(directory):
        if version <= current:
            continue
        statements = _split_statements(item.read_text(encoding="utf-8"))
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


def init_library() -> sqlite3.Connection:
    """Create the data folder, open the database and bring it to the latest schema."""
    conn = connect()
    migrate(conn)
    return conn
