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
    2. Copy the file nodes/gynecological-exam-tip-move-forward.json and
       rename the copy — the new file name becomes the Node's slug/URL,
       so use only English letters, numbers, and hyphens, e.g.
       nodes/how-to-prepare-for-an-ultrasound.json
    3. Open the new file in a plain text editor and fill in:
         - id                                a new unique id, e.g. "node-0002"
         - slug                              must exactly match the file name (no ".json")
         - youtube.videoId                   the YouTube video's ID
         - youtube.title                     becomes the page's title
         - youtube.description                becomes the page's body text
         - youtube.thumbnailUrl              the video's thumbnail image URL
         - classification.primaryCategoryId  a real topic, not "unassigned"
         - classification.priority           "high", "normal", or "low"
         - clinical.lastReviewedAt           the date it was medically reviewed
         - clinical.status                   "current", "needs-review", or "outdated"
         - publishing.status                 "draft" while working on it,
                                              "published" when it's ready to go live
         - publishing.publishedAt            the date it should go live
         - relatedNodeIds (optional)         a list of up to 3 other Nodes'
                                              "id" values, to show as
                                              "Related Knowledge" cards on
                                              this Node's page — see
                                              section 1 ("RELATED
                                              KNOWLEDGE") below
    4. Save the file. That's the only file you ever need to touch to
       add a new Node — no HTML editing, ever.

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
    Each Node's JSON file may include an optional top-level
    "relatedNodeIds" array of up to 3 other Nodes' "id" values, e.g.:

        "relatedNodeIds": ["node-0003", "node-0004"]

    - Selection is currently manual: a person lists the ids by hand,
      in the order they should appear. There is no automatic
      selection yet — matching by category, tag, or a combination of
      both is a planned future step, but is NOT implemented now.
    - Only the id is stored. Title, description, and link are always
      read at build time from the real target Node's own JSON file.
    - A Node's page can show zero, one, two, or three Related cards,
      depending on how many valid ids are listed — the section (and
      its heading) is omitted entirely when there are zero.
    - The build validates this field for every published Node: it
      must be an array of existing, distinct, non-self ids, max 3
      entries, and every referenced Node must itself be published.
      Invalid data fails the build with a clear error naming the
      Node's slug, its source file, and the offending id.
    - See select_related_nodes() and render_related_section() in
      build.py — selection and rendering are separate functions, so
      the manual selection can later be replaced by automatic
      selection without touching the rendering code, the Node page
      template, or the approved card design.

nodes/  (folder)
    One JSON file per Knowledge Node, following Node Schema v1.0. Each
    file holds everything specific to that one Node, including its
    optional "relatedNodeIds" (see "RELATED KNOWLEDGE" above).

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
    python3 build.py --node gynecological-exam-tip-move-forward

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
    - Related Knowledge now uses real Node data via the manual
      "relatedNodeIds" field (see section 1, "RELATED KNOWLEDGE").
      Automatic selection by category/tag matching is planned but has
      NOT been built yet — only the manual-selection version exists
      so far.
    - No Node-creation interface yet — adding a Node still means
      creating a nodes/{slug}.json file by hand (see section 0).
    - No automatic YouTube import yet — Node data (title, description,
      video ID) is still entered by hand into each JSON file. This
      was explicitly kept out of scope for this pass.
