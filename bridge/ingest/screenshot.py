"""Page screenshots through headless Edge, used when a page has no usable preview image."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

WIDTH = 1280
HEIGHT = 1600
TIMEOUT_SECONDS = 45
_EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


class ScreenshotError(Exception):
    """Raised when no browser is available or the screenshot could not be taken."""


def find_edge() -> str | None:
    """Return the path of msedge.exe, or None when Edge is not installed."""
    found = shutil.which("msedge")
    if found:
        return found
    for candidate in _EDGE_PATHS:
        if os.path.exists(candidate):
            return candidate
    return None


def capture_page(url: str) -> bytes:
    """Render an http(s) URL in headless Edge and return the PNG bytes."""
    if not str(url).lower().startswith(("http://", "https://")):
        raise ScreenshotError("Only web pages can be screenshotted")
    edge = find_edge()
    if edge is None:
        raise ScreenshotError("Microsoft Edge was not found")
    with tempfile.TemporaryDirectory(prefix="hyperbridge-shot-") as work:
        target = Path(work) / "page.png"
        command = [
            edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            f"--user-data-dir={Path(work) / 'profile'}", f"--window-size={WIDTH},{HEIGHT}",
            "--virtual-time-budget=8000", f"--screenshot={target}", url,
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise ScreenshotError(f"Screenshot failed: {error}") from error
        if not target.exists() or target.stat().st_size == 0:
            raise ScreenshotError("Edge produced no screenshot")
        return target.read_bytes()
