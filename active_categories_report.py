#!/usr/bin/env python3
"""
active_categories_report.py — read-only classification research tool.

For proposing a new Node's classification: reports which registry
categories are currently "active" (>=1 published, available Node — i.e.
already have a live Topic page on the site, per build.py's
derive_active_topics() rule) and how many Nodes each has, and optionally
the existing tag usage of Nodes already in a given category, so a new
Node's tags stay consistent with what's already there.

Read-only: loads nodes/*.json and data/code-categories-and-tags.json,
never writes anything. Exists as a fixed, narrowly-scoped command (unlike
an ad-hoc `python -c "..."` one-liner) so it can be safely allowlisted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import node_store

BASE_DIR = Path(__file__).parent
REGISTRY_PATH = BASE_DIR / "data" / "code-categories-and-tags.json"


def _is_live(node: dict) -> bool:
    return (
        node.get("publishing", {}).get("status") == "published"
        and node.get("youtube", {}).get("availability") != "unavailable"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only report of active Topic categories and their existing tag usage")
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Registry category id to show existing Nodes/tags for (repeatable)",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    internal_ids = set(registry.get("internalCategoryIds", []))
    nodes = node_store.load_all_nodes()
    live_nodes = [n for n in nodes if _is_live(n)]

    counts = Counter()
    for n in live_nodes:
        for cat in n.get("classification", {}).get("primaryCategoryIds", []):
            counts[cat] += 1

    print("=== Active categories (registry order; internal categories excluded) ===")
    for cat in registry["categories"]:
        if cat in internal_ids:
            continue
        if counts.get(cat, 0) > 0:
            label = registry.get("categoryLabelsHe", {}).get(cat, "")
            print(f"{cat}: {counts[cat]}  ({label})")

    for cat in args.category:
        print(f"\n=== Existing live Nodes in '{cat}' ===")
        matches = [n for n in live_nodes if cat in n.get("classification", {}).get("primaryCategoryIds", [])]
        if not matches:
            print("(none)")
            continue
        for n in matches:
            cls = n["classification"]
            print(f"- {n['slug']} (priority {n['priority']})")
            print(f"    title: {n['youtube']['title']}")
            print(f"    primaryTagIds: {cls['primaryTagIds']}")
            print(f"    secondaryTagIds: {cls['secondaryTagIds']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
