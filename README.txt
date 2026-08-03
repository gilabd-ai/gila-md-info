Knowledge Node System — README
================================

This is the source project for the Gila MD Knowledge Node platform.
It contains NO database, NO CMS, NO JavaScript framework, and needs NO
Node.js/npm build tooling — the build script (written in Python, using
only Python's built-in libraries) reads these source files and writes
plain static HTML files. Those static files are what gets uploaded to
GitHub and hosted on Cloudflare Pages.


0. QUICK NON-TECHNICAL GUIDE
--------------------------------

HOW TO ADD A NEW KNOWLEDGE NODE
    1. Go into the nodes/ folder.
    2. Copy the file nodes/template-node.json and rename the copy — the
       new file name becomes the Node's slug/URL, so use only English
       letters, numbers, and hyphens, e.g.
       nodes/how-to-prepare-for-an-ultrasound.json
       (nodes/template-node.json itself is a permanently reserved Node
       that exists only to be copied. It IS published — it has a real,
       directly-accessible page at /nodes/template-node/ — but its
       classification uses the reserved "template-node" internal
       category, which keeps it out of every public discovery path
       (sitemap.xml, marked "noindex", excluded from Topic navigation).
       Its priority 0 keeps it out of Related Knowledge too. Never
       assign the "template-node" category/tag to a real content Node.)
    3. Open the new file in a plain text editor and fill in:
         - id                                a new unique id, e.g. "node-0002"
         - slug                              must exactly match the file name (no ".json")
         - youtube.videoId                   the YouTube video's ID
         - youtube.title                     becomes the page's title
         - youtube.description                becomes the page's body text
         - youtube.thumbnailUrl              the video's thumbnail image URL
         - classification.primaryCategoryIds  1+ category ids, copied
                                              exactly from
                                              data/code-categories-and-tags.json
                                              — never invent a new one
         - classification.primaryTagIds      0+ tag ids (the Node's main
                                              topics), same registry file
         - classification.secondaryTagIds    0+ tag ids (related but not
                                              central topics), same file —
                                              a tag can't be in both
                                              primaryTagIds and
                                              secondaryTagIds
         - priority                          0 (never recommend this Node
                                              elsewhere), 1 (highest), 2
                                              (normal), or 3 (lowest) — a
                                              top-level field, a sibling of
                                              "classification", not inside
                                              it. No default: the build
                                              fails if it's missing.
         - clinical.lastReviewedAt           the date it was medically reviewed
         - clinical.status                   "current", "needs-review", or "outdated"
         - publishing.status                 "draft" while working on it,
                                              "published" when it's ready to go live
         - publishing.publishedAt            the date it should go live
    4. Save the file. That's the only file you ever need to touch to
       add a new Node — no HTML editing, ever. "Related Knowledge" cards
       are computed automatically at build time from classification and
       priority — see section 1 ("RELATED KNOWLEDGE") below. There is no
       manual related-Node field to fill in.

    If you need a category or tag that doesn't exist yet in
    data/code-categories-and-tags.json, add it there first (it's a simple,
    flat list of English ids) — never write an id into a Node file that
    isn't already present in that registry.

WHICH FILE IS EDITED FOR CONTENT CHANGES
    - To change what's ON a Node's page (title, text, video): edit that
      Node's file in nodes/.
    - To change the doctor's name, social links, disclaimer text, or
      any wording that's the same across the whole site: edit
      site-config.json.
    - Never edit anything inside the dist/ folder by hand — it is
      regenerated from scratch every time the build runs, and any
      manual edit there will be silently thrown away.

HOW TO RUN A PREVIEW (before a Node is finished/published)
    python3 build.py --node YOUR-SLUG-HERE
    Then open dist/nodes/YOUR-SLUG-HERE/index.html in a browser. This
    works even while the Node is still marked "draft", and it also
    refreshes the homepage and disclaimer page so the links between
    pages work while you're previewing.

HOW TO RUN THE PRODUCTION BUILD (before publishing for real)
    python3 build.py --all
    This builds the homepage, the Medical Disclaimer page, and every
    Node whose publishing.status is exactly "published" — nothing
    marked "draft", "unpublished", or "archived" is ever included. If
    any Node marked "published" is missing a required field, the build
    stops immediately and tells you exactly what's missing — it will
    never silently publish something incomplete.

WHAT GETS UPLOADED TO GITHUB
    Everything in this project folder gets pushed to the GitHub
    repository, EXCEPT the dist/ folder — Cloudflare regenerates that
    from source on every deploy, so it doesn't need to be committed.
    Simplest approach: commit everything except dist/ (add a
    .gitignore file containing "dist/"), and let Cloudflare run the
    build command below on every push.

HOW CLOUDFLARE PUBLISHES THE RESULT
    Cloudflare Pages is connected to the GitHub repository. On every
    push, it runs the build command (python3 build.py --all), then
    publishes whatever ends up in the dist/ folder as the live website.
    See section 6 for the exact settings.


1. WHAT EACH FILE / FOLDER DOES
-----------------------------------

template.html
    The single shared HTML/CSS/JS template used for every Knowledge
    Node. This is the exact approved design — header, video player,
    read-more toggle, related cards, disclaimer strip — refactored to
    take {{TOKEN}} placeholders instead of hand-written content, so
    it can be reused for every Node.

homepage-template.html
    The shared template for the site's real homepage: same header and
    branding as a Node page, a short intro, and a list of every
    published Knowledge Node. (Knowledge Centers and a search bar are
    NOT built yet — see section 7, "Known gaps".)

disclaimer-template.html
    The shared template for the permanent Medical Disclaimer page.
    Same header/branding as a Node page, the full approved Hebrew
    disclaimer text, and a link back to the homepage. Deliberately has
    no video, no related-content cards, and no "more content" button.

approved-node-reference.html
    The original, hand-built, fully working "does a gynecological exam
    hurt" page exactly as it was approved. This file is kept only as a
    visual/behavioral reference to check the build system's output
    against — it is NOT used by the build and is never uploaded to
    GitHub or Cloudflare.

site-config.json
    Global site-wide data that is the same on every page: the doctor's
    name/title, the logo, the four social-media links, the short
    disclaimer strip text + link, the homepage's intro text, and the
    full Medical Disclaimer page content.

RELATED KNOWLEDGE
    Fully automatic, computed at build time from each Node's
    classification and priority — there is no manual field to fill in.
    Two stages:

    1. BUILD-TIME RANKING (same for every visitor, deterministic):
       select_related_nodes() in build.py scores every other eligible
       Node against the current one and returns up to 10 candidates,
       best first. A candidate must share at least one category, primary
       tag, or secondary tag with the current Node (a Node's own
       priority never makes it eligible on its own) and must not be a
       draft, priority 0 ("never recommend"), or have an unavailable
       video. Scoring: a shared tag scores +100 if it's a primary topic
       on both Nodes, or +50 if it's primary on only one side or
       secondary on both (the topic is still genuinely shared, just not
       central to both); a shared category scores +50; the candidate's
       own priority adds +100 (priority 1), +50 (priority 2), or +0
       (priority 3). Ties keep the Nodes' existing load order. The
       page's default 3 cards (and its full ranked-candidate list, for
       the browser script below) come directly from this ranking — see
       render_related_section() for the pure-rendering half, which
       never changes for this reason.
    2. BROWSER-SIDE VARIETY (per-visitor, client-only): a small inline
       script in template.html remembers the last 5 Node ids a visitor
       looked at, in the browser's own localStorage (never sent to any
       server, never anything but ids). It then prefers unvisited
       candidates from the SAME ranked list above, falling back to
       already-visited ones only if fewer than 3 unvisited candidates
       exist. It only ever reorders/subsets the build-time ranking — it
       never re-ranks anything, and relevance always wins over variety.
       If JavaScript is off, or localStorage is unavailable/blocked/
       throws/holds malformed data, the visitor just sees the default
       top-3 that's already in the HTML — the section is never empty or
       broken.
    - A Node's page can show zero, one, two, or three Related cards,
      depending on how many eligible candidates exist — the section
      (and its heading) is omitted entirely when there are zero.
    - The build validates every published Node's classification via
      validate_classification_and_priority() in build.py: every
      category/tag id must exist in data/code-categories-and-tags.json, no
      duplicates, no tag in both primaryTagIds and secondaryTagIds, a
      published Node must have at least one category, and priority must
      be exactly 0/1/2/3. Invalid data fails the build with a clear
      error naming the Node's slug, its source file, and the problem.

nodes/  (folder)
    One JSON file per Knowledge Node, following Node Schema v1.0. Each
    file holds everything specific to that one Node, including its
    classification (see "RELATED KNOWLEDGE" above for how that drives
    the Related Knowledge cards automatically).

data/code-categories-and-tags.json
    The single canonical registry of every approved category and tag id
    — a flat list of plain English ids, e.g. "gynecological-exams",
    "pelvic-exam". This is a controlled pool: a Node's classification
    may only use ids that are already in this file. The registry is
    expected to grow over time, but only after explicit approval from
    the site owner — new categories/tags are added here first, by a
    person, before any Node can use them. Existing ids must never be
    silently renamed; that would break classification consistency and
    Related Knowledge matching for every Node already using that id.

    "internalCategoryIds" is a separate array within this same file
    marking categories reserved for technical/editorial Nodes only —
    currently just "template-node". A Node may use an internal
    category, and it still gets a real, directly-accessible built page,
    but it is automatically excluded from sitemap.xml, marked
    "noindex", and excluded from public Topic navigation (see
    _is_internal_only() in build.py). Internal categories are reserved
    for technical or editorial Nodes only. They must never be used for
    normal public medical content.

docs/gila-categories-and-tags.html
    An internal, English-only, human-readable reference page listing
    every approved category and its tags — for the site owner to browse
    and copy exact ids from. Generated by generate_categories_doc.py
    directly from data/code-categories-and-tags.json (plus a small
    editorial grouping of which tags to display under which category),
    and cross-validated against it at generation time, so this page can
    never disagree with the canonical registry. It is NOT part of the
    public website and is never copied into dist/. Re-run
    `python3 generate_categories_doc.py` after the registry changes to
    regenerate it.

docs/gila-node-dashboard.html
    An internal, English-only editorial dashboard listing every Node
    (published, draft, and the reserved template Node) with its
    classification, priority, publication/sync dates, a validation
    status, and the full ranked Related Knowledge candidate list with a
    score explanation for each one — so the site owner can review
    classification and catch recommendation problems before publishing
    more Nodes. Generated by generate_node_dashboard.py directly from
    the current Node files and the exact same production scoring
    functions build.py uses for the real site (never a second,
    independently recreated scoring formula). It is a GENERATED VIEW
    ONLY, not a source of truth, NOT part of the public website, never
    linked from any public page, and never copied into dist/. Re-run
    `python3 generate_node_dashboard.py` after any Node change to
    regenerate it.

assets/  (folder)
    Shared binary/text assets referenced by the templates — currently
    just logo-base64.txt, the Gila MD logo image encoded as base64
    text so it can be embedded directly into the generated HTML.

build.py
    The build script. Reads the templates + site-config.json +
    everything in nodes/, validates it, and writes final static HTML
    files into dist/. See section 4 for commands.

dist/  (folder, generated — not part of this ZIP/repo's source content)
    The actual deployable website. Fully regenerated from the source
    files every time build.py runs; safe to delete at any time.


2. WHICH FILES ARE SOURCE FILES
-----------------------------------

Everything except dist/ is a source file:
    template.html, homepage-template.html, disclaimer-template.html,
    approved-node-reference.html (reference only, unused by the build),
    site-config.json, build.py, nodes/*.json, assets/*

None of these are the live website by themselves — they exist so the
build script can generate the real deployable output.


3. URL CONVENTION
---------------------

Clean, slug-based, folder-style URLs (this was the convention already
implied by the original project and is unchanged here):

    /                              -> homepage
    /nodes/{slug}/                 -> one specific Knowledge Node
    /medical-disclaimer/           -> the permanent Medical Disclaimer page


4. BUILD COMMANDS
---------------------

Production build (every published Node + homepage + disclaimer page):
    python3 build.py --all

Development preview of one Node by slug, regardless of its publishing
status (drafts can be previewed this way); also refreshes the homepage
and disclaimer page so links work locally. Related cards in the
preview only ever show targets that are themselves published, so the
preview reflects what production would actually show:
    python3 build.py --node template-node

Output always goes to dist/:
    dist/index.html                           (homepage)
    dist/nodes/{slug}/index.html               (one per published Node)
    dist/medical-disclaimer/index.html         (Medical Disclaimer page)


5. GITHUB → CLOUDFLARE PAGES DEPLOYMENT
--------------------------------------------

This project is prepared for GitHub → Cloudflare Pages, but is NOT
deployed or connected to the live site yet — that is a deliberate,
separate step so nothing on the current live site is overwritten
accidentally.

When ready to connect it:
    1. Push this whole project (everything except dist/) to a GitHub
       repository.
    2. In Cloudflare Pages, create a new project connected to that
       repository.
    3. Framework preset:      None
    4. Build command:         python3 build.py --all
    5. Build output directory: dist
    6. (Recommended, not required) Add a file named .python-version
       to the project root containing "3.12" so Cloudflare always uses
       a modern, predictable Python version. The build script only
       uses Python's standard library, so no dependency installation
       step is needed.
    7. Clean URLs: Cloudflare Pages serves an index.html inside a
       folder at that folder's URL automatically (e.g. the file
       dist/nodes/{slug}/index.html is served at /nodes/{slug}/), so
       no extra redirect/rewrite configuration is required.

Do not connect this to the current live production site until it has
been reviewed and approved — that step is intentionally left for a
separate, explicit go-ahead.


6. VERIFICATION — WHAT WAS ACTUALLY RUN AND CONFIRMED
-----------------------------------------------------------

    - Dev build of a single Node by slug (ignoring publishing status):
      succeeded, produced dist/nodes/{slug}/index.html, and also
      refreshed the homepage + disclaimer page.
    - Production build with the Node still in "draft": succeeded,
      built 0 Nodes, explicitly listed the draft Node as excluded,
      and still built the homepage + disclaimer page.
    - Duplicate slug test: build failed immediately with a clear
      message naming both conflicting files.
    - "Published" Node missing required fields test: build failed
      immediately, listing every specific missing field.
    - Malformed JSON test: build failed immediately with the exact
      JSON parse error and file path.
    - Node file missing required top-level sections test: build
      failed immediately, naming the missing sections.
    - "unpublished" and "archived" status Nodes: both correctly
      excluded from the production build, alongside "draft".
    - Full end-to-end test with a temporary fully-valid "published"
      Node: it appeared on the homepage, its own page linked correctly
      to /medical-disclaimer/ and to / (home), and the disclaimer page
      linked correctly back to / (home). All confirmed by inspecting
      the generated HTML directly, then the temporary test Node was
      removed.
    - Medical Disclaimer page confirmed to: use the shared header, be
      marked dir="rtl" with a responsive viewport tag, contain all 9
      paragraphs of the approved Hebrew disclaimer text, and contain
      NO video/related-cards/more-content-button markup.


7. CURRENT STATUS / KNOWN GAPS
------------------------------------

DONE / stable (unchanged from the approved design):
    - Header, home nav bar, video viewer, title, description with
      read-more/show-less, three related-cards, "לעוד תוכן בנושא"
      button, medical disclaimer strip — all pixel- and behavior-
      identical to the originally approved Node.

NEWLY BUILT in this pass:
    - Real build system with nodes/ and assets/ folders (previously
      the one Node file and the logo file sat loose at the project
      root instead of in the folders the README already described).
    - Real homepage (dist/index.html) — previously just a placeholder
      redirect. Lists every published Node.
    - Permanent Medical Disclaimer page at /medical-disclaimer/ with
      the full approved Hebrew text.
    - Disclaimer-strip link and home-nav-bar link now point to the
      real pages instead of "#".
    - Stronger validation: malformed JSON and Node files missing
      required top-level sections now fail the build with a clear
      message, instead of crashing unpredictably partway through.

STILL OPEN / needs a decision before real production publishing:
    - No Knowledge Centers (topic pages) or search bar exist yet —
      both need a topic/category data model that hasn't been designed.
      The homepage currently lists Nodes directly instead. This is a
      deliberate scope decision, not an oversight (see build.py,
      build_homepage()).
    - Related Knowledge is now fully automatic — build-time ranking by
      shared category/tag/priority, plus a browser-side variety layer
      (see section 1, "RELATED KNOWLEDGE"). There is no manual
      relatedNodeIds field anymore.
    - No Node-creation interface yet — adding a Node still means
      creating a nodes/{slug}.json file by hand (see section 0).
    - No automatic YouTube import yet — Node data (title, description,
      video ID) is still entered by hand into each JSON file. This
      was explicitly kept out of scope for this pass.
