#!/usr/bin/env python3
"""
fetch_video_preview.py — read-only YouTube metadata preview.

For proposing a new Node BEFORE any Node file exists: fetches the same
fields youtube_sync.py would later sync into a Node (title, description,
publishedAt, thumbnailUrl, durationSeconds), for a bare videoId. Never
writes anything — prints JSON to stdout only. This script's whole reason
to exist is to be a fixed, narrowly-scoped, safely-allowlistable command
(unlike an ad-hoc `python -c "..."` one-liner, which is arbitrary code
and can never be safely blanket-approved).

youtube_sync.py --node SLUG remains the only way to write this data into
an actual Node file — this script never touches nodes/*.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import youtube_sync as ys


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only YouTube video metadata preview")
    parser.add_argument("--video-id", required=True, help="YouTube video id, e.g. from a /shorts/<id> URL")
    args = parser.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    sys.stdout.reconfigure(encoding="utf-8")

    try:
        result = ys.fetch_videos_batch([args.video_id], api_key)
    except ys.SyncError as exc:
        print(f"Technical failure contacting YouTube: {exc}", file=sys.stderr)
        return 1

    if args.video_id not in result:
        print(json.dumps({args.video_id: None}, indent=2))
        print(f"Video {args.video_id} was not found (confirmed absent from YouTube's response).", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
