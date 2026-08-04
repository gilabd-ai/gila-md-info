# Gila MD — Knowledge Node Website

This file is read automatically by Claude Code at the start of every session in this repository. It exists so that any future session — with no memory of past conversations — has the full, accurate context needed to work on this project correctly and safely.

## What this project is

A static, medical-information website for Dr. Gila Ben-David (gynecologist). Each page ("Knowledge Node") is built from one real YouTube video: its title, description, and thumbnail, embedded with a real player. Production domain: https://drgilamd.com. Hosted on Cloudflare Pages, which runs `python3 build.py --all` and deploys the `dist/` output directory automatically on every push to the repository's default branch.

Language: Hebrew throughout. Every page is `<html lang="he" dir="rtl">`.

## Hard, non-negotiable rule — read this first

Claude must NEVER invent, guess, or assume any editorial, clinical, or classification data. This is a real medical website, not a demo. If a field is genuinely unset, it stays exactly as-is — `null`, `"unassigned"`, or whatever the real placeholder value is — never filled in with something plausible-sounding. This applies to category assignments, clinical review dates/status, priority, and anything a human (Dr. Ben-David) is meant to decide, not Claude. When in doubt, leave it unset and ask, rather than guess.

## Architecture — three independent Python modules

* `node_store.py` — the shared foundation. Owns loading Node JSON files, duplicate-slug/id checks, the id lookup table, and the one canonical way to write a Node file back to disk (standard `json.dump`, fixed indentation, no attempt to preserve hand-written blank-line formatting, atomic temp-file-then-rename writes for crash safety, and only writes when the content actually changed). Imports nothing from the other two modules.
* `build.py` — rendering only. Turns Node data + `template.html` + `site-config.json` into the static HTML site, plus `robots.txt` and `sitemap.xml`. Never imports `requests` and never imports `youtube_sync` — this is a real, checkable architectural guarantee that Build cannot reach the network, not just a convention.
* `youtube_sync.py` — the only part of the project that talks to the YouTube Data API v3. Reads `YOUTUBE_API_KEY` from the environment (never hard-coded, never logged, never committed). Imports `node_store`, never `build.py`.

Both `build.py` and `youtube_sync.py` have their own CLI entry points and are meant to map onto two independent future UI buttons ("Sync" and "Build").

## Node Schema v1.0

There is no separate schema/template file. The de facto template for creating a new Node is the real file `nodes/template-node.json` — copy it as the starting point for any new Node. This file exists only to be copied: it uses the reserved `template-node` internal category/tag and `priority: 0`. It IS published (`publishing.status: "published"`) — it has a real, directly-accessible page at `/nodes/template-node/`, since the site owner wants to be able to view it directly — but the internal category keeps it out of `sitemap.xml`, marks its page `noindex`, and excludes it from Topic navigation; priority 0 excludes it from Related Knowledge. See "Internal categories" below. Never assign the `template-node` category/tag to a real content Node.

⚠️ Whenever the Node schema changes (fields added, removed, or renamed), update that template Node AND `README.txt`'s manual Node-creation instructions in the same change. This has been forgotten before and caused real drift — treat it as a checklist item, not optional.

Fields on every Node (`nodes/{slug}.json`):

```
schemaVersion
id                          "node-000N"
slug                        must exactly match the filename (no ".json")
youtube:
  videoId                   the single source of truth for the video —
                             there is intentionally NO "url" field; a watch
                             URL is generated from videoId only when needed,
                             never stored
  title
  description                the full, real, human-written text — shown
                             verbatim on the page; never summarized or rewritten
  publishedAt                the video's own YouTube publish date
  thumbnailUrl
  availability               "available" | "unavailable" — see Sync section
  lastSyncedAt                ISO-8601 UTC, set by Sync
classification:
  primaryCategoryIds         array of category ids — every id must exist in
                             data/code-categories-and-tags.json; never invent one
  primaryTagIds               array of tag ids — the Node's main topics,
                             same registry, same never-invent rule
  secondaryTagIds             array of tag ids — related but not central
                             topics; a tag can't be in both primaryTagIds
                             and secondaryTagIds on the same Node
priority                     0 | 1 | 2 | 3 — a TOP-LEVEL field, a sibling
                             of "classification", not nested inside it.
                             0 = never recommend this Node elsewhere,
                             1 = highest, 2 = normal, 3 = lowest. No
                             default: the build fails if it's missing.
clinical:
  lastReviewedAt              real date only — never invent
  status                      "current" | "needs-review" | "outdated"
publishing:
  status                      "draft" | "published" | "unpublished" | "archived"
  publishedAt                  the PAGE's own publish date (distinct from
                              youtube.publishedAt — do not conflate the two)
timestamps:
  createdAt / updatedAt        currently always null; nothing in the system
                              populates these yet

```

## `data/code-categories-and-tags.json` — the classification registry

The single canonical, controlled pool of approved category/tag ids — a JSON object with `categories`/`tags` arrays of plain English ids, an `internalCategoryIds` array, and a `categoryLabelsHe` mapping (see below). A Node's `classification.primaryCategoryIds` / `primaryTagIds` / `secondaryTagIds` may only use ids already present here. Claude must never add an id to a Node's classification, or to this registry itself, that wasn't explicitly given by the user — this is exactly the kind of editorial/classification data the hard rule at the top of this file covers. The same rule applies to Hebrew labels: Claude must never invent, translate, or guess a `categoryLabelsHe` value — only the site owner decides these.

The registry is expected to grow over time, but only with the user's explicit approval each time — new categories/tags go into this file first, then Nodes may select those exact ids. Existing ids must never be silently renamed or removed, since that would break classification consistency and Related Knowledge matching for every Node already using that id.

`docs/gila-categories-and-tags.html` is a generated, human-readable reference page (via `generate_categories_doc.py`) for the site owner to browse and copy exact ids from, now showing each public category's approved Hebrew label beside its id (the page's own structure/explanations stay English-only) — it cross-validates against this registry at generation time so it can never disagree with it, and it is NOT a second source of truth, NOT part of the public site, and never copied into `dist/`.

### Internal categories

`internalCategoryIds` (a separate array in the same registry file, currently just `["template-node"]`) marks categories reserved for technical or editorial Nodes only. They must never be used for normal public medical content. A Node may use an internal category and still gets a real, directly-accessible built page (`publishing.status: "published"` works normally), but `_is_internal_only()` in `build.py` automatically excludes it from `sitemap.xml`, marks its page `<meta name="robots" content="noindex, follow">`, and excludes it from every Topic-navigation surface (`derive_active_topics()` skips internal categories entirely, regardless of how many Nodes use them) — this is one general mechanism, not template-Node-specific code. Internal categories are exempt from needing a `categoryLabelsHe` entry, since they're never shown publicly — and must NOT have one.

## `docs/gila-node-dashboard.html` — internal editorial dashboard

Generated (via `generate_node_dashboard.py`) English-only view of every Node — published, draft, and the reserved template Node — showing classification/priority/dates, a validation status, and the full ranked Related Knowledge candidate list with a per-candidate score explanation. It is a GENERATED VIEW ONLY: not a source of truth, not part of the public site, never linked publicly, never copied into `dist/`. Critically, it reuses `build.py`'s `score_related_candidates()` / `ineligible_candidate_reason()` — the exact same functions `select_related_nodes()` wraps for the public site — so the dashboard's numbers can never independently drift from what production actually computes. Re-run after any Node change.

## `template.html` and the `{{TOKEN}}` system

`build.py` does plain string-replacement of `{{TOKEN}}` placeholders in `template.html` (and `homepage-template.html`, `disclaimer-template.html`, `topic-template.html`, `topics-index-template.html`). These tokens never move and are always safe to rely on: `{{PAGE_TITLE}}`, `{{SEO_META_TAGS}}`, `{{JSONLD_SCRIPT}}`, `{{SITE_LOGO_BASE64}}`, `{{NODE_TITLE}}`, `{{NODE_DESCRIPTION}}`, `{{VIDEO_ID}}`, `{{NODE_ID}}`, `{{RELATED_SECTION_HTML}}`, `{{RELATED_CANDIDATES_JSON}}`, `{{TOPIC_SELECTOR_OPTIONS_HTML}}`, `{{ALL_TOPICS_BUTTON_URL}}`, `{{TOPIC_NAME_HE}}`, `{{TOPIC_NODES_HTML}}`, `{{TOPICS_LIST_HTML}}`, and others for header/nav/disclaimer text pulled from `site-config.json`.

## `site-config.json` — global, site-wide data

`siteName`, `language`, `direction`, `baseUrl` (`"https://drgilamd.com"`), `aboutUrl` (currently `""` — the About page doesn't exist yet), `header` (doctor's name/role), `socialLinks`, `uiLabels`, `homepage` (photo, welcome paragraphs, `topicSelectorLabel`/`topicSelectorPlaceholder`), `topicsIndexPage`, `medicalDisclaimerPage`, `allTopicsButton` (top-level `{text, url}` — the "לכל הנושאים באתר" button, shared as-is by both the homepage and every Node page's second nav button, since they are literally the same button in two places), `moreLinkButton` (Node pages' own FIRST nav button — `{text}` only, no stored `url`: its href is a dynamic per-Node `/topics/{id}/` computed at build time from the Node's own first public category, see Topic Navigation section below), `homeNavBar`.

## Related Knowledge — automatic, two-stage

Fully automatic since the classification-registry upgrade — there is no manual `relatedNodeIds` field anymore. Deliberately split into two independent stages so each can change without touching the other:

**Stage 1 — build-time ranking (deterministic, same for every visitor).** `select_related_nodes()` in `build.py` scores every other eligible Node and returns up to 10 candidates, best first — this is the only seam that decides WHICH Nodes are related. A candidate must be published (in production), not a draft, not `priority == 0`, not `youtube.availability == "unavailable"` (its page isn't built at all, so linking to it would be a dead link), never self, and must share at least one `primaryCategoryId`, `primaryTagId`, or `secondaryTagId` with the source Node — priority alone never qualifies a candidate. Scoring: a shared tag scores **+100** if it's primary on both Nodes, else **+50** (covers primary↔secondary and secondary↔secondary — the topic is still genuinely shared, just not central to both); a shared category scores **+50**; the candidate's own priority adds a bonus (**+100** for priority 1, **+50** for priority 2, **+0** for priority 3). Ties preserve the Nodes' existing load order (alphabetical by slug). The page's default 3 rendered cards, and the full ranked list exposed to the browser via `{{RELATED_CANDIDATES_JSON}}`, both come directly from this one ranking.

**Stage 2 — browser-side variety (per-visitor, client-only).** A small inline script in `template.html` keeps the last 5 visited Node ids in `localStorage` (ids only — never sent to a server, never used for anything else) and prefers unvisited candidates from the exact same Stage-1 ranked list, falling back to already-visited ones only when fewer than 3 unvisited candidates exist. It only ever reorders/subsets Stage 1's output — it never re-ranks anything, so relevance always wins over variety. Any failure here (JS disabled, `localStorage` unavailable/blocked/throwing, malformed stored data) silently falls back to the default top-3 already rendered in the HTML — the section can never end up empty or broken because of this layer.

`render_related_section()` remains pure rendering of an already-selected list — it contains no selection logic and doesn't need to change for either stage. `validate_classification_and_priority()` fails the whole build loudly if a published Node's classification references an unknown category/tag id, has a duplicate, has a tag in both `primaryTagIds` and `secondaryTagIds`, is missing a category, has a deprecated field (`relatedNodeIds`, old-shape `classification.primaryCategoryId`/`additionalCategoryIds`/`tagIds`/`priority`), or has an invalid/missing top-level `priority`.

## Topic Navigation — automatic, independent of Related Knowledge

`derive_active_topics()` in `build.py` is the ONE place that decides which Topics are active and what's on each — reused, unchanged, by the Homepage Topic Selector, the All-Topics page, and every individual Topic page, so the three can never disagree. Topic membership is decided by `classification.primaryCategoryIds` ONLY — priority and tags are never consulted here, a deliberate, complete separation from Related Knowledge. An "active Topic" is any registry category (in registry `categories` array order — never alphabetical, so the site owner controls display order by editing one file) that is NOT in `internalCategoryIds` and is assigned to at least one published, available Node; a category with zero matching Nodes never appears anywhere and never gets a page.

* Homepage Topic Selector — a native `<select>` (never free text, never a `#` link) in `homepage-template.html`, showing only active Topics' approved Hebrew names; English category ids never reach the visible page. Navigates to `/topics/{category-id}/` on change.
* Individual Topic pages (`topic-template.html` → `dist/topics/{category-id}/index.html`) — every matching published+available Node as a card, reusing `render_node_card_html()` (no duplicated card logic), plus the same shared `.more-link` pink button (top-level `allTopicsButton` config, `/topics/` destination) used on Node pages and the homepage, placed above the disclaimer.
* All-Topics page (`topics-index-template.html` → `dist/topics/index.html`) — one tile per active Topic (Hebrew name + Node count, rendered as "`{count} תכנים`").
* A Node with multiple `primaryCategoryIds` appears on every one of its Topics' pages. `/topics/` and every active Topic page are added to `sitemap.xml` automatically — only ever the real active set.
* Each Node page has two pink nav buttons, both reusing the exact same `.more-link` CSS, stacked vertically. The first — `render_more_link_button_html()` in `build.py`, text from `moreLinkButton.text` — links to `/topics/{id}/` where `{id}` is `_first_public_topic_id()`: the first non-internal id in that Node's own `classification.primaryCategoryIds`, in array order (array order is the deliberate priority signal here — never any score). If a Node's `primaryCategoryIds` are all internal (e.g. the Template Node), this first button is omitted entirely rather than pointed at a placeholder. The second button is static and always rendered — same top-level `allTopicsButton` config and same `/topics/` destination as the homepage's own button.

## Build behavior

`build_all_published()` builds every Node with `publishing.status == "published"` and `youtube.availability != "unavailable"`. A Node that's published but whose video has gone unavailable is skipped with a warning report, not a hard failure — the rest of the site still builds. Draft / unpublished / archived Nodes are always excluded entirely (never even validated for publication-readiness). Duplicate slugs or ids fail the whole build immediately with a clear error naming the conflicting files.

## YouTube Sync — three-state model

1. YouTube responds, video found → `availability = "available"`, refresh all 6 Sync-managed fields (`title`, `description`, `publishedAt`, `thumbnailUrl`, `availability`, `lastSyncedAt`).
2. YouTube responds, video NOT in the results (confirmed missing) → `availability = "unavailable"`. Previously stored title/description/ publishedAt/thumbnailUrl are preserved, not erased. `lastSyncedAt` still updates (a real check happened).
3. The request itself fails technically (network, timeout, bad/quota'd API key, malformed response) → nothing is touched at all, not even `availability`. Reported as a sync failure, never confused with "video is actually gone."

Sync only ever touches those 6 `youtube.*` fields — never `videoId`, `classification`, top-level `priority`, `publishing`, `clinical`, or anything else. `sync_one_node()` is the primary, canonical engine; `sync_all_nodes()` batches up to 50 video IDs per YouTube API request but funnels every single Node through that exact same underlying logic — the two are guaranteed to produce identical results for the same Node, verified by direct testing, not just by design intent. If an entire batch request fails technically, every Node in that batch is left completely untouched.

## Search Foundations (SEO / AI discoverability)

* `generate_meta_description()` — deterministic, offline (no AI, no network), 155-character limit. Strips only a trailing hashtag block, prefers cutting at a sentence boundary, never cuts mid-word. The exact same short string is reused for `<meta name="description">`, `og:description`, and `twitter:description`. The full original description is never altered on the page itself.
* JSON-LD: `MedicalWebPage` wrapping a `VideoObject` on every Node page; `WebSite` + `Physician`/`Person` (multi-typed) identity on the homepage. Author/reviewer identity is built once from `site-config.json` and reused everywhere — never duplicated into individual Node files.
* `baseUrl` / `aboutUrl` gate every absolute-URL-dependent output (canonical link, `og:url`, sitemap, JSON-LD `@id`). When either is missing/empty, the dependent output is cleanly omitted — never emitted blank, relative, or invalid. The moment a real value is added to `site-config.json`, every affected page picks it up automatically on the next build.
* `robots.txt` and `sitemap.xml` are generated at build time from the exact, real set of pages actually built that run — never a theoretical list. Sitemap entries deliberately have no `<lastmod>` — no field currently exists that honestly represents "this page's content last meaningfully changed" (`youtube.lastSyncedAt` only means "we checked"; inventing a date would be less accurate than omitting it).
* No `meta keywords` anywhere, ever.
* Explicitly out of scope, do not add without a fresh decision: `FAQPage`, `QAPage`, `MedicalCondition`, `Speakable`, `llms.txt`, `BreadcrumbList`, category/Knowledge Center schema, AI-generated summaries, new manual keyword/search-query fields, per-Node author fields.

## GitHub Actions — `.github/workflows/youtube-sync.yml`

Manual trigger only (`workflow_dispatch`) — sync one Node by slug, or all Nodes. Installs `requests`, reads the `YOUTUBE_API_KEY` secret, runs Sync then Build, and commits only `nodes/*.json` (never a broad `git add`) back to the repo, only if something actually changed. Uses the default `GITHUB_TOKEN` for the commit — this means GitHub Actions will never re-trigger itself in a loop, since token-authored commits don't trigger new workflow runs, and this workflow has no `push` trigger anyway.

Never add a `[skip ci]` (or similarly worded) tag to any commit message in this repo. That exact phrase has a separate, unrelated meaning to Cloudflare Pages specifically — it tells Cloudflare to skip deploying — which would silently prevent the live site from ever picking up the change. This was caught and deliberately removed once already; don't reintroduce it.

## Known, deliberate gaps — do not "fix" without asking first

* Public category display names now exist (`categoryLabelsHe` in the registry, used by the Homepage Topic Selector and Topic pages) — but `BreadcrumbList` / other Knowledge-Center-style JSON-LD is still explicitly out of scope (see Search Foundations below); adding it needs a fresh decision, not just because the labels now exist.
* No About page exists yet — `aboutUrl` is intentionally empty in `site-config.json` until it's built.
* Node pages now have two working pink nav buttons — "לעוד תוכן בנושא הזה" (dynamic, links to the Node's own first public Topic) and "לכל הנושאים באתר" (static, same destination as the homepage's own button) — see Topic Navigation above. Resolved 2026-08-04; previously this was an open product decision and the button did nothing (`href="#"`).

## Operational lesson worth knowing

Uploading a file to GitHub through the website only adds or overwrites — it never deletes anything else sitting in that folder. Several past issues in this project (an old draft Node reappearing, an already-removed field coming back) were caused by this — an old file was never actually deleted, just never touched again by later uploads. When verifying repo state, check what's actually there rather than assuming a past cleanup persisted.
