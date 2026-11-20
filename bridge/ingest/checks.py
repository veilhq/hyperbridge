"""Remembers which entries each source lookup has read or failed to read, and when a failed one may be tried again."""

from datetime import datetime

from bridge.core.pacer import PUSHBACK_STATUSES, HostCooling

FIRST_WAIT_DAYS = 1
MAX_WAIT_DAYS = 30


def now() -> str:
    """Return the current local time in the format entry_checks stores."""
    return datetime.now().isoformat(timespec="seconds")


def due(alias="entries") -> str:
    """Return an SQL condition, taking (step, now) parameters, that is true when the entry may be looked up for that step.

    An entry is due when it has no check, or its last try failed and the wait (one day, doubling per failure, at most thirty) has passed.
    """
    return (f"NOT EXISTS (SELECT 1 FROM entry_checks c WHERE c.entry_id = {alias}.id AND c.step = ?"
            f" AND (c.failures = 0 OR julianday(?) < julianday(c.checked_at)"
            f" + min({MAX_WAIT_DAYS}, {FIRST_WAIT_DAYS} << min(c.failures - 1, 5))))")


def passed(conn, entry_id, step, at=None) -> None:
    """Record that a step read an entry, so it is not read again."""
    conn.execute("INSERT OR REPLACE INTO entry_checks (entry_id, step, checked_at, failures) VALUES (?, ?, ?, 0)",
                 (entry_id, step, at or now()))


def failed(conn, entry_id, step, at=None) -> None:
    """Record one more failed try of a step on an entry, which lengthens its wait."""
    conn.execute("INSERT INTO entry_checks (entry_id, step, checked_at, failures) VALUES (?, ?, ?, 1)"
                 " ON CONFLICT (entry_id, step) DO UPDATE SET failures = failures + 1, checked_at = excluded.checked_at",
                 (entry_id, step, at or now()))


def pushed_back(err) -> bool:
    """Return True when a failure came from the host refusing or limiting requests, not from the entry itself."""
    return isinstance(err, HostCooling) or getattr(err, "status", 0) in PUSHBACK_STATUSES
