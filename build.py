#!/usr/bin/env python3
"""
Knowledge Node build system.

Reads the shared template.html + site-config.json (global site data) +
Node data records (nodes/*.json, one file per node, Node Schema v1.0),
and produces static HTML files — no server, no database, no framework.
Each Node's optional "relatedNodeIds" field (up to 3 other Node ids)
drives its "Related Knowledge" section — see select_related_nodes()
and render_related_section() below.

This module is deliberately written as importable functions (not just a
CLI script), so a future Node-creation interface can call build_node()
or build_all_published() directly instead of shelling out to Python.

──────────────────────────────────────────────────────────────────────
CLI USAGE
──────────────────────────────────────────────────────────────────────

Build every published Node, the homepage, and the Medical Disclaimer
page (production):
    python3 build.py --all

Build a single Node by slug, for development/testing (ignores its
publishing status — drafts can be previewed this way). Also refreshes
the homepage + disclaimer page so links between pages work locally.
Related cards in the preview only ever show targets that are
themselves published, so the preview reflects what production would
actually render:
    python3 build.py --node does-a-gynecological-exam-hurt

Output always goes to dist/:
    dist/index.html                           (real homepage)
    dist/nodes/{slug}/index.html               (one per published Node)
    dist/medical-disclaimer/index.html         (permanent disclaimer page)

──────────────────────────────────────────────────────────────────────
ADDING A FUTURE NODE (until a real creation interface exists)
──────────────────────────────────────────────────────────────────────
    1. Create nodes/{new-slug}.json following Node Schema v1.0
       (copy an existing node file as a starting point).
    2. Optionally set "relatedNodeIds" to up to 3 existing Node ids.
    3. Run: python3 build.py --all
    4. Upload the contents of dist/ to GitHub as usual.
    No HTML editing required, ever.

──────────────────────────────────────────────────────────────────────
URL CONVENTION
──────────────────────────────────────────────────────────────────────
Clean, slug-based, folder-style URLs (an index.html inside a folder
named after the slug, so the URL itself has no ".html" in it):
    /                              -> homepage
    /nodes/{slug}/                 -> one specific Knowledge Node
    /medical-disclaimer/           -> the permanent disclaimer page
This was the convention already implied by the original project
(dist/nodes/{slug}/index.html) and is preserved unchanged here.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
NODES_DIR = BASE_DIR / "nodes"
DIST_DIR = BASE_DIR / "dist"

MAX_RELATED_CARDS = 3


# ──────────────────────────────────────────────────────────────────
# Node discovery
# ──────────────────────────────────────────────────────────────────

# Minimal structural shape every Node file must have, regardless of its
# publishing status. This catches malformed/incomplete Node data (e.g. a
# hand-edited JSON file missing a top-level section entirely) with a clear
# error, instead of an obscure KeyError deep inside rendering.
_REQUIRED_NODE_SECTIONS = ["id", "slug", "youtube", "classification", "clinical", "publishing"]


def load_all_nodes() -> list[dict]:
    """Load every node data record from nodes/*.json. Fails clearly on bad JSON."""
    nodes = []
    for path in sorted(NODES_DIR.glob("*.json")):
        try:
            node = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"BUILD FAILED — invalid JSON in {path}: {e}")

        if not isinstance(node, dict):
            raise SystemExit(f"BUILD FAILED — {path} must contain a JSON object, not {type(node).__name__}")

        missing = [section for section in _REQUIRED_NODE_SECTIONS if section not in node]
        if missing:
            raise SystemExit(
                f"BUILD FAILED — invalid Node data in {path}: "
                f"missing required section(s): {', '.join(missing)}"
            )
        if node.get("publishing", {}).get("status") not in ("published", "draft", "unpublished", "archived"):
            raise SystemExit(
                f"BUILD FAILED — invalid publication data in {path}: "
                f"publishing.status must be one of published/draft/unpublished/archived "
                f"(got {node.get('publishing', {}).get('status')!r})"
            )

        node["_sourceFile"] = str(path)
        nodes.append(node)
    return nodes


def check_for_duplicate_slugs(nodes: list[dict]) -> None:
    """Fail clearly and immediately if two node files share a slug."""
    seen: dict[str, str] = {}
    conflicts = []
    for node in nodes:
        slug = node["slug"]
        if slug in seen:
            conflicts.append((slug, seen[slug], node["_sourceFile"]))
        else:
            seen[slug] = node["_sourceFile"]
    if conflicts:
        lines = [f"  '{slug}' used in both {a} AND {b}" for slug, a, b in conflicts]
        raise SystemExit(
            "BUILD FAILED — duplicate Node slug(s) detected:\n" + "\n".join(lines)
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
            conflicts.append((node_id, seen[node_id], node["_sourceFile"]))
        else:
            seen[node_id] = node["_sourceFile"]
    if conflicts:
        lines = [f"  '{node_id}' used in both {a} AND {b}" for node_id, a, b in conflicts]
        raise SystemExit(
            "BUILD FAILED — duplicate Node id(s) detected:\n" + "\n".join(lines)
        )


def validate_for_publication(node: dict) -> list[str]:
    """
    Returns a list of human-readable problems for a Node that claims
    publishing.status == 'published'. Empty list means it's valid.
    This is the single source of truth for "is this Node allowed to be
    published" — it must never be duplicated as stored data on the Node.
    """
    errors = []
    source = node.get("_sourceFile", "?")

    if not node.get("id"):
        errors.append("id is missing or empty")

    if not node.get("slug"):
        errors.append("slug is missing or empty")

    yt = node.get("youtube", {})
    if not yt.get("videoId"):
        errors.append("youtube.videoId is missing or empty")
    if not yt.get("title"):
        errors.append("youtube.title is missing or empty")
    if not yt.get("description"):
        errors.append("youtube.description is missing or empty")

    classification = node.get("classification", {})
    primary_category = classification.get("primaryCategoryId")
    if primary_category is None or primary_category == "unassigned":
        errors.append("classification.primaryCategoryId must be set to a real category (currently null/'unassigned')")
    if classification.get("priority") not in ("high", "normal", "low"):
        errors.append("classification.priority must be 'high', 'normal', or 'low' (currently missing/invalid)")

    clinical = node.get("clinical", {})
    if not clinical.get("lastReviewedAt"):
        errors.append("clinical.lastReviewedAt is missing")
    if clinical.get("status") not in ("current", "needs-review", "outdated"):
        errors.append("clinical.status must be 'current', 'needs-review', or 'outdated' (currently missing/invalid)")

    publishing = node.get("publishing", {})
    if not publishing.get("publishedAt"):
        errors.append("publishing.publishedAt is missing")

    if errors:
        errors = [f"[{node.get('slug', '?')} — {source}] {e}" for e in errors]

    return errors


def validate_related_node_ids(node: dict, nodes_by_id: dict[str, dict],
                               enforce_published_targets: bool) -> list[str]:
    """
    Validates the optional "relatedNodeIds" field on a single Node.
    Returns a list of human-readable problems; empty list means valid.
    Kept as its own function (mirrors validate_for_publication) so it can
    be called independently and doesn't entangle Related-specific rules
    with the unrelated publication-readiness checks above.

    enforce_published_targets=True is used for the production build: a
    published Node that points at a Node which is not itself published
    is treated as a build error (manual Related data is meant to be
    exact, not silently drop a card with no explanation).
    """
    errors = []
    slug = node.get("slug", "?")
    source = node.get("_sourceFile", "?")
    own_id = node.get("id")

    related_ids = node.get("relatedNodeIds", [])
    if related_ids is None:
        related_ids = []

    if not isinstance(related_ids, list):
        return [
            f"[{slug} — {source}] relatedNodeIds must be an array "
            f"(got {type(related_ids).__name__})"
        ]

    if len(related_ids) > MAX_RELATED_CARDS:
        errors.append(
            f"[{slug} — {source}] relatedNodeIds has {len(related_ids)} entries, "
            f"maximum allowed is {MAX_RELATED_CARDS}"
        )

    seen_ids: set[str] = set()
    for related_id in related_ids:
        if not isinstance(related_id, str):
            errors.append(
                f"[{slug} — {source}] relatedNodeIds contains a non-string value: {related_id!r}"
            )
            continue

        if related_id == own_id:
            errors.append(
                f"[{slug} — {source}] relatedNodeIds contains id '{related_id}', "
                "which is the Node's own id (a Node cannot be related to itself)"
            )
            continue

        if related_id in seen_ids:
            errors.append(
                f"[{slug} — {source}] relatedNodeIds contains duplicate id '{related_id}'"
            )
            continue
        seen_ids.add(related_id)

        target = nodes_by_id.get(related_id)
        if target is None:
            errors.append(
                f"[{slug} — {source}] relatedNodeIds contains id '{related_id}', "
                "which does not match any existing Node"
            )
            continue

        if enforce_published_targets and target.get("publishing", {}).get("status") != "published":
            target_status = target.get("publishing", {}).get("status", "?")
            errors.append(
                f"[{slug} — {source}] relatedNodeIds contains id '{related_id}' "
                f"(Node '{target.get('slug', '?')}'), which is not published "
                f"(status: {target_status}) — a published Node cannot list an "
                "unpublished Node as Related"
            )

    return errors


def select_related_nodes(node: dict, nodes_by_id: dict[str, dict],
                          published_only: bool) -> list[dict]:
    """
    Returns an ordered list of the actual related Node records for
    `node`, ready to be rendered.

    This is the ONLY place that decides *which* Nodes are related.
    It currently just reads the manual "relatedNodeIds" field, in the
    order the ids appear. This function is the intended seam for
    swapping in automatic category/tag-based selection later — its
    signature and return type (a list of real Node dicts) would not
    need to change, so render_related_section() would not need to
    change either.

    Rules enforced here (defensively — real invalid data should already
    have failed validate_related_node_ids() at production build time,
    but this function must never crash or misrender for a preview of a
    draft Node with imperfect/absent data):
      - never include the Node itself
      - only Nodes that actually exist
      - only published Nodes, when published_only=True
      - never the same Node twice
      - capped at MAX_RELATED_CARDS, in declaration order
    """
    own_id = node.get("id")
    related_ids = node.get("relatedNodeIds") or []
    if not isinstance(related_ids, list):
        return []

    selected: list[dict] = []
    seen_ids: set[str] = set()
    for related_id in related_ids:
        if not isinstance(related_id, str):
            continue
        if related_id == own_id:
            continue
        if related_id in seen_ids:
            continue
        target = nodes_by_id.get(related_id)
        if target is None:
            continue
        if published_only and target.get("publishing", {}).get("status") != "published":
            continue
        seen_ids.add(related_id)
        selected.append(target)
        if len(selected) == MAX_RELATED_CARDS:
            break

    return selected


# ──────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────

def make_snippet(text: str, max_chars: int = 160) -> str:
    """
    Shared helper for producing a short preview snippet from a longer
    description, so this truncation logic exists in exactly one place.
    Used by both the homepage's Node cards (render_node_card_html) and
    the Related Knowledge cards (render_related_section).
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def render_related_section(related_nodes: list[dict], site_config: dict) -> str:
    """
    Pure rendering: takes an already-selected list of real Node records
    (see select_related_nodes) and produces the Related Knowledge
    section HTML. Contains no selection logic at all — it only knows
    how to turn Nodes into cards. Cards are text-only (title +
    description snippet) — no thumbnail/icon.

    - 0 items -> return "" (no heading, no empty grid box)
    - 1-3 items -> render exactly that many (grid naturally fills from the
      right in RTL, leaving empty space on the left — no extra CSS needed)
    - callers are expected to already have capped the list at 3; this
      function caps again defensively so it can never over-render.
    """
    items = related_nodes[:MAX_RELATED_CARDS]
    if not items:
        return ""  # zero real items -> omit the whole section, no empty box

    cards_html = []
    for related_node in items:
        title = html.escape(related_node["youtube"]["title"], quote=True)
        description = html.escape(make_snippet(related_node["youtube"]["description"]), quote=True)
        href = f'/nodes/{html.escape(related_node["slug"], quote=True)}/'
        cards_html.append(
            f'      <a class="related-card" href="{href}">\n'
            f'        <div class="related-title">{title}</div>\n'
            f'        <div class="related-desc">{description}</div>\n'
            '      </a>'
        )
    cards_joined = "\n".join(cards_html)
    label = html.escape(site_config["uiLabels"]["relatedSectionLabel"], quote=True)

    return (
        '  <section class="related-section">\n'
        f'    <p class="section-label">{label}</p>\n'
        '    <div class="related-grid">\n'
        f'{cards_joined}\n'
        '    </div>\n'
        '  </section>'
    )


def render_node_html(node: dict, template: str, site_config: dict,
                      nodes_by_id: dict[str, dict], published_only: bool) -> str:
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    video_id = node["youtube"]["videoId"]

    # thumbnailUrl is real YouTube-sourced data and must be used if present.
    # Derivation from videoId is only a FALLBACK for missing data, never a replacement.
    thumbnail_url = node["youtube"].get("thumbnailUrl") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    thumbnail_fallback_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    page_title = f'{node["youtube"]["title"]} | {site_config["header"]["name"]}'
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()

    related_nodes = select_related_nodes(node, nodes_by_id, published_only=published_only)

    tokens = {
        "{{PAGE_TITLE}}": page_title,
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{NODE_TITLE}}": node["youtube"]["title"],
        "{{NODE_DESCRIPTION}}": node["youtube"]["description"],
        "{{VIDEO_ID}}": video_id,
        "{{VIDEO_THUMBNAIL_URL}}": thumbnail_url,
        "{{VIDEO_THUMBNAIL_FALLBACK_URL}}": thumbnail_fallback_url,
        "{{UI_READ_MORE}}": site_config["uiLabels"]["readMore"],
        "{{UI_SHOW_LESS}}": site_config["uiLabels"]["showLess"],
        "{{UI_WATCH_LABEL}}": site_config["uiLabels"]["watchSectionLabel"],
        "{{UI_VIDEO_ENDED}}": site_config["uiLabels"]["videoEnded"],
        "{{UI_CLOSE_ARIA}}": site_config["uiLabels"]["closeVideoAriaLabel"],
        "{{MORE_LINK_TEXT}}": site_config["moreLinkButton"]["text"],
        "{{MORE_LINK_URL}}": site_config["moreLinkButton"]["url"],
        "{{HOME_NAV_TEXT}}": site_config["homeNavBar"]["text"],
        "{{HOME_NAV_URL}}": site_config["homeNavBar"]["url"],
        "{{DISCLAIMER_ICON}}": site_config["disclaimer"]["icon"],
        "{{DISCLAIMER_SHORT_TEXT}}": site_config["disclaimer"]["shortText"],
        "{{DISCLAIMER_LINK_PREFIX}}": site_config["disclaimer"]["linkPrefix"],
        "{{DISCLAIMER_LINK_TEXT}}": site_config["disclaimer"]["linkText"],
        "{{DISCLAIMER_LINK_URL}}": site_config["disclaimer"]["linkUrl"],
        "{{END_REPLAY_LABEL}}": site_config["endOfVideoButtons"]["replay"],
        "{{END_CLOSE_LABEL}}": site_config["endOfVideoButtons"]["close"],
        "{{RELATED_SECTION_HTML}}": render_related_section(related_nodes, site_config),
    }

    output = template
    for token, value in tokens.items():
        output = output.replace(token, value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", output)
    if remaining:
        raise SystemExit(f"BUILD FAILED — unresolved tokens for node '{node['slug']}': {set(remaining)}")

    return output


# ──────────────────────────────────────────────────────────────────
# Build orchestration
# ──────────────────────────────────────────────────────────────────

def build_node(node: dict, nodes_by_id: dict[str, dict], published_only: bool = True) -> Path:
    """Build a single Node to dist/nodes/{slug}/index.html. Returns the output path."""
    template = (BASE_DIR / "template.html").read_text(encoding="utf-8")
    site_config = json.loads((BASE_DIR / "site-config.json").read_text(encoding="utf-8"))

    html_out = render_node_html(node, template, site_config, nodes_by_id, published_only=published_only)

    out_dir = DIST_DIR / "nodes" / node["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


def render_node_card_html(node: dict) -> str:
    title = node["youtube"]["title"]
    snippet = make_snippet(node["youtube"]["description"])
    return (
        f'    <a class="node-card" href="/nodes/{node["slug"]}/">\n'
        f'      <p class="node-card-title">{title}</p>\n'
        f'      <p class="node-card-desc">{snippet}</p>\n'
        '    </a>'
    )


def build_homepage(published_nodes: list[dict]) -> Path:
    """
    Build the real dist/index.html homepage: shared header/branding, a
    short intro, and a list of every published Knowledge Node.

    Knowledge Centers and a search bar are NOT implemented — they need a
    topic/category data model that does not exist yet, and inventing one
    is out of scope here per "do not redesign the data model unless
    essential". This homepage is the real, working, non-placeholder entry
    point required for this build; Knowledge Centers remain a documented
    future step.
    """
    template = (BASE_DIR / "homepage-template.html").read_text(encoding="utf-8")
    site_config = json.loads((BASE_DIR / "site-config.json").read_text(encoding="utf-8"))
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    homepage_cfg = site_config["homepage"]
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()

    if published_nodes:
        list_html = '  <div class="node-list">\n' + "\n".join(
            render_node_card_html(n) for n in published_nodes
        ) + "\n  </div>"
    else:
        list_html = f'  <div class="empty-state">{homepage_cfg["emptyStateText"]}</div>'

    tokens = {
        "{{PAGE_TITLE}}": homepage_cfg["pageTitle"],
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{HOMEPAGE_EYEBROW}}": homepage_cfg["eyebrow"],
        "{{HOMEPAGE_TITLE}}": homepage_cfg["title"],
        "{{HOMEPAGE_INTRO}}": homepage_cfg["intro"],
        "{{HOMEPAGE_LIST_LABEL}}": homepage_cfg["listLabel"],
        "{{NODES_LIST_HTML}}": list_html,
        "{{DISCLAIMER_ICON}}": site_config["disclaimer"]["icon"],
        "{{DISCLAIMER_SHORT_TEXT}}": site_config["disclaimer"]["shortText"],
        "{{DISCLAIMER_LINK_PREFIX}}": site_config["disclaimer"]["linkPrefix"],
        "{{DISCLAIMER_LINK_TEXT}}": site_config["disclaimer"]["linkText"],
        "{{DISCLAIMER_LINK_URL}}": site_config["disclaimer"]["linkUrl"],
    }

    html = template
    for token, value in tokens.items():
        html = html.replace(token, value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if remaining:
        raise SystemExit(f"BUILD FAILED — unresolved tokens on homepage: {set(remaining)}")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DIST_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def build_disclaimer_page() -> Path:
    """
    Build the permanent Medical Disclaimer page at dist/medical-disclaimer/index.html.
    Uses the shared header/branding, contains the full approved Hebrew
    disclaimer text, and a link back to the homepage. No video, no
    Related Knowledge cards, no "All content in this topic" button.
    """
    template = (BASE_DIR / "disclaimer-template.html").read_text(encoding="utf-8")
    site_config = json.loads((BASE_DIR / "site-config.json").read_text(encoding="utf-8"))
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    disclaimer_cfg = site_config["medicalDisclaimerPage"]
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()

    paragraphs_html = "\n".join(f"    <p>{p}</p>" for p in disclaimer_cfg["paragraphs"])

    tokens = {
        "{{PAGE_TITLE}}": disclaimer_cfg["pageTitle"],
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{HOME_NAV_TEXT}}": site_config["homeNavBar"]["text"],
        "{{HOME_NAV_URL}}": site_config["homeNavBar"]["url"],
        "{{DISCLAIMER_PAGE_TITLE}}": disclaimer_cfg["title"],
        "{{DISCLAIMER_PARAGRAPHS_HTML}}": paragraphs_html,
        "{{DISCLAIMER_LAST_UPDATED}}": disclaimer_cfg["lastUpdated"],
    }

    html = template
    for token, value in tokens.items():
        html = html.replace(token, value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if remaining:
        raise SystemExit(f"BUILD FAILED — unresolved tokens on disclaimer page: {set(remaining)}")

    out_dir = DIST_DIR / "medical-disclaimer"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def build_all_published():
    """Build every Node whose publishing.status == 'published'. Excludes draft/archived."""
    all_nodes = load_all_nodes()
    check_for_duplicate_slugs(all_nodes)
    check_for_duplicate_ids(all_nodes)
    nodes_by_id = {n["id"]: n for n in all_nodes if n.get("id")}

    published = [n for n in all_nodes if n["publishing"]["status"] == "published"]
    excluded = [n for n in all_nodes if n["publishing"]["status"] != "published"]

    # Every Node claiming "published" status must pass full validation.
    # This is checked at build time, not stored as data on the Node.
    all_errors = []
    for node in published:
        all_errors.extend(validate_for_publication(node))
    for node in published:
        all_errors.extend(validate_related_node_ids(node, nodes_by_id, enforce_published_targets=True))
    if all_errors:
        raise SystemExit(
            "BUILD FAILED — the following Node(s) are marked 'published' but are "
            "invalid:\n" + "\n".join(f"  - {e}" for e in all_errors)
        )

    built_paths = [build_node(n, nodes_by_id, published_only=True) for n in published]
    build_homepage(published)
    build_disclaimer_page()

    print(f"Built {len(published)} published Node(s).")
    if excluded:
        print(f"Excluded {len(excluded)} Node(s) not in 'published' status:")
        for n in excluded:
            print(f"  - {n['slug']} (status: {n['publishing']['status']})")
    print("Built homepage: dist/index.html")
    print("Built Medical Disclaimer page: dist/medical-disclaimer/index.html")

    return built_paths


def build_single_for_dev(slug: str):
    """
    Build one Node by slug regardless of publishing status, for
    dev/testing/preview. Related cards in the preview only ever show
    targets that are themselves published, so the preview reflects
    what production would actually render.
    """
    all_nodes = load_all_nodes()
    check_for_duplicate_slugs(all_nodes)
    check_for_duplicate_ids(all_nodes)
    nodes_by_id = {n["id"]: n for n in all_nodes if n.get("id")}

    matches = [n for n in all_nodes if n["slug"] == slug]
    if not matches:
        raise SystemExit(f"No node found with slug '{slug}'")
    out_path = build_node(matches[0], nodes_by_id, published_only=True)

    # Also refresh homepage + disclaimer page so their links work while
    # previewing locally. Homepage only ever lists real 'published' Nodes,
    # even in dev preview of a draft.
    published = [n for n in all_nodes if n["publishing"]["status"] == "published"]
    build_homepage(published)
    build_disclaimer_page()

    print(f"Built dev preview: {out_path}")
    print("Also refreshed dist/index.html and dist/medical-disclaimer/index.html")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Knowledge Node build system")
    parser.add_argument("--all", action="store_true", help="Build all published Nodes (production)")
    parser.add_argument("--node", metavar="SLUG", help="Build a single Node by slug, for dev/testing/preview (ignores publishing status)")
    args = parser.parse_args()

    if args.all:
        build_all_published()
    elif args.node:
        build_single_for_dev(args.node)
    else:
        print(__doc__)
        sys.exit(1)
