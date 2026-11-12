"""One ordered pass over every library backfill: local repairs, then source lookups, then title and tag enrichment."""
import logging
import random
import time

from bridge.ingest import arena, capture, enrich, restore, social, tumblr
from bridge.library import swatches

logger = logging.getLogger("hyperbridge")


def local_steps(conn) -> list:
    """Return the repairs that need no network, as (name, callable) pairs."""
    return [
        ("image types", lambda: capture.fix_image_types(conn)),
        ("domains", lambda: capture.fix_domains(conn)),
        ("file name titles", lambda: capture.fix_file_name_titles(conn)),
        ("swatches", lambda: swatches.backfill(conn)),
        ("animated thumbnails", lambda: capture.refresh_animated_thumbnails(conn)),
    ]


def source_steps(conn, fetcher) -> list:
    """Return the lookups that ask outside services for missing details, as (name, callable) pairs."""
    return [
        ("arena", lambda: arena.backfill_origins(conn, fetcher, random.Random(), max_channels=None, retries=arena.RETRIES)),
        ("tumblr", lambda: tumblr.backfill(conn, fetcher)),
        ("social", lambda: social.backfill(conn, fetcher)),
        ("titles", lambda: restore.titles(conn, fetcher)),
    ]


def run_all(conn, fetcher=None, settle=0.0) -> list:
    """Run local repairs, then source lookups after settle seconds, then enrichment; return the names of steps that failed.

    A failing step is logged and skipped so later steps still run; it is retried at the next start.
    """
    fetcher = fetcher or capture.default_fetcher()
    failed = []

    def run(group):
        for name, step in group:
            try:
                step()
            except Exception:  # noqa: BLE001 - one failed backfill must not stop the rest
                logger.exception("%s backfill failed", name)
                failed.append(name)

    run(local_steps(conn))
    if settle:
        time.sleep(settle)
    run(source_steps(conn, fetcher))
    run([("enrich", lambda: enrich.backfill(conn))])
    return failed
