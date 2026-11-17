"""Reads X and Instagram posts from the platforms' own embed endpoints, at capture time and as a backfill for saved links."""

import html
import json
import re

from bridge.ingest import capture
from bridge.library import library

LIMIT = 50
_X_POST = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[^/?#]+/status/(\d+)", re.I)
_HASHTAG = re.compile(r"(?<![\w&])#([^\W\d_][\w]*)", re.U)
_PUBLISHERS = {"x": "X", "instagram": "Instagram"}


def hashtags(text) -> list:
    """Return the distinct hashtag words in a caption, without the hash sign."""
    return list(dict.fromkeys(match.lower() for match in _HASHTAG.findall(text or "")))


def x_post_id(url) -> str:
    """Return the post id of an X or Twitter post link, or "" for anything else."""
    match = _X_POST.match(url or "")
    return match.group(1) if match else ""


def x_post(fetcher, post_id) -> dict:
    """Read an X post's author, text, date, hashtags and images from X's embed endpoint."""
    data = json.loads(bytes(fetcher(f"https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=a").body))
    if not data.get("text"):
        raise ValueError("post not readable")
    user = data.get("user") or {}
    tags = [tag.get("text") for tag in (data.get("entities") or {}).get("hashtags") or []] or hashtags(data["text"])
    media = [item.get("media_url_https") for item in data.get("mediaDetails") or []]
    media = media or [item.get("url") for item in data.get("photos") or []]
    images = list(dict.fromkeys(url for url in media if isinstance(url, str) and url.startswith("https://")))
    return {"service": "x", "ref": str(post_id), "creator": user.get("screen_name") or "", "text": html.unescape(data["text"]),
            "posted": str(data.get("created_at") or "")[:10], "tags": tags, "images": images}


def instagram_post(embed_bytes) -> dict:
    """Read an Instagram post's owner, caption and hashtags from its embed page."""
    page = capture._decode(bytes(embed_bytes))
    marker = '"contextJSON":'
    start = page.find(marker)
    if start < 0:
        raise ValueError("post not readable")
    literal, _ = json.JSONDecoder().raw_decode(page[start + len(marker):])
    media = json.loads(literal)["gql_data"]["shortcode_media"]
    edges = (media.get("edge_media_to_caption") or {}).get("edges") or []
    text = ((edges[0].get("node") or {}).get("text") or "") if edges else ""
    return {"service": "instagram", "ref": str(media.get("shortcode") or ""),
            "creator": (media.get("owner") or {}).get("username") or "", "text": text, "posted": "", "tags": hashtags(text)}


def entry_fields(post) -> dict:
    """Return a post's details as the entry fields capture applies."""
    return {"creator": post["creator"][:200], "description": post["text"][:1000], "publisher": _PUBLISHERS[post["service"]],
            "posted_at": post["posted"], "tags": post["tags"]}


def mark_source(conn, entry_id, post) -> None:
    """Record the service, post id and author collection on an entry that has no source service yet."""
    conn.execute("UPDATE entries SET source_service = ?, source_ref = ?, collection = ? WHERE id = ? AND source_service = ''",
                 (post["service"], post["ref"], post["creator"][:200], entry_id))


def backfill(conn, fetcher, limit=LIMIT) -> int:
    """Read each unfilled X or Instagram post link once and record its tags, creator, caption and date; returns how many changed."""
    rows = conn.execute(
        "SELECT id, source_url, creator, description, publisher FROM entries"
        " WHERE source_service = '' AND (source_url LIKE '%/status/%' OR source_url LIKE '%instagram.com/%')").fetchall()
    done = 0
    for row in rows:
        if done >= limit:
            break
        url = row["source_url"]
        post_id = x_post_id(url)
        embed = capture.instagram_embed_url(url)
        if not post_id and not embed:
            continue
        try:
            post = x_post(fetcher, post_id) if post_id else instagram_post(fetcher(embed).body)
        except Exception:  # noqa: BLE001 - a post that cannot be read is retried on a later run
            continue
        conn.execute(
            "UPDATE entries SET source_service = ?, source_ref = ?, collection = ?, posted_at = ?,"
            " creator = CASE WHEN creator = '' THEN ? ELSE creator END,"
            " description = CASE WHEN description = '' THEN ? ELSE description END,"
            " publisher = CASE WHEN publisher = '' THEN ? ELSE publisher END WHERE id = ?",
            (post["service"], post["ref"], post["creator"][:200], post["posted"], post["creator"][:200],
             post["text"][:1000], _PUBLISHERS[post["service"]], row["id"]))
        library.add_entry_tags(conn, row["id"], post["tags"])
        done += 1
    return done
