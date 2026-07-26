#!/usr/bin/env python3
"""
node_store.py — shared Node-file foundation.

This module owns everything about reading and writing nodes/*.json:
loading, duplicate-slug/id checks, id-based lookup, and the one
canonical way to write a Node file back to disk.

Both build.py (rendering the site) and youtube_sync.py (talking to the
YouTube API) import from this module. Neither of them imports the
other, and this module imports neither of them — that's deliberate:
it's what makes "Build never contacts YouTube" a fact you can verify
just by reading imports, not a rule someone has to remember to follow.

This module has no network dependency at all — it only touches the
local filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
NODES_DIR = BASE_DIR / "nodes"

# Minimal structural shape every Node file must have, regardless of its
# publishing status. This catches malformed/incomplete Node data (e.g. a
# hand-edited JSON file missing a top-level section entirely) with a clear
# error, instead of an obscure KeyError deep inside rendering or syncing.
_REQUIRED_NODE_SECTIONS = ["id", "slug", "youtube", "classification", "clinical", "publishing"]

# The internal bookkeeping key load_all_nodes() adds to every Node dict
# (its own source file path, for clear error messages). It must never be
# written back into the actual JSON file on disk.
_SOURCE_FILE_KEY = "_sourceFile"


def load_all_nodes() -> list[dict]:
    """Load every node data record from nodes/*.json. Fails clearly on bad JSON."""
    nodes = []
    for path in sorted(NODES_DIR.glob("*.json")):
        try:
            node = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"FAILED — invalid JSON in {path}: {e}")

        if not isinstance(node, dict):
            raise SystemExit(f"FAILED — {path} must contain a JSON object, not {type(node).__name__}")

        missing = [section for section in _REQUIRED_NODE_SECTIONS if section not in node]
        if missing:
            raise SystemExit(
                f"FAILED — invalid Node data in {path}: "
                f"missing required section(s): {', '.join(missing)}"
            )
        if node.get("publishing", {}).get("status") not in ("published", "draft", "unpublished", "archived"):
            raise SystemExit(
                f"FAILED — invalid publication data in {path}: "
                f"publishing.status must be one of published/draft/unpublished/archived "
                f"(got {node.get('publishing', {}).get('status')!r})"
            )

        node[_SOURCE_FILE_KEY] = str(path)
        nodes.append(node)
    return nodes


def check_for_duplicate_slugs(nodes: list[dict]) -> None:
    """Fail clearly and immediately if two node files share a slug."""
    seen: dict[str, str] = {}
    conflicts = []
    for node in nodes:
        slug = node["slug"]
        if slug in seen:
            conflicts.append((slug, seen[slug], node[_SOURCE_FILE_KEY]))
        else:
            seen[slug] = node[_SOURCE_FILE_KEY]
    if conflicts:
        lines = [f"  '{slug}' used in both {a} AND {b}" for slug, a, b in conflicts]
        raise SystemExit(
            "FAILED — duplicate Node slug(s) detected:\n" + "\n".join(lines)
        )


def check_for_duplicate_ids(nodes: list[dict]) -> None:
    """Fail clearly and immediately if two node files share an id."""
    seen: dict[str, str] = {}
    conflicts = []
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
        if node_id in seen:
            conflicts.append((node_id, seen[node_id], node[_SOURCE_FILE_KEY]))
        else:
            seen[node_id] = node[_SOURCE_FILE_KEY]
    if conflicts:
        lines = [f"  '{node_id}' used in both {a} AND {b}" for node_id, a, b in conflicts]
        raise SystemExit(
            "FAILED — duplicate Node id(s) detected:\n" + "\n".join(lines)
        )


def build_nodes_by_id(nodes: list[dict]) -> dict[str, dict]:
    """Efficient id -> Node lookup, built once per run."""
    return {node["id"]: node for node in nodes if node.get("id")}


def load_all_nodes_checked() -> tuple[list[dict], dict[str, dict]]:
    """
    Convenience wrapper used by both build.py and youtube_sync.py at the
    start of any whole-library operation: load every Node, fail fast on
    duplicate slugs/ids, and return both the flat list and the id lookup.
    """
    nodes = load_all_nodes()
    check_for_duplicate_slugs(nodes)
    check_for_duplicate_ids(nodes)
    return nodes, build_nodes_by_id(nodes)


def serialize_node_canonical(node: dict) -> str:
    """
    The one canonical JSON text representation of a Node: standard
    json.dump with fixed indentation, UTF-8/Hebrew characters written
    literally (not escaped), the field order exactly as the dict
    currently holds it, and a single trailing newline. Never includes
    the internal _sourceFile bookkeeping key.

    Deliberately does NOT try to preserve any hand-written formatting
    (like blank lines between sections) — every Node file, whether
    written by a person or by Sync, converges on this one predictable
    machine format. This is a deliberate simplicity choice: trying to
    preserve arbitrary human formatting is real complexity for little
    benefit, whereas "every file always looks the same" is easy to
    reason about at any scale.
    """
    to_write = {k: v for k, v in node.items() if k != _SOURCE_FILE_KEY}
    return json.dumps(to_write, ensure_ascii=False, indent=2) + "\n"


def node_content_changed(node: dict) -> bool:
    """
    True if writing `node` in its canonical form would actually change
    its file on disk (either the file doesn't exist yet, or its current
    bytes differ from the canonical serialization of `node`). Used to
    implement "only rewrite a Node file when something actually changed"
    without hand-tracking which individual fields were touched.
    """
    source_path = Path(node[_SOURCE_FILE_KEY])
    new_content = serialize_node_canonical(node)
    if not source_path.exists():
        return True
    return source_path.read_text(encoding="utf-8") != new_content


def write_node(node: dict) -> None:
    """
    Atomically write `node` back to its source file, in canonical form.
    Uses a temp-file-then-rename so a crash or interruption mid-write
    can never leave a half-written, corrupted Node file behind — the
    file on disk is always either the old complete version or the new
    complete version, never something in between.
    """
    source_path = Path(node[_SOURCE_FILE_KEY])
    new_content = serialize_node_canonical(node)
    tmp_path = source_path.with_suffix(source_path.suffix + ".tmp")
    tmp_path.write_text(new_content, encoding="utf-8")
    tmp_path.replace(source_path)  # atomic on POSIX filesystems
