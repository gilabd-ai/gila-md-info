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

There is no separate schema/template file. The de facto template for creating a new Node is the real file `nodes/gynecological-exam-tip-move-forward.json` — copy it as the starting point for any new Node.

⚠️ Whenever the Node schema changes (fields added, removed, or renamed), update that template Node AND `README.txt`'s manual Node-creation instructions in the same change. This has been forgotten before and caused real drift — treat it as a checklist item, not optional.

Fields on every Node (`nodes/{slug}.json`):

```
schemaVersion
id                          "node-000N"
slug                        must exactly match the filename (no ".json")
relatedNodeIds              optional array, max 3 ids, MANUAL selection today
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
  primaryCategoryId          a real category, or "unassigned" — never invent one
  additionalCategoryIds
  tagIds
  priority                   "high" | "normal" | "low"
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

## `template.html` and the `{{TOKEN}}` system

`build.py` does plain string-replacement of `{{TOKEN}}` placeholders in `template.html` (and `homepage-template.html`, `disclaimer-template.html`). These tokens never move and are always safe to rely on: `{{PAGE_TITLE}}`, `{{SEO_META_TAGS}}`, `{{JSONLD_SCRIPT}}`, `{{SITE_LOGO_BASE64}}`, `{{NODE_TITLE}}`, `{{NODE_DESCRIPTION}}`, `{{VIDEO_ID}}`, `{{RELATED_SECTION_HTML}}`, and others for header/nav/disclaimer text pulled from `site-config.json`.

## `site-config.json` — global, site-wide data

`siteName`, `language`, `direction`, `baseUrl` (`"https://drgilamd.com"`), `aboutUrl` (currently `""` — the About page doesn't exist yet), `header` (doctor's name/role), `socialLinks`, `uiLabels`, homepage/disclaimer content blocks, `moreLinkButton`, `homeNavBar`.

## Related Knowledge

Manual today, via each Node's `relatedNodeIds`. Deliberately split into two functions so automatic (category/tag-based) selection can replace only one of them later without touching rendering or the approved card design:

* `select_related_nodes()` — decides WHICH Nodes are related. This is the only seam that should ever change for automatic selection.
* `render_related_section()` — pure rendering of an already-selected list. Contains no selection logic and should never need to change for this reason.

Rules enforced: never self, only Nodes that exist, only published Nodes in production, never a Node whose `youtube.availability == "unavailable"` (its page isn't built at all, so linking to it would be a dead link), no duplicates, capped at 3. `validate_related_node_ids()` fails the whole build loudly if a published Node's `relatedNodeIds` is malformed, self-referential, duplicated, over 3 entries, or points at a non-existent or non-published Node — manual Related data is meant to be exact, not silently wrong.

## Build behavior

`build_all_published()` builds every Node with `publishing.status == "published"` and `youtube.availability != "unavailable"`. A Node that's published but whose video has gone unavailable is skipped with a warning report, not a hard failure — the rest of the site still builds. Draft / unpublished / archived Nodes are always excluded entirely (never even validated for publication-readiness). Duplicate slugs or ids fail the whole build immediately with a clear error naming the conflicting files.

## YouTube Sync — three-state model

1. YouTube responds, video found → `availability = "available"`, refresh all 6 Sync-managed fields (`title`, `description`, `publishedAt`, `thumbnailUrl`, `availability`, `lastSyncedAt`).
2. YouTube responds, video NOT in the results (confirmed missing) → `availability = "unavailable"`. Previously stored title/description/ publishedAt/thumbnailUrl are preserved, not erased. `lastSyncedAt` still updates (a real check happened).
3. The request itself fails technically (network, timeout, bad/quota'd API key, malformed response) → nothing is touched at all, not even `availability`. Reported as a sync failure, never confused with "video is actually gone."

Sync only ever touches those 6 `youtube.*` fields — never `videoId`, `classification`, `tags`, `priority`, `relatedNodeIds`, `publishing`, `clinical`, or anything else. `sync_one_node()` is the primary, canonical engine; `sync_all_nodes()` batches up to 50 video IDs per YouTube API request but funnels every single Node through that exact same underlying logic — the two are guaranteed to produce identical results for the same Node, verified by direct testing, not just by design intent. If an entire batch request fails technically, every Node in that batch is left completely untouched.

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

* No category/tag display-name lookup exists yet (`classification.primaryCategoryId` is just a slug, e.g. `"gynecological-exams"`) — this blocks things like `BreadcrumbList` until a real "Knowledge Centers" data model is designed.
* No About page exists yet — `aboutUrl` is intentionally empty in `site-config.json` until it's built.
* `homepage-template.html` is scheduled for a full future rebuild from scratch — avoid investing further design polish into its current version.

## Operational lesson worth knowing

Uploading a file to GitHub through the website only adds or overwrites — it never deletes anything else sitting in that folder. Several past issues in this project (an old draft Node reappearing, an already-removed field coming back) were caused by this — an old file was never actually deleted, just never touched again by later uploads. When verifying repo state, check what's actually there rather than assuming a past cleanup persisted.
