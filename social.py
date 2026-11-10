"""Fills tags, creator, caption and posted date on saved entries whose source link is an X post or an Instagram post."""

import html
import json
import re
from datetime import datetime

import capture
import library

LIMIT = 50
_X_POST = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[^/?#]+/status/(\d+)", re.I)
_HASHTAG = re.compile(r"(?<![\w&])#([^\W\d_][\w]*)", re.U)


def hashtags(text) -> list:
    """Return the distinct hashtag words in a caption, without the hash sign."""
    return list(dict.fromkeys(match.lower() for match in _HASHTAG.findall(text or "")))


def _x_post(fetcher, post_id) -> dict:
    data = json.loads(bytes(fetcher(f"https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=a").body))
    if not data.get("text"):
        raise ValueError("post not readable")
    user = data.get("user") or {}
    tags = [tag.get("text") for tag in (data.get("entities") or {}).get("hashtags") or []] or hashtags(data["text"])
    return {"service": "x", "ref": str(post_id), "creator": user.get("screen_name") or "", "text": html.unescape(data["text"]),
            "posted": str(data.get("created_at") or "")[:10], "tags": tags}


def _instagram_post(fetcher, embed_url) -> dict:
    page = capture._decode(bytes(fetcher(embed_url).body))
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
        x_match = _X_POST.match(url)
        embed = capture.instagram_embed_url(url)
        if not x_match and not embed:
            continue
        try:
            post = _x_post(fetcher, x_match.group(1)) if x_match else _instagram_post(fetcher, embed)
        except Exception:  # noqa: BLE001 - a post that cannot be read is retried on a later run
            continue
        publisher = "X" if post["service"] == "x" else "Instagram"
        conn.execute(
            "UPDATE entries SET source_service = ?, source_ref = ?, collection = ?, posted_at = ?,"
            " creator = CASE WHEN creator = '' THEN ? ELSE creator END,"
            " description = CASE WHEN description = '' THEN ? ELSE description END,"
            " publisher = CASE WHEN publisher = '' THEN ? ELSE publisher END WHERE id = ?",
            (post["service"], post["ref"], post["creator"][:200], post["posted"], post["creator"][:200],
             post["text"][:1000], publisher, row["id"]))
        library.add_entry_tags(conn, row["id"], post["tags"])
        done += 1
    return done
