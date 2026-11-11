"""Dominant-color swatches for entries: extraction, hue families and the one-time backfill."""

import colorsys
import io
import json

from bridge.core import db

SWATCH_COUNT = 5
_SAMPLE_EDGE = 96
FAMILIES = ("Red", "Orange", "Yellow", "Green", "Teal", "Blue", "Purple", "Pink", "Neutral")
NO_COLOR = "No color"


def extract(body: bytes, count: int = SWATCH_COUNT) -> list[str]:
    """Return up to count dominant colors of an image as hex strings, most common first."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(body)) as image:
            small = image.convert("RGB")
            small.thumbnail((_SAMPLE_EDGE, _SAMPLE_EDGE))
            quantized = small.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette() or []
            counts = sorted(quantized.getcolors() or [], reverse=True)
    except Exception:  # noqa: BLE001 - an unreadable image simply has no swatches
        return []
    return ["#{:02x}{:02x}{:02x}".format(*palette[index * 3:index * 3 + 3]) for _, index in counts[:count]]


def family(hex_color: str) -> str:
    """Return the hue family name of a hex color; low-saturation or extreme tones are Neutral."""
    try:
        red, green, blue = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (ValueError, IndexError, TypeError):
        return NO_COLOR
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    if sat < 0.18 or light < 0.12 or light > 0.92:
        return "Neutral"
    degrees = hue * 360
    for limit, name in ((15, "Red"), (45, "Orange"), (70, "Yellow"), (165, "Green"), (200, "Teal"),
                        (260, "Blue"), (310, "Purple"), (345, "Pink")):
        if degrees < limit:
            return name
    return "Red"


def _lab(hex_color: str) -> tuple[float, float, float]:
    """Convert a hex color to OKLab."""
    channels = []
    for i in (1, 3, 5):
        value = int(hex_color[i:i + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    long = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    mid = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)
    return (
        0.2104542553 * long + 0.7936177850 * mid - 0.0040720468 * short,
        1.9779984951 * long - 2.4285922050 * mid + 0.4505937099 * short,
        0.0259040371 * long + 0.7827717662 * mid - 0.8086757660 * short,
    )


NEAR_DISTANCE = 0.12


def near(raw: str, hex_color: str, limit: float = NEAR_DISTANCE) -> bool:
    """Return whether any stored swatch is a similar shade to hex_color (OKLab distance within limit)."""
    try:
        target = _lab(hex_color)
        values = [_lab(value) for value in parse(raw)]
    except (ValueError, IndexError, TypeError):
        return False
    return any(sum((a - b) ** 2 for a, b in zip(target, value)) ** 0.5 <= limit for value in values)


def entry_family(raw: str) -> str:
    """Return the hue family of the first stored swatch, or NO_COLOR when there is none."""
    try:
        values = json.loads(raw or "[]")
    except ValueError:
        return NO_COLOR
    return family(values[0]) if values else NO_COLOR


HUE_STEPS = 24


def gradient_key(raw: str) -> tuple:
    """Sort key that runs colors around the hue wheel (light to dark within a step), then greys dark to light, then no color."""
    values = parse(raw)
    try:
        red, green, blue = (int(values[0][i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (IndexError, ValueError):
        return (2, 0, 0.0)
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    if sat < 0.18 or light < 0.12 or light > 0.92:
        return (1, 0, light)
    return (0, int(hue * HUE_STEPS) % HUE_STEPS, -light)


def parse(raw: str) -> list[str]:
    """Parse the stored swatch JSON, tolerating bad data."""
    try:
        values = json.loads(raw or "[]")
    except ValueError:
        return []
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def store(conn, entry_id: int, body: bytes) -> None:
    """Extract swatches from image bytes and save them on the entry."""
    conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(extract(body)), entry_id))


def backfill(conn) -> int:
    """Fill swatches for captured entries that have none yet; return how many were updated."""
    rows = conn.execute(
        "SELECT e.id, a.path FROM entries e JOIN assets a ON a.entry_id = e.id"
        " AND a.kind = 'original' AND a.position = 0 WHERE e.swatches = '[]'"
    ).fetchall()
    updated = 0
    for row in rows:
        path = db.data_dir() / row["path"]
        try:
            body = path.read_bytes()
        except OSError:
            continue
        values = extract(body)
        if values:
            conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(values), row["id"]))
            updated += 1
    conn.commit()
    return updated
