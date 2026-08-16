#!/usr/bin/env python3
"""
youtube_sync.py — production YouTube metadata synchronization.

Pulls current metadata from the official YouTube Data API v3 and
updates each Node's YouTube-managed fields. This is the ONLY part of
the project that ever talks to YouTube — build.py never does.

──────────────────────────────────────────────────────────────────────
SINGLE SOURCE OF TRUTH
──────────────────────────────────────────────────────────────────────
`youtube.videoId` is the only YouTube identifier ever stored. There is
no stored URL field anywhere — a watch URL is generated from videoId
only in the moment it's needed (e.g. in this script's own printed
reports), never saved to a Node file.

──────────────────────────────────────────────────────────────────────
WHAT SYNC UPDATES, AND WHAT IT NEVER TOUCHES
──────────────────────────────────────────────────────────────────────
Sync may update ONLY these seven fields, inside a Node's "youtube" object:
    youtube.title
    youtube.description
    youtube.publishedAt
    youtube.thumbnailUrl
    youtube.durationSeconds
    youtube.availability
    youtube.lastSyncedAt

Sync NEVER reads or writes anything else — not videoId, not
classification, tags, priority, relatedNodeIds, publishing, clinical,
or any other manually-managed field. It also never touches build.py,
any template, or any file outside nodes/*.json.

──────────────────────────────────────────────────────────────────────
THE THREE POSSIBLE OUTCOMES FOR ANY ONE NODE
──────────────────────────────────────────────────────────────────────
1. YouTube responds successfully, video found
   -> availability = "available", the seven fields above are refreshed
      from YouTube's current data, lastSyncedAt = now.

2. YouTube responds successfully, but this video ID is NOT in the
   results (confirmed missing — deleted, private, etc.)
   -> availability = "unavailable". Previously stored title,
      description, publishedAt, thumbnailUrl, and durationSeconds are
      LEFT ALONE (not erased). lastSyncedAt IS updated to now, because
      a real, completed check did happen.

3. The request itself fails for a technical reason (network error,
   timeout, invalid/quota-exceeded API key, malformed response, or an
   entire batch request failing)
   -> NOTHING is changed for the affected Node(s) at all — not
      availability, not lastSyncedAt, not any other field. This is
      reported as a sync failure, never confused with "video is
      actually unavailable".

──────────────────────────────────────────────────────────────────────
ARCHITECTURE: ONE ENGINE, TWO WORKFLOWS
──────────────────────────────────────────────────────────────────────
sync_one_node() is the primary, reusable workflow — sync exactly one
Node. sync_all_nodes() is the bulk workflow: it loads every Node and
applies that exact same per-Node outcome logic (apply_sync_result) to
each one, so a single Node syncs identically whether you sync it alone
or as part of a full run. The only difference is efficiency: instead
of one YouTube request per Node, sync_all_nodes() batches up to 50
video IDs into a single request (YouTube Data API's batch limit),
which matters once the Node library grows well beyond a handful.

──────────────────────────────────────────────────────────────────────
CLI USAGE
──────────────────────────────────────────────────────────────────────
Sync one Node by slug (the everyday workflow):
    python3 youtube_sync.py --node template-node

Sync every Node in the library:
    python3 youtube_sync.py --all

Preview what would change without writing anything (recommended before
trusting either command the first few times):
    python3 youtube_sync.py --node SLUG --dry-run
    python3 youtube_sync.py --all --dry-run

──────────────────────────────────────────────────────────────────────
SETUP
──────────────────────────────────────────────────────────────────────
    pip install requests --break-system-packages
    export YOUTUBE_API_KEY="your-api-key-here"
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

import node_store

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
HTTP_TIMEOUT_SECONDS = 10
BATCH_SIZE = 50  # YouTube Data API v3's maximum ids per videos.list call

# The exact, complete set of fields Sync is ever allowed to touch.
# Documented here as the single source of truth for that rule — see
# apply_sync_result(), which is the only function that writes to a
# Node's "youtube" object.
SYNC_MANAGED_FIELDS = (
    "title", "description", "publishedAt", "thumbnailUrl", "durationSeconds",
    "availability", "lastSyncedAt",
)

_THUMBNAIL_PREFERENCE = ["maxres", "standard", "high", "medium", "default"]

_ISO8601_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def _parse_iso8601_duration(duration: str) -> Optional[int]:
    """
    Converts YouTube's contentDetails.duration (ISO 8601, e.g. "PT1M17S",
    "PT18S", "PT2M") into a whole number of seconds. Returns None if the
    string doesn't match the expected format — the caller treats that the
    same as a malformed/missing item, never as "video is 0 seconds long".
    """
    if not duration:
        return None
    match = _ISO8601_DURATION_RE.match(duration)
    if not match or not any(match.groups()):
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


class SyncError(Exception):
    """
    A TECHNICAL failure: network error, timeout, bad/quota-exceeded API
    key, or a malformed response from YouTube. Raised by
    fetch_videos_batch() and must never be confused with "YouTube
    responded fine and the video just isn't there" — that second case
    is a normal (non-exception) result, not an error.
    """


@dataclass
class SyncOutcome:
    """One line of a sync report, for one Node."""
    node_id: str
    slug: str
    video_id: str
    title: str
    status: str  # "updated" | "unchanged" | "unavailable" | "failed"
    error: Optional[str] = None

    @property
    def youtube_url(self) -> str:
        """Generated on demand for display — never stored anywhere."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _select_thumbnail(thumbnails: dict) -> Optional[str]:
    """Best available thumbnail URL, preferring maxres > standard > high > medium > default."""
    for size in _THUMBNAIL_PREFERENCE:
        entry = thumbnails.get(size)
        if entry and entry.get("url"):
            return entry["url"]
    return None


def fetch_videos_batch(video_ids: list[str], api_key: str) -> dict[str, dict]:
    """
    Calls YouTube Data API v3 videos.list ONCE for up to BATCH_SIZE
    video ids (caller is responsible for chunking a larger list).

    Returns a dict of {video_id: normalized_snippet} for every id that
    WAS found in the response. Any id from the input that is NOT a key
    in the returned dict was confirmed absent from YouTube's response —
    that is the "confirmed unavailable" case, not an error.

    Raises SyncError for ANY technical failure (network, timeout, HTTP
    error, malformed JSON, API-level error). When this raises, the
    caller must not assume anything about ANY id in this batch — none
    of them were actually checked.
    """
    if not video_ids:
        return {}
    if len(video_ids) > BATCH_SIZE:
        raise ValueError(f"fetch_videos_batch supports at most {BATCH_SIZE} video IDs per call")

    params = {
        "part": "snippet,contentDetails",
        "id": ",".join(video_ids),
        "key": api_key,
    }

    try:
        response = requests.get(YOUTUBE_API_URL, params=params, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as exc:
        raise SyncError("The request to YouTube timed out.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise SyncError("Could not connect to YouTube. Check your network connection.") from exc
    except requests.exceptions.RequestException as exc:
        raise SyncError(f"Network error while contacting YouTube: {exc}") from exc

    if response.status_code == 403:
        raise SyncError(
            "YouTube rejected the request (HTTP 403) — the API key may be invalid, "
            "restricted, or the daily quota may be exceeded."
        )
    if response.status_code == 400:
        raise SyncError("YouTube rejected the request as malformed (HTTP 400).")
    if response.status_code != 200:
        raise SyncError(f"YouTube API returned an unexpected HTTP status: {response.status_code}.")

    try:
        body = response.json()
    except ValueError as exc:
        raise SyncError("YouTube's response was not valid JSON.") from exc

    if "error" in body:
        message = body["error"].get("message", "Unknown API error.")
        raise SyncError(f"YouTube API returned an error: {message}")

    items = body.get("items")
    if items is None:
        raise SyncError("YouTube's response was malformed (missing 'items').")

    results: dict[str, dict] = {}
    for item in items:
        video_id = item.get("id")
        snippet = item.get("snippet")
        if not video_id or not snippet:
            continue  # skip an individual malformed item rather than failing the whole batch
        title = snippet.get("title")
        if not title:
            continue
        thumbnails = snippet.get("thumbnails") or {}
        content_details = item.get("contentDetails") or {}
        results[video_id] = {
            "title": title,
            "description": snippet.get("description", ""),
            "publishedAt": snippet.get("publishedAt"),
            "thumbnailUrl": _select_thumbnail(thumbnails),
            "durationSeconds": _parse_iso8601_duration(content_details.get("duration")),
        }

    return results


def apply_sync_result(node: dict, fetched: Optional[dict], now_iso: str) -> None:
    """
    THE single shared engine both sync_one_node() and sync_all_nodes()
    use to apply one completed (non-technical-failure) result to one
    Node, in place. This is the one and only place that writes to a
    Node's "youtube" object — see SYNC_MANAGED_FIELDS for the complete,
    enforced list of what it's allowed to touch.

    fetched = a normalized metadata dict -> video confirmed available;
              refresh all seven managed fields from it.
    fetched = None -> video confirmed NOT in YouTube's response; mark
              unavailable, and deliberately leave title/description/
              publishedAt/thumbnailUrl/durationSeconds exactly as they
              were.

    In both cases, lastSyncedAt is updated to now_iso, because a real,
    completed check happened either way.
    """
    yt = node["youtube"]
    if fetched is not None:
        yt["title"] = fetched["title"]
        yt["description"] = fetched["description"]
        if fetched["publishedAt"]:
            yt["publishedAt"] = fetched["publishedAt"]
        if fetched["thumbnailUrl"]:
            yt["thumbnailUrl"] = fetched["thumbnailUrl"]
        if fetched["durationSeconds"] is not None:
            yt["durationSeconds"] = fetched["durationSeconds"]
        yt["availability"] = "available"
    else:
        yt["availability"] = "unavailable"
    yt["lastSyncedAt"] = now_iso


def _chunked(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def sync_one_node(node: dict, api_key: str, dry_run: bool = False) -> SyncOutcome:
    """
    PRIMARY synchronization workflow: sync exactly one Node.
    Internally calls fetch_videos_batch() with a batch of size one —
    the same underlying engine sync_all_nodes() uses, just applied to
    a single Node directly, so results are guaranteed identical to
    what that Node would get as part of a full sync run.
    """
    video_id = node["youtube"]["videoId"]
    original_title = node["youtube"]["title"]

    try:
        results = fetch_videos_batch([video_id], api_key)
    except SyncError as exc:
        return SyncOutcome(node["id"], node["slug"], video_id, original_title, "failed", str(exc))

    fetched = results.get(video_id)
    apply_sync_result(node, fetched, _now_iso())

    changed = node_store.node_content_changed(node)
    if changed and not dry_run:
        node_store.write_node(node)

    status = "unavailable" if fetched is None else ("updated" if changed else "unchanged")
    return SyncOutcome(node["id"], node["slug"], video_id, node["youtube"]["title"], status)


def sync_one_node_by_slug(slug: str, api_key: str, dry_run: bool = False) -> SyncOutcome:
    """Thin CLI-facing wrapper: look a Node up by slug, then sync it."""
    all_nodes, _ = node_store.load_all_nodes_checked()
    matches = [n for n in all_nodes if n["slug"] == slug]
    if not matches:
        raise SystemExit(f"No node found with slug '{slug}'")
    return sync_one_node(matches[0], api_key, dry_run=dry_run)


def sync_all_nodes(api_key: str, dry_run: bool = False) -> list[SyncOutcome]:
    """
    BULK synchronization workflow: every Node in the library.
    Applies the exact same apply_sync_result() engine sync_one_node()
    uses — the only difference is that YouTube requests are batched up
    to BATCH_SIZE ids at a time for efficiency. If an entire batch
    request fails technically, every Node in that batch is reported as
    failed and left completely untouched; the run continues with the
    remaining batches rather than aborting entirely.
    """
    all_nodes, _ = node_store.load_all_nodes_checked()
    now_iso = _now_iso()
    outcomes: list[SyncOutcome] = []

    for chunk in _chunked(all_nodes, BATCH_SIZE):
        video_ids = [n["youtube"]["videoId"] for n in chunk]
        try:
            results = fetch_videos_batch(video_ids, api_key)
        except SyncError as exc:
            for n in chunk:
                outcomes.append(SyncOutcome(
                    n["id"], n["slug"], n["youtube"]["videoId"], n["youtube"]["title"], "failed", str(exc)
                ))
            continue

        for n in chunk:
            video_id = n["youtube"]["videoId"]
            fetched = results.get(video_id)
            apply_sync_result(n, fetched, now_iso)

            changed = node_store.node_content_changed(n)
            if changed and not dry_run:
                node_store.write_node(n)

            status = "unavailable" if fetched is None else ("updated" if changed else "unchanged")
            outcomes.append(SyncOutcome(n["id"], n["slug"], video_id, n["youtube"]["title"], status))

    return outcomes


def print_report(outcomes: list[SyncOutcome], dry_run: bool) -> None:
    total = len(outcomes)
    updated = [o for o in outcomes if o.status == "updated"]
    unchanged = [o for o in outcomes if o.status == "unchanged"]
    unavailable = [o for o in outcomes if o.status == "unavailable"]
    failed = [o for o in outcomes if o.status == "failed"]

    mode_label = " (DRY RUN — no files were written)" if dry_run else ""
    print(f"\nSync summary{mode_label}:")
    print(f"  Total Nodes processed: {total}")
    print(f"  Updated:               {len(updated)}")
    print(f"  Unchanged:             {len(unchanged)}")
    print(f"  Unavailable:           {len(unavailable)}")
    print(f"  Failed:                {len(failed)}")

    if failed:
        print("\nFailed Node(s):")
        for o in failed:
            print(f"  - nodeId={o.node_id} slug={o.slug} videoId={o.video_id} "
                  f"youtubeUrl={o.youtube_url} title=\"{o.title}\"")
            print(f"    error: {o.error}")

    if unavailable:
        print("\nConfirmed unavailable Node(s) (previous metadata preserved):")
        for o in unavailable:
            print(f"  - nodeId={o.node_id} slug={o.slug} videoId={o.video_id} title=\"{o.title}\"")


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube metadata synchronization")
    parser.add_argument("--node", metavar="SLUG", help="Sync one Node by slug")
    parser.add_argument("--all", action="store_true", help="Sync every Node in the library")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change; write nothing")
    args = parser.parse_args()

    if not args.node and not args.all:
        print(__doc__)
        return 1

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print(
            "Error: the YOUTUBE_API_KEY environment variable is not set.\n"
            "Set it before running this script, e.g.:\n"
            '  export YOUTUBE_API_KEY="your-api-key-here"',
            file=sys.stderr,
        )
        return 1

    if args.node:
        outcome = sync_one_node_by_slug(args.node, api_key, dry_run=args.dry_run)
        print_report([outcome], args.dry_run)
        return 1 if outcome.status == "failed" else 0

    outcomes = sync_all_nodes(api_key, dry_run=args.dry_run)
    print_report(outcomes, args.dry_run)
    return 1 if any(o.status == "failed" for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
