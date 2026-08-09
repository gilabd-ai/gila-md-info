#!/usr/bin/env python3
"""
Knowledge Node build system.

Reads the shared template.html + site-config.json (global site data) +
Node data records (nodes/*.json, one file per node, Node Schema v1.0),
and produces static HTML files — no server, no database, no framework.
Each Node's "Related Knowledge" section is computed automatically at
build time from its classification (shared categories/tags) and
priority — see select_related_nodes() and render_related_section()
below. A small browser-side script in template.html then reorders/
subsets that same ranked list per-visitor using localStorage, without
ever re-ranking it — see template.html's inline <script> block.

This module is deliberately written as importable functions (not just a
CLI script), so a future Node-creation interface can call build_node()
or build_all_published() directly instead of shelling out to Python.

──────────────────────────────────────────────────────────────────────
THREE-MODULE ARCHITECTURE
──────────────────────────────────────────────────────────────────────
- node_store.py   — shared foundation: reading/writing Node files.
                     Imports nothing from either file below.
- build.py        — THIS FILE. Rendering only (HTML generation).
                     Imports node_store. Never imports youtube_sync,
                     never imports `requests` — Build cannot reach the
                     network, which you can verify just by reading the
                     imports at the top of this file.
- youtube_sync.py — talks to the YouTube Data API and updates Node
                     files. Imports node_store. Never imports build.

Sync and Build are fully independent commands, each with its own CLI
entry point, so they can later be wired to two separate UI buttons
without any code reorganization.

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
    python3 build.py --node template-node

Output always goes to dist/:
    dist/index.html                           (real homepage)
    dist/nodes/{slug}/index.html               (one per published Node)
    dist/medical-disclaimer/index.html         (permanent disclaimer page)

──────────────────────────────────────────────────────────────────────
ADDING A FUTURE NODE (until a real creation interface exists)
──────────────────────────────────────────────────────────────────────
    1. Create nodes/{new-slug}.json following Node Schema v1.0
       (copy an existing node file as a starting point).
    2. Set classification.primaryCategoryIds / primaryTagIds /
       secondaryTagIds using only IDs already present in
       data/code-categories-and-tags.json, and set a top-level priority
       (0-3). Related Knowledge is then computed automatically — there
       is no manual related-Node field to fill in.
    3. Run: python3 build.py --all
    4. Upload the contents of dist/ to GitHub as usual.
    No HTML editing required, ever.

Separately, run `python3 youtube_sync.py --node {slug}` (see that file's
own docstring) to pull real title/description/thumbnail data from
YouTube into a Node before publishing it — Build itself never does this.

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
from typing import Optional

import node_store

BASE_DIR = Path(__file__).parent
DIST_DIR = BASE_DIR / "dist"

MAX_RELATED_CARDS = 3          # how many cards are ever displayed on a page
MAX_RELATED_CANDIDATES = 10    # how many ranked candidates are computed/exposed to the browser

# Recommendation-priority bonus added to a candidate's relatedness score.
# Priority 0 ("never recommend") is excluded before scoring — never looked up here.
PRIORITY_BONUS = {1: 100, 2: 50, 3: 0}


# ──────────────────────────────────────────────────────────────────
# Publication & Classification validation
# ──────────────────────────────────────────────────────────────────
# Node loading, duplicate-slug/id checks, and the id lookup all now
# live in node_store.py (shared with youtube_sync.py). This file only
# contains rendering-specific validation from here on.

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

    clinical = node.get("clinical", {})
    if not clinical.get("lastReviewedAt"):
        errors.append("clinical.lastReviewedAt is missing")

    publishing = node.get("publishing", {})
    if not publishing.get("publishedAt"):
        errors.append("publishing.publishedAt is missing")

    if errors:
        errors = [f"[{node.get('slug', '?')} — {source}] {e}" for e in errors]

    return errors


def load_categories_and_tags() -> dict:
    """
    Loads data/code-categories-and-tags.json — the single canonical
    registry of approved category/tag IDs, plus the internal-category
    marker set and the Hebrew Topic-name mapping. No code anywhere else
    is allowed to invent or guess an id, or a Hebrew label, that isn't
    present here.

    "internalCategoryIds" marks categories reserved for technical/
    editorial Nodes only (currently just "template-node") — never real
    public medical content. A Node may use an internal category, but it
    can never become a public Topic: see _is_internal_only() and
    derive_active_topics(). Self-consistency is enforced here, once, so
    every caller gets it for free: every internalCategoryIds entry must
    actually exist in categories.

    "categoryLabelsHe" is the approved Hebrew display name for every
    PUBLIC (non-internal) category — the only names visitors ever see;
    English category ids never reach the public HTML. "categoriesOrdered"
    preserves the registry's own array order (the editorial display
    order — see derive_active_topics()), unlike "categoryIds" which is a
    plain set with no defined order.

    A human-readable copy of this same data lives at
    docs/gila-categories-and-tags.html (generated by
    generate_categories_doc.py) — that page is a read-only reference for
    the site owner, never a second source of truth.
    """
    path = BASE_DIR / "data" / "code-categories-and-tags.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    category_ids = set(data["categories"])
    internal_category_ids = set(data.get("internalCategoryIds", []))
    category_labels_he = data.get("categoryLabelsHe", {})

    errors = []
    unknown_internal = internal_category_ids - category_ids
    if unknown_internal:
        errors.append(f"internalCategoryIds references unknown category id(s): {sorted(unknown_internal)}")
    unknown_labeled = set(category_labels_he) - category_ids
    if unknown_labeled:
        errors.append(f"categoryLabelsHe references unknown category id(s): {sorted(unknown_labeled)}")
    empty_labels = [k for k, v in category_labels_he.items() if not isinstance(v, str) or not v.strip()]
    if empty_labels:
        errors.append(f"categoryLabelsHe has empty/invalid label(s) for: {sorted(empty_labels)}")
    public_category_ids = category_ids - internal_category_ids
    missing_labels = public_category_ids - set(category_labels_he)
    if category_labels_he and missing_labels:
        errors.append(f"public categories missing a categoryLabelsHe entry: {sorted(missing_labels)}")
    if errors:
        raise SystemExit("FAILED — data/code-categories-and-tags.json is inconsistent:\n" +
                          "\n".join(f"  - {e}" for e in errors))

    return {
        "categoryIds": category_ids,
        "categoriesOrdered": data["categories"],
        "tagIds": set(data["tags"]),
        "internalCategoryIds": internal_category_ids,
        "categoryLabelsHe": category_labels_he,
    }


# classification/priority fields that no longer exist as of the automatic
# Related Knowledge upgrade — kept as their own list so a Node file that
# still has old data fails with a clear, specific message instead of
# being silently ignored.
_DEPRECATED_TOP_LEVEL_FIELDS = ["relatedNodeIds"]
_DEPRECATED_CLASSIFICATION_FIELDS = ["primaryCategoryId", "additionalCategoryIds", "tagIds", "priority"]


def validate_classification_and_priority(node: dict, registry: dict) -> list[str]:
    """
    Validates a single Node's "classification" object and top-level
    "priority" field. Returns a list of human-readable problems; empty
    list means valid. Kept as its own function (mirrors
    validate_for_publication) so it can be called independently and is
    the one source of truth for this data's validity — mirrors the role
    validate_related_node_ids() used to play for the now-removed manual
    Related Knowledge field.
    """
    errors = []
    slug = node.get("slug", "?")
    source = node.get("_sourceFile", "?")
    classification = node.get("classification", {})

    for field in _DEPRECATED_TOP_LEVEL_FIELDS:
        if field in node:
            errors.append(f"[{slug} — {source}] deprecated field '{field}' must be removed")
    for field in _DEPRECATED_CLASSIFICATION_FIELDS:
        if field in classification:
            errors.append(f"[{slug} — {source}] deprecated field 'classification.{field}' must be removed")

    def _check_id_array(field_name: str, allowed_ids: set) -> set:
        value = classification.get(field_name, [])
        if not isinstance(value, list):
            errors.append(
                f"[{slug} — {source}] classification.{field_name} must be an array "
                f"(got {type(value).__name__})"
            )
            return set()
        seen: set[str] = set()
        for v in value:
            if not isinstance(v, str):
                errors.append(
                    f"[{slug} — {source}] classification.{field_name} contains a non-string value: {v!r}"
                )
                continue
            if v in seen:
                errors.append(
                    f"[{slug} — {source}] classification.{field_name} contains duplicate id '{v}'"
                )
                continue
            seen.add(v)
            if v not in allowed_ids:
                errors.append(
                    f"[{slug} — {source}] classification.{field_name} references unknown id '{v}' "
                    "(not present in data/code-categories-and-tags.json)"
                )
        return seen

    category_ids = _check_id_array("primaryCategoryIds", registry["categoryIds"])
    primary_tag_ids = _check_id_array("primaryTagIds", registry["tagIds"])
    secondary_tag_ids = _check_id_array("secondaryTagIds", registry["tagIds"])

    for tag in primary_tag_ids & secondary_tag_ids:
        errors.append(
            f"[{slug} — {source}] tag '{tag}' cannot be listed in both "
            "primaryTagIds and secondaryTagIds on the same Node"
        )

    if node.get("publishing", {}).get("status") == "published" and not category_ids:
        errors.append(f"[{slug} — {source}] classification.primaryCategoryIds must contain at least one category")

    priority = node.get("priority")
    if priority not in (0, 1, 2, 3):
        errors.append(f"[{slug} — {source}] priority must be 0, 1, 2, or 3 (currently missing/invalid: {priority!r})")

    return errors


def ineligible_candidate_reason(candidate: dict, published_only: bool) -> Optional[str]:
    """
    Returns a short, human-readable reason `candidate` can never be
    recommended as anyone's Related Knowledge (used both to SKIP it in
    score_related_candidates() below, and — the same check, so it can
    never drift from what production actually does — to explain on the
    Editorial Node Dashboard why a given Node is excluded). Returns None
    when the candidate has no such blanket exclusion (it may still fail
    to match any specific source Node on category/tag overlap, which is
    a separate, per-pair concern handled in score_related_candidates()).
    """
    status = candidate.get("publishing", {}).get("status")
    if status == "draft":
        return "draft"
    if published_only and status != "published":
        return f"not published (status: {status})"
    if candidate.get("youtube", {}).get("availability") == "unavailable":
        return "video unavailable"
    priority = candidate.get("priority")
    if priority == 0:
        return "priority 0 (never recommend)"
    return None


def score_related_candidates(node: dict, nodes_by_id: dict[str, dict],
                              published_only: bool) -> list[dict]:
    """
    The one place that computes Related Knowledge relatedness — both for
    the public site (via select_related_nodes() below, a thin wrapper
    around this) and for the Editorial Node Dashboard, so the two can
    never independently drift apart.

    Returns up to MAX_RELATED_CANDIDATES entries, best first, each as
    {"node": candidate_dict, "score": int, "breakdown": [{"label", "points"}, ...]}
    where sum(b["points"] for b in breakdown) == score, always.

    A candidate is eligible only if ALL of:
      - it is not `node` itself
      - ineligible_candidate_reason() returns None (not draft, published
        when published_only=True, video not unavailable, priority != 0)
      - it shares at least one primaryCategoryId, primaryTagId, or
        secondaryTagId with `node` — priority alone never qualifies it

    Score = tag_score + 50 * |shared primaryCategoryIds| + priority
    bonus. tag_score: for every tag id shared between `node` and the
    candidate (present in either's primary or secondary set), +100 if
    it's primary on both sides, otherwise +50 (covers primary<->secondary
    and secondary<->secondary matches — the topic is still genuinely
    shared, just not a primary topic for both Nodes). Breakdown lines
    for shared tags/categories are emitted in sorted-id order (not set
    iteration order) so output is deterministic/reproducible run to run.

    Ties preserve nodes_by_id's iteration order (the order
    node_store.load_all_nodes() loaded files in — alphabetical by slug):
    Python's sort is documented-stable even with reverse=True, so this
    is a deterministic, well-defined "existing order", not an arbitrary
    tie-break.
    """
    own_id = node.get("id")
    classification = node.get("classification", {})
    own_categories = set(classification.get("primaryCategoryIds") or [])
    own_primary_tags = set(classification.get("primaryTagIds") or [])
    own_secondary_tags = set(classification.get("secondaryTagIds") or [])
    own_all_tags = own_primary_tags | own_secondary_tags

    scored: list[tuple[int, dict]] = []
    for candidate in nodes_by_id.values():
        if candidate.get("id") == own_id:
            continue
        if ineligible_candidate_reason(candidate, published_only) is not None:
            continue
        priority = candidate.get("priority")

        cand_classification = candidate.get("classification", {})
        cand_categories = set(cand_classification.get("primaryCategoryIds") or [])
        cand_primary_tags = set(cand_classification.get("primaryTagIds") or [])
        cand_secondary_tags = set(cand_classification.get("secondaryTagIds") or [])
        cand_all_tags = cand_primary_tags | cand_secondary_tags

        shared_categories = own_categories & cand_categories
        shared_tags = own_all_tags & cand_all_tags

        if not (shared_categories or shared_tags):
            continue

        breakdown = []
        for tag in sorted(shared_tags):
            both_primary = tag in own_primary_tags and tag in cand_primary_tags
            points = 100 if both_primary else 50
            label = f"shared Primary Tag: {tag}" if both_primary else f"Primary/Secondary Tag match: {tag}"
            breakdown.append({"label": label, "points": points})
        for cat in sorted(shared_categories):
            breakdown.append({"label": f"shared Category: {cat}", "points": 50})
        breakdown.append({"label": f"candidate Priority: {priority}", "points": PRIORITY_BONUS.get(priority, 0)})

        score = sum(b["points"] for b in breakdown)
        scored.append((score, {"node": candidate, "score": score, "breakdown": breakdown}))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:MAX_RELATED_CANDIDATES]]


def _is_internal_only(node: dict, registry: dict) -> bool:
    """
    True iff `node` is assigned ONLY internal categories (e.g. the
    reserved "template-node" category) — never any public one. Such a
    Node still gets a real, directly-accessible built page, but is
    excluded from sitemap.xml, marked `noindex`, and (via
    derive_active_topics()) can never surface in Topic navigation. A
    Node with a MIX of internal and public categories is correctly
    treated as public — this only excludes Nodes with no public
    category at all.
    """
    category_ids = node.get("classification", {}).get("primaryCategoryIds") or []
    if not category_ids:
        return False
    return set(category_ids) <= registry["internalCategoryIds"]


def _first_public_topic_id(node: dict, registry: dict) -> str | None:
    """
    The first non-internal category id in `node`'s primaryCategoryIds,
    in array order (array order is the deliberate priority — the
    site owner controls it by ordering the field, not by any scoring).
    Returns None if the Node has no public category at all (e.g. the
    Template Node, which is internal-only), in which case the
    "more content on this topic" button is omitted entirely rather
    than pointing anywhere.
    """
    category_ids = node.get("classification", {}).get("primaryCategoryIds") or []
    for category_id in category_ids:
        if category_id not in registry["internalCategoryIds"]:
            return category_id
    return None


def select_related_nodes(node: dict, nodes_by_id: dict[str, dict],
                          published_only: bool) -> list[dict]:
    """
    Returns up to MAX_RELATED_CANDIDATES real Node records related to
    `node`, ranked best-first. This is the ONLY place that decides WHICH
    Nodes are related and in what order — render_related_section() only
    ever renders an already-decided list, and the browser-side variety
    script in template.html only ever reorders/subsets this exact ranked
    list, never re-ranks it.

    A thin wrapper around score_related_candidates() — see that function
    for the actual eligibility/scoring rules. Kept as its own function
    (rather than inlining the list-comprehension at every call site) so
    every existing caller's signature/return type stays exactly as it
    was before the Editorial Node Dashboard needed per-candidate score
    detail.
    """
    return [entry["node"] for entry in score_related_candidates(node, nodes_by_id, published_only)]


# ──────────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────────

def make_snippet(text: str, max_chars: int = 160) -> str:
    """
    Shared helper for producing a short preview snippet from a longer
    description, so this truncation logic exists in exactly one place.
    Used by both Topic pages' Node cards (render_node_card_html) and
    the Related Knowledge cards (render_related_section).
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


# ──────────────────────────────────────────────────────────────────
# Search Foundations — SEO metadata & structured data
# ──────────────────────────────────────────────────────────────────
# Generates all SEO / AI-discoverability output (meta tags, Open Graph,
# Twitter Card, JSON-LD, robots.txt, sitemap.xml) entirely from data
# that already exists on Nodes and in site-config.json. No new per-Node
# manual field is ever required for any of this.
#
# site-config.json gains two OPTIONAL, site-wide values:
#   "baseUrl"  — the absolute production domain, e.g. "https://drgilamd.com"
#   "aboutUrl" — the absolute URL of a future About/physician-profile page
# Every function below treats a missing/empty value as "not configured
# yet" and OMITS only the specific output that depends on it — never a
# blank, relative, or placeholder URL. The moment a real value is added
# to site-config.json, every affected page picks it up automatically on
# the next build, with no other code or Node file change needed.

META_DESCRIPTION_MAX_CHARS = 155  # standard, widely-used meta description display length
OG_LOCALE_MAP = {"he": "he_IL"}   # extend here if additional site languages are ever added


def _has_value(value) -> bool:
    """True for a real, non-empty configured string. False for None / "" / whitespace-only."""
    return bool(value and str(value).strip())


def generate_meta_description(full_description: str, max_chars: int = META_DESCRIPTION_MAX_CHARS) -> str:
    """
    Deterministic, offline (no AI, no network) helper that turns a
    Node's full, human-written youtube.description into a short,
    single-line string reused identically for <meta name="description">,
    og:description, and twitter:description. The full original
    description is never modified anywhere on the page itself — this
    only ever produces a short COPY for metadata tags.

    Documented truncation rule, applied in this exact order:
      1. Split the text into lines.
      2. Drop trailing lines that are ENTIRELY hashtag content (one or
         more "#word" tokens and nothing else), working backward from
         the end, until a line with real sentence content is reached.
         Hashtags inline within a real sentence are left untouched —
         only a trailing hashtag block is removed.
      3. Join the remaining lines with a single space (metadata tags are
         flat single-line text; this doesn't affect the real, multi-line
         description shown in the page body, which stays untouched).
      4. Collapse all whitespace runs to single spaces; trim the ends.
      5. If the result already fits within max_chars, return it as-is —
         no truncation, no ellipsis added.
      6. Otherwise, look for the last sentence-ending punctuation
         (. ! or ?) at or before max_chars. If that cut point keeps at
         least 60% of max_chars, cut there (a clean, complete sentence).
      7. Otherwise, cut at the last whitespace at or before max_chars
         (never mid-word), and append a single "…" character.
    """
    if not full_description:
        return ""

    lines = full_description.split("\n")
    hashtag_line_re = re.compile(r"^(\s*#\S+\s*)+$")
    while lines and hashtag_line_re.match(lines[-1]):
        lines.pop()

    flat = re.sub(r"\s+", " ", " ".join(lines)).strip()

    if len(flat) <= max_chars:
        return flat

    window = flat[:max_chars]

    last_sentence_end = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if last_sentence_end >= max_chars * 0.6:
        return window[:last_sentence_end + 1].strip()

    last_space = window.rfind(" ")
    if last_space == -1:
        return window.rstrip() + "…"
    return window[:last_space].rstrip() + "…"


def _canonical_url(site_config: dict, path: str) -> str:
    """
    Absolute canonical URL for `path` (e.g. "/nodes/some-slug/") built
    from site_config["baseUrl"]. Callers must check _has_value(baseUrl)
    first — this assumes it's already known to be present.
    """
    return site_config["baseUrl"].rstrip("/") + path


def render_seo_meta_tags(*, page_title: str, description: str, path: str,
                          image_url: str, site_config: dict,
                          og_type: str = "website", noindex: bool = False) -> str:
    """
    The combined block of <meta name="description">, the canonical
    <link>, the robots <meta>, Open Graph tags, and Twitter Card tags
    for ONE page — used identically for Node pages, the homepage, Topic
    pages, and the disclaimer page (each just supplies different title/
    description/path/image). No meta keywords tag is ever generated.

    Canonical and og:url are OMITTED (not emitted blank/relative) when
    site_config["baseUrl"] isn't configured yet. Every other tag here
    needs no site-wide URL and is always emitted.

    noindex=True (used for Nodes assigned only internal categories, see
    _is_internal_only()) emits "noindex, follow" instead of "index,
    follow" — "follow" is kept so crawlers can still traverse any links
    on the page; this is the correct mechanism for "built and directly
    accessible, but never indexed" (a robots.txt Disallow would be
    wrong here — it would stop crawlers from ever seeing this tag).
    """
    base_url = site_config.get("baseUrl", "")
    site_name = site_config.get("siteName", "")
    language = site_config.get("language", "he")
    og_locale = OG_LOCALE_MAP.get(language, language)

    robots_content = "noindex, follow" if noindex else "index, follow"
    lines = [
        f'<meta name="description" content="{html.escape(description, quote=True)}">',
        f'<meta name="robots" content="{robots_content}">',
    ]

    og_url = None
    if _has_value(base_url):
        canonical = _canonical_url(site_config, path)
        lines.append(f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">')
        og_url = canonical

    lines.append(f'<meta property="og:title" content="{html.escape(page_title, quote=True)}">')
    lines.append(f'<meta property="og:description" content="{html.escape(description, quote=True)}">')
    if _has_value(image_url):
        lines.append(f'<meta property="og:image" content="{html.escape(image_url, quote=True)}">')
    if og_url:
        lines.append(f'<meta property="og:url" content="{html.escape(og_url, quote=True)}">')
    lines.append(f'<meta property="og:type" content="{og_type}">')
    lines.append(f'<meta property="og:locale" content="{og_locale}">')
    if _has_value(site_name):
        lines.append(f'<meta property="og:site_name" content="{html.escape(site_name, quote=True)}">')

    twitter_card = "summary_large_image" if _has_value(image_url) else "summary"
    lines.append(f'<meta name="twitter:card" content="{twitter_card}">')
    lines.append(f'<meta name="twitter:title" content="{html.escape(page_title, quote=True)}">')
    lines.append(f'<meta name="twitter:description" content="{html.escape(description, quote=True)}">')
    if _has_value(image_url):
        lines.append(f'<meta name="twitter:image" content="{html.escape(image_url, quote=True)}">')

    return "\n".join(lines)


def build_physician_identity(site_config: dict) -> dict:
    """
    The one, shared, site-wide identity for the site's physician, built
    entirely from site-config.json. Used as author/reviewer on every
    Node's JSON-LD. Never duplicated into any Node file.

    Uses ["Physician", "Person"] (multi-typed): schema.org's "Physician"
    type is technically defined as a kind of MedicalOrganization (it can
    represent "a doctor's office"), not a Person — using it alone would
    make person-specific properties like jobTitle technically invalid
    for it. Adding "Person" as a second type is the standard, documented
    way to correctly represent one individual doctor while still
    satisfying the "Physician" typing.

    Only ever includes real, already-public data — name/role from
    site-config, the real social links already listed site-wide, and a
    url/@id ONLY when aboutUrl is configured. Never includes
    medicalSpecialty, hasCredential, hospitalAffiliation, or any claim
    that isn't genuinely stored data.
    """
    header = site_config["header"]
    identity: dict = {
        "@type": ["Physician", "Person"],
        "name": header["name"],
    }
    if _has_value(header.get("role")):
        identity["jobTitle"] = header["role"]

    social_links = [s["url"] for s in site_config.get("socialLinks", []) if _has_value(s.get("url"))]
    if social_links:
        identity["sameAs"] = social_links

    about_url = site_config.get("aboutUrl", "")
    if _has_value(about_url):
        identity["@id"] = about_url
        identity["url"] = about_url

    return identity


def build_website_identity(site_config: dict) -> dict:
    """
    Site-wide WebSite JSON-LD entity for the homepage. Deliberately
    WebSite, not Organization — this is a personal professional
    website, not a registered organization. url is included only when
    baseUrl is configured.
    """
    identity: dict = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": site_config.get("siteName", ""),
        "publisher": build_physician_identity(site_config),
    }
    base_url = site_config.get("baseUrl", "")
    if _has_value(base_url):
        identity["url"] = base_url
    return identity


def build_video_object_jsonld(node: dict, site_config: dict, thumbnail_url: str = "") -> dict:
    """
    VideoObject JSON-LD for one Node, generated entirely from its
    youtube.* fields. `thumbnail_url` should be the SAME already-
    resolved thumbnail (real stored value, or the videoId-derived
    fallback used elsewhere on the page) the caller is using for the
    visible page and for og:image/twitter:image — kept consistent
    rather than independently re-deriving it here.
    """
    yt = node["youtube"]
    video_id = yt["videoId"]
    obj: dict = {
        "@type": "VideoObject",
        "name": yt["title"],
        "description": yt["description"],
        "embedUrl": f"https://www.youtube.com/embed/{video_id}",
        "contentUrl": f"https://www.youtube.com/watch?v={video_id}",
    }
    if _has_value(thumbnail_url):
        obj["thumbnailUrl"] = thumbnail_url
    if _has_value(yt.get("publishedAt")):
        obj["uploadDate"] = yt["publishedAt"]
    return obj


def build_node_jsonld(node: dict, site_config: dict, thumbnail_url: str = "") -> dict:
    """
    MedicalWebPage JSON-LD for one Node page, containing its
    VideoObject. Uses only real, stored data — never invents dates,
    credentials, specialties, affiliations, or medical claims.
    """
    page: dict = {
        "@context": "https://schema.org",
        "@type": "MedicalWebPage",
        "name": node["youtube"]["title"],
        "inLanguage": site_config.get("language", "he"),
        "mainEntity": build_video_object_jsonld(node, site_config, thumbnail_url),
        "author": build_physician_identity(site_config),
        "reviewedBy": build_physician_identity(site_config),
    }

    base_url = site_config.get("baseUrl", "")
    if _has_value(base_url):
        page["url"] = _canonical_url(site_config, f'/nodes/{node["slug"]}/')

    published_at = node.get("publishing", {}).get("publishedAt")
    if _has_value(published_at):
        page["datePublished"] = published_at

    last_reviewed = node.get("clinical", {}).get("lastReviewedAt")
    if _has_value(last_reviewed):
        page["lastReviewed"] = last_reviewed

    return page


def render_jsonld_script(data: dict) -> str:
    """Serialize a JSON-LD dict into a <script> tag — Hebrew text intact, deterministic key order."""
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{body}\n</script>'


def render_robots_txt(site_config: dict) -> str:
    """
    Standard robots.txt: allow normal crawling of the public site for
    all crawlers (no speculative per-crawler rules). References
    sitemap.xml only when baseUrl is configured — a relative sitemap
    reference would be invalid. Unpublished/unavailable Node pages need
    no explicit disallow rule here: they are simply never built at all
    (see build_all_published), so there is no URL to ever accidentally
    expose in the first place.
    """
    lines = ["User-agent: *", "Allow: /"]
    base_url = site_config.get("baseUrl", "")
    if _has_value(base_url):
        lines.append("")
        lines.append(f"Sitemap: {base_url.rstrip('/')}/sitemap.xml")
    return "\n".join(lines) + "\n"


def render_sitemap_xml(paths: list[str], site_config: dict) -> Optional[str]:
    """
    Standard sitemap.xml built from the exact list of page paths
    actually built this run (see build_all_published — this is always
    called with the real, final set: homepage, disclaimer page, and
    every published+available Node actually built, nothing more).

    No <lastmod> is emitted for any entry: there is currently no field
    that reliably represents "this page's content last meaningfully
    changed" — youtube.lastSyncedAt only means "we checked", and
    publishing.publishedAt only means "first went live", not "last
    updated". <lastmod> is optional in the sitemap protocol; omitting
    it is more accurate than publishing a misleading date.

    Returns None (generate nothing) if baseUrl isn't configured yet — a
    sitemap of relative or blank URLs would be invalid.
    """
    base_url = site_config.get("baseUrl", "")
    if not _has_value(base_url):
        return None

    base = base_url.rstrip("/")
    entries = "\n".join(
        f"  <url>\n    <loc>{html.escape(base + path, quote=True)}</loc>\n  </url>"
        for path in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )


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
        node_id = html.escape(related_node["id"], quote=True)
        cards_html.append(
            f'      <a class="related-card" href="{href}" data-node-id="{node_id}">\n'
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


def _json_for_inline_script(data) -> str:
    """
    Serialize `data` as JSON safe to embed inside a literal <script>...
    </script> block as a JS array/object literal (not a text/json
    island like the JSON-LD script, which never needs this). Escapes any
    "</" sequence so a value containing e.g. "</script>" can never
    prematurely close the tag, and escapes U+2028/U+2029 (valid in JSON
    strings, invalid unescaped inside a JS string literal).
    """
    raw = json.dumps(data, ensure_ascii=False)
    raw = raw.replace("</", "<\\/")
    raw = raw.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return raw


def render_more_link_button_html(node: dict, site_config: dict, registry: dict) -> str:
    """
    The first of the two Node-page pink nav buttons — "more content on
    this Topic" — linking to the Node's first public Topic page
    (_first_public_topic_id(), array order). Omitted entirely (empty
    string) when the Node has no public category, e.g. the Template
    Node, rather than rendered with a dead/placeholder destination.

    Carries data-topic-nav="primary" so the browser-side script in
    template.html can find this specific button (not the second, always-
    static "all topics" button, which also uses .more-link) and rewrite
    its href to the Topic page the visitor actually arrived from, when
    that context is available. See template.html for that logic — this
    function's own computed href/text is always the correct SERVER-
    RENDERED fallback for direct/external visits, and is left untouched
    either way.
    """
    topic_id = _first_public_topic_id(node, registry)
    if topic_id is None:
        return ""
    text = html.escape(site_config["moreLinkButton"]["text"], quote=True)
    url = html.escape(f"/topics/{topic_id}/", quote=True)
    return f'  <a class="more-link" data-topic-nav="primary" href="{url}">{text}</a>\n'


def render_node_html(node: dict, template: str, site_config: dict,
                      nodes_by_id: dict[str, dict], published_only: bool,
                      registry: dict) -> str:
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    video_id = node["youtube"]["videoId"]

    # thumbnailUrl is real YouTube-sourced data and must be used if present.
    # Derivation from videoId is only a FALLBACK for missing data, never a replacement.
    thumbnail_url = node["youtube"].get("thumbnailUrl") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    thumbnail_fallback_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    page_title = f'{node["youtube"]["title"]} | {site_config["header"]["name"]}'
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()

    related_candidates = select_related_nodes(node, nodes_by_id, published_only=published_only)
    default_related_cards = related_candidates[:MAX_RELATED_CARDS]
    related_candidates_payload = [
        {
            "id": c["id"],
            "slug": c["slug"],
            "title": c["youtube"]["title"],
            "desc": make_snippet(c["youtube"]["description"]),
        }
        for c in related_candidates
    ]

    seo_description = generate_meta_description(node["youtube"]["description"])
    seo_meta_tags = render_seo_meta_tags(
        page_title=node["youtube"]["title"],
        description=seo_description,
        path=f'/nodes/{node["slug"]}/',
        image_url=thumbnail_url,
        site_config=site_config,
        noindex=_is_internal_only(node, registry),
    )
    jsonld_script = render_jsonld_script(build_node_jsonld(node, site_config, thumbnail_url))

    tokens = {
        "{{PAGE_TITLE}}": page_title,
        "{{SEO_META_TAGS}}": seo_meta_tags,
        "{{JSONLD_SCRIPT}}": jsonld_script,
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{NODE_ID}}": node["id"],
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
        "{{HOME_NAV_TEXT}}": site_config["homeNavBar"]["text"],
        "{{HOME_NAV_URL}}": site_config["homeNavBar"]["url"],
        "{{DISCLAIMER_ICON}}": site_config["disclaimer"]["icon"],
        "{{DISCLAIMER_SHORT_TEXT}}": site_config["disclaimer"]["shortText"],
        "{{DISCLAIMER_LINK_PREFIX}}": site_config["disclaimer"]["linkPrefix"],
        "{{DISCLAIMER_LINK_TEXT}}": site_config["disclaimer"]["linkText"],
        "{{DISCLAIMER_LINK_URL}}": site_config["disclaimer"]["linkUrl"],
        "{{END_REPLAY_LABEL}}": site_config["endOfVideoButtons"]["replay"],
        "{{END_CLOSE_LABEL}}": site_config["endOfVideoButtons"]["close"],
        "{{RELATED_SECTION_HTML}}": render_related_section(default_related_cards, site_config),
        "{{RELATED_CANDIDATES_JSON}}": _json_for_inline_script(related_candidates_payload),
        "{{MORE_LINK_BUTTON_HTML}}": render_more_link_button_html(node, site_config, registry),
        "{{ALL_TOPICS_BUTTON_TEXT}}": site_config["allTopicsButton"]["text"],
        "{{ALL_TOPICS_BUTTON_URL}}": site_config["allTopicsButton"]["url"],
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
    registry = load_categories_and_tags()

    html_out = render_node_html(node, template, site_config, nodes_by_id, published_only=published_only,
                                 registry=registry)

    out_dir = DIST_DIR / "nodes" / node["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


def render_node_card_html(node: dict, from_topic_id: str | None = None) -> str:
    """
    `from_topic_id`, when given (only ever the Topic page's own id, from
    build_topic_page()), is appended as a "?fromTopic={id}" query param —
    temporary per-URL context so the Node page's first pink button can
    send the visitor back to the Topic she actually browsed from, instead
    of always falling back to the Node's first public category. Purely
    a client-side hint (see template.html); never affects canonical
    URLs, sitemap entries, or any other server-rendered output.
    """
    title = node["youtube"]["title"]
    snippet = make_snippet(node["youtube"]["description"])
    href = f'/nodes/{node["slug"]}/'
    if from_topic_id:
        href += f'?fromTopic={html.escape(from_topic_id, quote=True)}'
    return (
        f'    <a class="node-card" href="{href}">\n'
        f'      <p class="node-card-title">{title}</p>\n'
        f'      <p class="node-card-desc">{snippet}</p>\n'
        '    </a>'
    )


def render_topic_selector_options_html(active_topics: list[dict]) -> str:
    return "\n".join(
        f'      <option value="/topics/{html.escape(t["id"], quote=True)}/">'
        f'{html.escape(t["label"], quote=True)}</option>'
        for t in active_topics
    )


def build_homepage(published_nodes: list[dict], active_topics: list[dict]) -> Path:
    """
    Build the real dist/index.html homepage: shared header/branding, a
    professional photo, a short welcome section, the Homepage Topic
    Selector, the "All Topics" button, social links, and the disclaimer
    strip. `published_nodes` is accepted (build_all_published always
    passes the real, current list) but not currently rendered directly
    on the homepage — the Topic Selector, the All-Topics page, and
    Related Knowledge are how visitors reach individual Nodes now.

    `active_topics` (from derive_active_topics(), computed once by the
    caller and passed in — never recomputed here) drives the Topic
    Selector's options, in the exact same registry order used
    everywhere else. English category ids never reach the selector's
    visible text — only the approved Hebrew label.
    """
    template = (BASE_DIR / "homepage-template.html").read_text(encoding="utf-8")
    site_config = json.loads((BASE_DIR / "site-config.json").read_text(encoding="utf-8"))
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    homepage_cfg = site_config["homepage"]
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()
    photo_base64 = (BASE_DIR / homepage_cfg["photoImagePath"]).read_text(encoding="utf-8").strip()

    welcome_html = "\n".join(f"    <p>{p}</p>" for p in homepage_cfg["welcomeParagraphs"])
    topic_selector_options_html = render_topic_selector_options_html(active_topics)

    seo_description = generate_meta_description(homepage_cfg["welcomeParagraphs"][0])
    seo_meta_tags = render_seo_meta_tags(
        page_title=homepage_cfg["pageTitle"],
        description=seo_description,
        path="/",
        image_url="",
        site_config=site_config,
    )
    jsonld_script = render_jsonld_script(build_website_identity(site_config))

    tokens = {
        "{{PAGE_TITLE}}": homepage_cfg["pageTitle"],
        "{{SEO_META_TAGS}}": seo_meta_tags,
        "{{JSONLD_SCRIPT}}": jsonld_script,
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{HOMEPAGE_PHOTO_BASE64}}": photo_base64,
        "{{HOMEPAGE_PHOTO_ALT}}": homepage_cfg["photoAlt"],
        "{{HOMEPAGE_WELCOME_HTML}}": welcome_html,
        "{{TOPIC_SELECTOR_LABEL}}": homepage_cfg["topicSelectorLabel"],
        "{{TOPIC_SELECTOR_PLACEHOLDER}}": homepage_cfg["topicSelectorPlaceholder"],
        "{{TOPIC_SELECTOR_OPTIONS_HTML}}": topic_selector_options_html,
        "{{TOPIC_MODAL_TITLE}}": site_config["uiLabels"]["topicModalTitle"],
        "{{TOPIC_MODAL_CLOSE_ARIA}}": site_config["uiLabels"]["topicModalCloseAriaLabel"],
        "{{ALL_TOPICS_BUTTON_TEXT}}": site_config["allTopicsButton"]["text"],
        "{{ALL_TOPICS_BUTTON_URL}}": site_config["allTopicsButton"]["url"],
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

    # Use the disclaimer's own first paragraph as the source text for the
    # short meta description -- it's real, on-page content, same principle
    # as using youtube.description for Node pages. No JSON-LD here: this
    # page isn't a MedicalWebPage or VideoObject, and inventing a page
    # type for it just to have some structured data would be inaccurate.
    seo_description = generate_meta_description(disclaimer_cfg["paragraphs"][0])
    seo_meta_tags = render_seo_meta_tags(
        page_title=disclaimer_cfg["title"],
        description=seo_description,
        path="/medical-disclaimer/",
        image_url="",
        site_config=site_config,
    )

    tokens = {
        "{{PAGE_TITLE}}": disclaimer_cfg["pageTitle"],
        "{{SEO_META_TAGS}}": seo_meta_tags,
        "{{JSONLD_SCRIPT}}": "",
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


# ──────────────────────────────────────────────────────────────────
# Topic navigation (Homepage Topic Selector, Topic pages, All Topics)
# ──────────────────────────────────────────────────────────────────
# Fully automatic and fully independent of Related Knowledge: Topic
# membership is decided by classification.primaryCategoryIds ONLY —
# never tags, never priority. See derive_active_topics(), the ONE
# place that decides which Topics exist and what's on each of them.

def derive_active_topics(nodes: list[dict], registry: dict) -> list[dict]:
    """
    The single source of truth for "what Topics are active right now" —
    reused to build the Homepage Topic Selector, the All-Topics page,
    and every individual Topic page, so the three can never disagree.

    `nodes` must already be the real, final published+available set
    (the same `buildable` list build_all_published() already computes)
    — this function does no publishing/availability filtering of its
    own. Walks registry["categoriesOrdered"] IN THAT ORDER (never
    alphabetical — this is what gives the site owner control over
    Topic order by editing one file), skips anything in
    internalCategoryIds entirely (an internal category can never become
    a Topic, regardless of how many Nodes use it), and for each
    remaining category collects every Node whose primaryCategoryIds
    contains it. A category with zero matching Nodes is dropped
    entirely — never appears, never gets a page, never reaches the
    sitemap. Priority and tags are never consulted anywhere here.

    Returns an ordered list of {"id", "label", "nodes"}.
    """
    nodes_by_category: dict[str, list[dict]] = {}
    for node in nodes:
        for category_id in node.get("classification", {}).get("primaryCategoryIds") or []:
            nodes_by_category.setdefault(category_id, []).append(node)

    topics = []
    for category_id in registry["categoriesOrdered"]:
        if category_id in registry["internalCategoryIds"]:
            continue
        matching_nodes = nodes_by_category.get(category_id)
        if not matching_nodes:
            continue
        topics.append({
            "id": category_id,
            "label": registry["categoryLabelsHe"][category_id],
            "nodes": matching_nodes,
        })
    return topics


def build_topic_page(topic: dict, site_config: dict) -> Path:
    """
    Build one Topic page to dist/topics/{id}/index.html — shared
    header, the Hebrew Topic name as the heading, a card for every Node
    in that Topic (reusing render_node_card_html(), the same helper the
    homepage used before its redesign — no duplicated card-rendering
    logic), and the shared disclaimer. Only ever called for Topics
    derive_active_topics() already confirmed have at least one Node.
    """
    template = (BASE_DIR / "topic-template.html").read_text(encoding="utf-8")
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()

    nodes_html = '  <div class="node-list">\n' + "\n".join(
        render_node_card_html(n, from_topic_id=topic["id"]) for n in topic["nodes"]
    ) + "\n  </div>"

    page_title = f'{topic["label"]} | {site_config["header"]["name"]}'
    seo_description = generate_meta_description(
        f'{topic["label"]} — סרטונים והסברים מאת {site_config["header"]["name"]}'
    )
    seo_meta_tags = render_seo_meta_tags(
        page_title=page_title,
        description=seo_description,
        path=f'/topics/{topic["id"]}/',
        image_url="",
        site_config=site_config,
    )

    tokens = {
        "{{PAGE_TITLE}}": page_title,
        "{{SEO_META_TAGS}}": seo_meta_tags,
        "{{JSONLD_SCRIPT}}": "",
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{HOME_NAV_TEXT}}": site_config["homeNavBar"]["text"],
        "{{HOME_NAV_URL}}": site_config["homeNavBar"]["url"],
        "{{TOPIC_NAME_HE}}": topic["label"],
        "{{TOPIC_NODES_HTML}}": nodes_html,
        "{{ALL_TOPICS_BUTTON_TEXT}}": site_config["allTopicsButton"]["text"],
        "{{ALL_TOPICS_BUTTON_URL}}": site_config["allTopicsButton"]["url"],
        "{{DISCLAIMER_ICON}}": site_config["disclaimer"]["icon"],
        "{{DISCLAIMER_SHORT_TEXT}}": site_config["disclaimer"]["shortText"],
        "{{DISCLAIMER_LINK_PREFIX}}": site_config["disclaimer"]["linkPrefix"],
        "{{DISCLAIMER_LINK_TEXT}}": site_config["disclaimer"]["linkText"],
        "{{DISCLAIMER_LINK_URL}}": site_config["disclaimer"]["linkUrl"],
    }

    html_out = template
    for token, value in tokens.items():
        html_out = html_out.replace(token, value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", html_out)
    if remaining:
        raise SystemExit(f"BUILD FAILED — unresolved tokens on Topic page '{topic['id']}': {set(remaining)}")

    out_dir = DIST_DIR / "topics" / topic["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


def render_topic_tile_html(topic: dict) -> str:
    count = len(topic["nodes"])
    label = html.escape(topic["label"], quote=True)
    return (
        f'    <a class="topic-tile" href="/topics/{html.escape(topic["id"], quote=True)}/">\n'
        f'      <p class="topic-tile-name">{label}</p>\n'
        f'      <p class="topic-tile-count">{count} תכנים</p>\n'
        '    </a>'
    )


def build_all_topics_page(active_topics: list[dict], site_config: dict) -> Path:
    """
    Build the "All Topics" index to dist/topics/index.html — one tile
    per active Topic (Hebrew name + Node count), in the same registry
    order as everywhere else. Only ever lists Topics
    derive_active_topics() already confirmed are active — an empty
    future category never appears here.
    """
    template = (BASE_DIR / "topics-index-template.html").read_text(encoding="utf-8")
    social = {s["platform"]: s["url"] for s in site_config["socialLinks"]}
    logo_base64 = (BASE_DIR / site_config["header"]["logoImagePath"]).read_text(encoding="utf-8").strip()
    topics_cfg = site_config["topicsIndexPage"]

    if active_topics:
        tiles_html = '  <div class="topics-grid">\n' + "\n".join(
            render_topic_tile_html(t) for t in active_topics
        ) + "\n  </div>"
    else:
        tiles_html = f'  <div class="empty-state">{topics_cfg["emptyStateText"]}</div>'

    seo_description = generate_meta_description(
        f'{topics_cfg["heading"]} — {site_config["header"]["name"]}'
    )
    seo_meta_tags = render_seo_meta_tags(
        page_title=topics_cfg["pageTitle"],
        description=seo_description,
        path="/topics/",
        image_url="",
        site_config=site_config,
    )

    tokens = {
        "{{PAGE_TITLE}}": topics_cfg["pageTitle"],
        "{{SEO_META_TAGS}}": seo_meta_tags,
        "{{JSONLD_SCRIPT}}": "",
        "{{SITE_LOGO_BASE64}}": logo_base64,
        "{{SITE_HEADER_NAME}}": site_config["header"]["name"],
        "{{SITE_HEADER_ROLE}}": site_config["header"]["role"],
        "{{SOCIAL_YOUTUBE_URL}}": social["YouTube"],
        "{{SOCIAL_INSTAGRAM_URL}}": social["Instagram"],
        "{{SOCIAL_FACEBOOK_URL}}": social["Facebook"],
        "{{SOCIAL_TIKTOK_URL}}": social["TikTok"],
        "{{HOME_NAV_TEXT}}": site_config["homeNavBar"]["text"],
        "{{HOME_NAV_URL}}": site_config["homeNavBar"]["url"],
        "{{TOPICS_INDEX_HEADING}}": topics_cfg["heading"],
        "{{TOPICS_LIST_HTML}}": tiles_html,
        "{{DISCLAIMER_ICON}}": site_config["disclaimer"]["icon"],
        "{{DISCLAIMER_SHORT_TEXT}}": site_config["disclaimer"]["shortText"],
        "{{DISCLAIMER_LINK_PREFIX}}": site_config["disclaimer"]["linkPrefix"],
        "{{DISCLAIMER_LINK_TEXT}}": site_config["disclaimer"]["linkText"],
        "{{DISCLAIMER_LINK_URL}}": site_config["disclaimer"]["linkUrl"],
    }

    html_out = template
    for token, value in tokens.items():
        html_out = html_out.replace(token, value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", html_out)
    if remaining:
        raise SystemExit(f"BUILD FAILED — unresolved tokens on All-Topics page: {set(remaining)}")

    out_dir = DIST_DIR / "topics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


def build_all_published():
    """
    Build every Node whose publishing.status == 'published' AND whose
    video is not confirmed unavailable. Excludes draft/archived Nodes
    entirely (as before), and additionally SKIPS (with a warning, not a
    failure) any published Node whose youtube.availability == 
    "unavailable" — a missing YouTube video must never take down the
    rest of the site. Build only ever reads the locally stored
    "availability" value; it never contacts YouTube itself.
    """
    all_nodes, nodes_by_id = node_store.load_all_nodes_checked()

    published_all = [n for n in all_nodes if n["publishing"]["status"] == "published"]
    not_published = [n for n in all_nodes if n["publishing"]["status"] != "published"]

    unavailable_skipped = [n for n in published_all if n["youtube"].get("availability") == "unavailable"]
    buildable = [n for n in published_all if n["youtube"].get("availability") != "unavailable"]

    # Every Node that will actually be built must pass full validation.
    # This is checked at build time, not stored as data on the Node.
    # (Skipped/unavailable Nodes are NOT validated for publication —
    # they're not being published right now, so incomplete data on a
    # Node nobody is building yet must not fail the whole build.)
    registry = load_categories_and_tags()

    all_errors = []
    for node in buildable:
        all_errors.extend(validate_for_publication(node))
    for node in buildable:
        all_errors.extend(validate_classification_and_priority(node, registry))
    if all_errors:
        raise SystemExit(
            "BUILD FAILED — the following Node(s) are marked 'published' but are "
            "invalid:\n" + "\n".join(f"  - {e}" for e in all_errors)
        )

    site_config = json.loads((BASE_DIR / "site-config.json").read_text(encoding="utf-8"))
    active_topics = derive_active_topics(buildable, registry)

    built_paths = [build_node(n, nodes_by_id, published_only=True) for n in buildable]
    build_homepage(buildable, active_topics)
    build_disclaimer_page()
    for topic in active_topics:
        build_topic_page(topic, site_config)
    build_all_topics_page(active_topics, site_config)

    (DIST_DIR / "robots.txt").write_text(render_robots_txt(site_config), encoding="utf-8")
    print("Built robots.txt")

    sitemap_eligible = [n for n in buildable if not _is_internal_only(n, registry)]
    built_page_paths = (
        ["/", "/medical-disclaimer/", "/topics/"]
        + [f"/nodes/{n['slug']}/" for n in sitemap_eligible]
        + [f"/topics/{t['id']}/" for t in active_topics]
    )
    sitemap_xml = render_sitemap_xml(built_page_paths, site_config)
    if sitemap_xml is not None:
        (DIST_DIR / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")
        print(f"Built sitemap.xml ({len(built_page_paths)} URLs)")
    else:
        print("Skipped sitemap.xml — site-config.json 'baseUrl' is not configured yet.")

    print(f"Built {len(buildable)} published Node(s).")
    if not_published:
        print(f"Excluded {len(not_published)} Node(s) not in 'published' status:")
        for n in not_published:
            print(f"  - {n['slug']} (status: {n['publishing']['status']})")
    print("Built homepage: dist/index.html")
    print("Built Medical Disclaimer page: dist/medical-disclaimer/index.html")
    print(f"Built {len(active_topics)} active Topic page(s) + dist/topics/index.html:")
    for t in active_topics:
        print(f"  - {t['id']} ({t['label']}): {len(t['nodes'])} Node(s)")

    # Warning report — never fails the build, just surfaces what to fix.
    if unavailable_skipped:
        print("\nWARNINGS:")
        print(f"  {len(unavailable_skipped)} published Node(s) SKIPPED — video unavailable:")
        for n in unavailable_skipped:
            print(
                f"    - nodeId={n['id']} slug={n['slug']} videoId={n['youtube']['videoId']} "
                f"title=\"{n['youtube']['title']}\" reason=\"YouTube video unavailable\""
            )

    return built_paths


def build_single_for_dev(slug: str):
    """
    Build one Node by slug regardless of publishing status, for
    dev/testing/preview. Related cards in the preview only ever show
    targets that are themselves published and available, so the
    preview reflects what production would actually render.
    """
    all_nodes, nodes_by_id = node_store.load_all_nodes_checked()

    matches = [n for n in all_nodes if n["slug"] == slug]
    if not matches:
        raise SystemExit(f"No node found with slug '{slug}'")
    out_path = build_node(matches[0], nodes_by_id, published_only=True)

    # Also refresh homepage + disclaimer page so their links work while
    # previewing locally. Homepage only ever lists real 'published',
    # available Nodes, even when previewing an unrelated draft. Topic
    # pages themselves are NOT rebuilt here (only --all does that, same
    # as sitemap.xml/robots.txt) — this stays a fast, single-Node preview.
    registry = load_categories_and_tags()
    published = [
        n for n in all_nodes
        if n["publishing"]["status"] == "published" and n["youtube"].get("availability") != "unavailable"
    ]
    active_topics = derive_active_topics(published, registry)
    build_homepage(published, active_topics)
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
