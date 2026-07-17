#!/usr/bin/env python3
"""
Knowledge Node build system.

Reads the shared template.html + site-config.json (global site data) +
Node data records (nodes/*.json, one file per node, Node Schema v1.0) +
related-temp.json (DEVELOPMENT-ONLY placeholder related-content), and
produces static HTML files — no server, no database, no framework.

This module is deliberately written as importable functions (not just a
CLI script), so a future Node-creation interface can call build_node()
or build_all_published() directly instead of shelling out to Python.

──────────────────────────────────────────────────────────────────────
CLI USAGE
──────────────────────────────────────────────────────────────────────

Build every published Node, the homepage, and the Medical Disclaimer
page (production):
    python3 build.py --all

Same, WITH development related-content fixtures visible on Node pages
(for visual testing only — never use this output for real deploys):
    python3 build.py --all --dev

Build a single Node by slug, for development/testing (ignores its
publishing status — drafts can be previewed this way). Also refreshes
the homepage + disclaimer page so links between pages work locally:
    python3 build.py --node does-a-gynecological-exam-hurt --dev

Output always goes to dist/:
    dist/index.html                           (real homepage)
    dist/nodes/{slug}/index.html               (one per published Node)
    dist/medical-disclaimer/index.html         (permanent disclaimer page)

──────────────────────────────────────────────────────────────────────
ADDING A FUTURE NODE (until a real creation interface exists)
──────────────────────────────────────────────────────────────────────
    1. Create nodes/{new-slug}.json following Node Schema v1.0
       (copy an existing node file as a starting point).
    2. Run: python3 build.py --all
    3. Upload the contents of dist/ to GitHub as usual.
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
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
NODES_DIR = BASE_DIR / "nodes"
DIST_DIR = BASE_DIR / "dist"


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


# ──────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────

def render_related_section(dev_fixtures: bool, site_config: dict, related_temp: dict) -> str:
    """
    Related content is system-generated behavior (real scoring against
    real published Nodes), not yet built. Until it exists:
      - dev_fixtures=True  -> render the labeled DEVELOPMENT fixture cards,
                               for visual testing only.
      - dev_fixtures=False -> omit the section entirely (production).
    Cards are text-only (title + description snippet) — no thumbnail/icon.

    IMPORTANT for whenever real related-content data exists: this function
    must NEVER pad the list to force exactly 3 cards, and must omit the
    ENTIRE section (heading included) when there are zero real items.
    - 0 items -> return "" (no heading, no empty grid box)
    - 1-3 items -> render exactly that many (grid naturally fills from the
      right in RTL, leaving empty space on the left — no extra CSS needed)
    - 4+ items -> cap at the first 3 (the layout is designed for 3 max)
    """
    if not dev_fixtures:
        return ""

    items = related_temp["placeholderCards"][:3]  # never show more than 3
    if not items:
        return ""  # zero real items -> omit the whole section, no empty box

    cards_html = []
    for card in items:
        cards_html.append(
            '      <a class="related-card" href="#" onclick="return false;">\n'
            f'        <div class="related-title">{card["title"]}</div>\n'
            f'        <div class="related-desc">{card["description"]}</div>\n'
            '      </a>'
        )
    cards_joined = "\n".join(cards_html)
    label = site_config["uiLabels"]["relatedSectionLabel"]

    return (
        '  <!-- DEVELOPMENT FIXTURE — placeholder related content, not real Nodes. -->\n'
        '  <section class="related-section">\n'
        f'    <p class="section-label">{label}</p>\n'
        '    <div class="related-grid">\n'
        f'{cards_joined}\n'
        '    </div>\n'
        '  </section>'
    )


def render_node_html(node: dict, template: str, site_config: dict,
                      related_temp: dict, dev_fixtures: bool) -> str:
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    video_id = node["youtube"]["videoId"]

    # thumbnailUrl is real YouTube-sourced data and must be used if present.
    # Derivation from videoId is only a FALLBACK for missing data, never a replacement.
    thumbnail_url = node["youtube"].get("thumbnailUrl") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    thumbnail_fallback_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    page_title = f'{node["youtube"]["title"]} | {site_config["header"]["name"]}'
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()

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
        "{{RELATED_SECTION_HTML}}": render_related_section(dev_fixtures, site_config, related_temp),
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

def build_node(node: dict, dev_fixtures: bool = False) -> Path:
    """Build a single Node to dist/nodes/{slug}/index.html. Returns the output path."""
    template = (BASE_DIR / "template.html").read_text(encoding="utf-8")
    site_config = json.loads((BASE_DIR / "site-config.json").read_text(encoding="utf-8"))
    related_temp = json.loads((BASE_DIR / "related-temp.json").read_text(encoding="utf-8"))

    html = render_node_html(node, template, site_config, related_temp, dev_fixtures)

    out_dir = DIST_DIR / "nodes" / node["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_node_card_html(node: dict) -> str:
    title = node["youtube"]["title"]
    description = node["youtube"]["description"]
    snippet = description if len(description) <= 160 else description[:160].rstrip() + "…"
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


def build_all_published(dev_fixtures: bool = False):
    """Build every Node whose publishing.status == 'published'. Excludes draft/archived."""
    all_nodes = load_all_nodes()
    check_for_duplicate_slugs(all_nodes)

    published = [n for n in all_nodes if n["publishing"]["status"] == "published"]
    excluded = [n for n in all_nodes if n["publishing"]["status"] != "published"]

    # Every Node claiming "published" status must pass full validation.
    # This is checked at build time, not stored as data on the Node.
    all_errors = []
    for node in published:
        all_errors.extend(validate_for_publication(node))
    if all_errors:
        raise SystemExit(
            "BUILD FAILED — the following Node(s) are marked 'published' but are "
            "missing required fields:\n" + "\n".join(f"  - {e}" for e in all_errors)
        )

    built_paths = [build_node(n, dev_fixtures=dev_fixtures) for n in published]
    build_homepage(published)
    build_disclaimer_page()

    print(f"Built {len(published)} published Node(s).")
    if excluded:
        print(f"Excluded {len(excluded)} Node(s) not in 'published' status:")
        for n in excluded:
            print(f"  - {n['slug']} (status: {n['publishing']['status']})")
    print("Built homepage: dist/index.html")
    print("Built Medical Disclaimer page: dist/medical-disclaimer/index.html")
    if dev_fixtures:
        print("NOTE: built WITH development related-content fixtures visible. Do not deploy this output.")

    return built_paths


def build_single_for_dev(slug: str, dev_fixtures: bool = True):
    """Build one Node by slug regardless of publishing status, for dev/testing/preview."""
    all_nodes = load_all_nodes()
    check_for_duplicate_slugs(all_nodes)
    matches = [n for n in all_nodes if n["slug"] == slug]
    if not matches:
        raise SystemExit(f"No node found with slug '{slug}'")
    out_path = build_node(matches[0], dev_fixtures=dev_fixtures)

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
    parser.add_argument("--node", metavar="SLUG", help="Build a single Node by slug, for dev/testing")
    parser.add_argument("--dev", action="store_true", help="Include development related-content fixtures")
    args = parser.parse_args()

    if args.all:
        build_all_published(dev_fixtures=args.dev)
    elif args.node:
        build_single_for_dev(args.node, dev_fixtures=args.dev)
    else:
        print(__doc__)
        sys.exit(1)
