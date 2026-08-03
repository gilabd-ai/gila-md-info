#!/usr/bin/env python3
"""
generate_node_dashboard.py — builds docs/gila-node-dashboard.html.

Internal, English-only editorial tool for the site owner — NOT part of
the public site, never copied into dist/, never linked from any public
page, not in sitemap.xml. It exists so a human can see every Node at
once (published, draft, and the reserved template Node), review its
classification/priority, and understand exactly why the automatic
Related Knowledge engine ranked its candidates the way it did — all
without opening JSON files or re-deriving scores by hand.

This is a GENERATED VIEW ONLY. The sources of truth remain the Node
JSON files, data/code-categories-and-tags.json, and the production
scoring logic in build.py. This script never writes back to any Node
file, and never recreates the scoring formula — every score and score
breakdown shown here comes directly from build.score_related_candidates()
and build.ineligible_candidate_reason(), the exact same functions the
public site's Related Knowledge feature uses (see build.py's
select_related_nodes(), a thin wrapper around the same function). If
those functions ever change, this dashboard picks up the change
automatically the next time it's regenerated — there is no second
formula here that could drift out of sync.

Usage:
    python3 generate_node_dashboard.py
"""

import html
import json
from pathlib import Path

import build
import node_store

BASE_DIR = Path(__file__).parent
OUTPUT_PATH = BASE_DIR / "docs" / "gila-node-dashboard.html"

MAIN_TABLE_COLUMNS = [
    "Node ID", "Slug", "YouTube Title", "Publishing Status", "Availability",
    "Priority", "Primary Categories", "Primary Tags", "Secondary Tags",
    "YouTube Published At", "Node Published At", "Last YouTube Sync",
    "Validation Status",
]


def _is_internal(node: dict, registry: dict) -> bool:
    """
    True iff every one of the Node's primaryCategoryIds is an internal
    category (registry["internalCategoryIds"]) — registry-driven, not a
    hardcoded "template-node" string check, so this correctly covers any
    future internal category too, not just the one template Node.
    """
    category_ids = node.get("classification", {}).get("primaryCategoryIds") or []
    if not category_ids:
        return False
    return set(category_ids) <= registry.get("internalCategoryIds", set())


def _validation_status(node: dict, registry: dict) -> tuple[str, list[str]]:
    """
    Returns ("OK" | "Warning" | "Error", [issue strings]). Reuses the
    exact same validation functions build_all_published() runs — never
    a separately re-implemented check. A published Node with issues is
    an Error (should never happen in a healthy repo — this dashboard is
    a drift detector for that). A non-published Node with issues is a
    Warning (expected while still being drafted). No issues -> OK.
    """
    issues = build.validate_for_publication(node) + build.validate_classification_and_priority(node, registry)
    if not issues:
        return "OK", []
    if node.get("publishing", {}).get("status") == "published":
        return "Error", issues
    return "Warning", issues


def _chip_list(ids: list[str]) -> str:
    if not ids:
        return '<span class="muted">—</span>'
    return '<ul class="tag-list">' + "".join(
        f'<li class="tag-chip"><code>{html.escape(i, quote=True)}</code></li>' for i in ids
    ) + "</ul>"


def _copy_code(value: str) -> str:
    if not value:
        return '<span class="muted">—</span>'
    return f'<code class="copyable">{html.escape(value, quote=True)}</code>'


def build_dashboard_rows(all_nodes: list[dict], nodes_by_id: dict[str, dict], registry: dict) -> list[dict]:
    """
    Computes everything the template needs for one Node, in one place,
    so render_html() stays pure presentation. published_only=True is
    used for score_related_candidates()/ineligible_candidate_reason() so
    the dashboard shows exactly what the production build would compute
    for each Node — never a hypothetical.
    """
    rows = []
    for node in sorted(all_nodes, key=lambda n: n.get("slug", "")):
        classification = node.get("classification", {})
        yt = node.get("youtube", {})
        publishing = node.get("publishing", {})
        status, issues = _validation_status(node, registry)

        own_exclusion_reason = build.ineligible_candidate_reason(node, published_only=True)
        candidates = build.score_related_candidates(node, nodes_by_id, published_only=True)

        rows.append({
            "id": node.get("id", ""),
            "slug": node.get("slug", ""),
            "title": yt.get("title") or "",
            "status": publishing.get("status", ""),
            "availability": yt.get("availability") or "",
            "priority": node.get("priority"),
            "primary_categories": classification.get("primaryCategoryIds") or [],
            "primary_tags": classification.get("primaryTagIds") or [],
            "secondary_tags": classification.get("secondaryTagIds") or [],
            "youtube_published_at": yt.get("publishedAt") or "",
            "node_published_at": publishing.get("publishedAt") or "",
            "last_synced": yt.get("lastSyncedAt") or "",
            "validation_status": status,
            "validation_issues": issues,
            "is_internal": _is_internal(node, registry),
            "own_exclusion_reason": own_exclusion_reason,
            "candidates": candidates,
        })
    return rows


def render_candidate_breakdown(breakdown: list[dict]) -> str:
    lines = "".join(
        f'<li><span class="points">{"+" if b["points"] >= 0 else ""}{b["points"]}</span> {html.escape(b["label"], quote=True)}</li>'
        for b in breakdown
    )
    total = sum(b["points"] for b in breakdown)
    return (
        '<details class="breakdown">'
        '<summary>Score breakdown ▸</summary>'
        f'<ul class="breakdown-list">{lines}</ul>'
        f'<p class="breakdown-total">Total: {total}</p>'
        '</details>'
    )


def render_candidates_section(row: dict) -> str:
    parts = []
    if row["own_exclusion_reason"] is not None:
        parts.append(
            '<p class="exclusion-note">This Node is never recommended elsewhere: '
            f'<strong>{html.escape(row["own_exclusion_reason"], quote=True)}</strong></p>'
        )
    if row["is_internal"]:
        parts.append(
            '<p class="exclusion-note">Internal category — excluded from sitemap.xml, marked '
            '<strong>noindex</strong>, and excluded from public Topic navigation. Still built as a '
            'normal, directly-accessible page.</p>'
        )

    candidates = row["candidates"]
    if not candidates:
        parts.append('<p class="no-candidates">No eligible candidates</p>')
        return "\n".join(parts)

    candidate_rows = []
    for i, entry in enumerate(candidates):
        c = entry["node"]
        in_top_3 = i < build.MAX_RELATED_CARDS
        candidate_rows.append(
            "<tr>"
            f"<td>{i + 1}</td>"
            f"<td>{_copy_code(c.get('id', ''))}</td>"
            f"<td>{html.escape(c.get('youtube', {}).get('title') or '', quote=True)}</td>"
            f"<td>{_copy_code(c.get('slug', ''))}</td>"
            f"<td class=\"num\">{entry['score']}</td>"
            f"<td class=\"num\">{c.get('priority')}</td>"
            f"<td>{'Yes' if in_top_3 else 'No'}</td>"
            f"<td>{render_candidate_breakdown(entry['breakdown'])}</td>"
            "</tr>"
        )

    parts.append(
        '<table class="candidates-table">'
        '<thead><tr><th>#</th><th>Candidate ID</th><th>Candidate Title</th><th>Candidate Slug</th>'
        '<th>Score</th><th>Priority</th><th>In Default Top 3</th><th>Explanation</th></tr></thead>'
        f'<tbody>{"".join(candidate_rows)}</tbody>'
        '</table>'
    )
    return "\n".join(parts)


def render_row(row: dict) -> str:
    search_terms = " ".join([
        row["id"], row["slug"], row["title"], row["status"], str(row["priority"]),
        *row["primary_categories"], *row["primary_tags"], *row["secondary_tags"],
    ]).lower()

    status_badge = f'<span class="badge badge-{row["validation_status"].lower()}">{row["validation_status"]}</span>'
    internal_badge = ' <span class="badge badge-internal">Internal Category</span>' if row["is_internal"] else ""

    cells = [
        _copy_code(row["id"]),
        _copy_code(row["slug"]),
        html.escape(row["title"], quote=True) + internal_badge,
        html.escape(row["status"], quote=True),
        html.escape(row["availability"], quote=True) if row["availability"] else '<span class="muted">—</span>',
        str(row["priority"]) if row["priority"] is not None else '<span class="muted">—</span>',
        _chip_list(row["primary_categories"]),
        _chip_list(row["primary_tags"]),
        _chip_list(row["secondary_tags"]),
        html.escape(row["youtube_published_at"], quote=True) if row["youtube_published_at"] else '<span class="muted">—</span>',
        html.escape(row["node_published_at"], quote=True) if row["node_published_at"] else '<span class="muted">—</span>',
        html.escape(row["last_synced"], quote=True) if row["last_synced"] else '<span class="muted">—</span>',
        status_badge,
    ]
    cells_html = "".join(f"<td>{c}</td>" for c in cells)

    n_candidates = len(row["candidates"])
    summary_row = (
        f'<tr class="node-row" data-search="{html.escape(search_terms, quote=True)}" '
        f'data-status="{html.escape(row["status"], quote=True)}" '
        f'data-priority="{row["priority"]}" '
        f'data-availability="{html.escape(row["availability"] or "", quote=True)}" '
        f'data-internal="{"yes" if row["is_internal"] else "no"}">'
        f'{cells_html}</tr>'
    )
    details_row = (
        '<tr class="details-row">'
        f'<td colspan="{len(MAIN_TABLE_COLUMNS)}">'
        f'<details><summary>Related Candidates ({n_candidates})</summary>'
        f'{render_candidates_section(row)}'
        '</details></td></tr>'
    )
    return summary_row + "\n" + details_row


def render_html(rows: list[dict]) -> str:
    headers_html = "".join(f"<th>{html.escape(c, quote=True)}</th>" for c in MAIN_TABLE_COLUMNS)
    rows_html = "\n".join(render_row(r) for r in rows)

    statuses = sorted({r["status"] for r in rows})
    status_options = "".join(f'<option value="{html.escape(s, quote=True)}">{html.escape(s, quote=True)}</option>' for s in statuses)

    return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Node Dashboard</title>
<style>
  :root {{
    --ink: #20302c;
    --paper: #f6f3ec;
    --paper-raised: #ffffff;
    --teal: #1f4d46;
    --line: rgba(32,48,44,0.14);
    --ok: #1f4d46;
    --warning: #c99a2e;
    --error: #c65f48;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px 16px 64px;
    background: var(--paper);
    color: var(--ink);
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    max-width: 1400px;
    margin-inline: auto;
  }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  .intro {{
    background: var(--paper-raised);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 14px;
    line-height: 1.6;
    margin-bottom: 20px;
  }}
  .intro code {{ background: rgba(31,77,70,0.08); padding: 1px 5px; border-radius: 4px; }}
  .controls {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 16px;
  }}
  .controls input, .controls select {{
    padding: 8px 10px;
    font-size: 13.5px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--paper-raised);
    color: var(--ink);
  }}
  #searchBox {{ flex: 1; min-width: 220px; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  thead th {{
    position: sticky; top: 0;
    background: var(--teal);
    color: #fff;
    text-align: left;
    padding: 10px 10px;
    white-space: nowrap;
    z-index: 1;
  }}
  tbody td {{ padding: 8px 10px; border-top: 1px solid var(--line); vertical-align: top; background: var(--paper-raised); }}
  tr.node-row.hidden, tr.details-row.hidden {{ display: none; }}
  tr.details-row td {{ background: #fbfaf6; }}
  .muted {{ color: #8b968f; }}
  code {{ font-family: ui-monospace, Consolas, monospace; }}
  code.copyable {{
    background: rgba(31,77,70,0.08);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 2px 6px;
    cursor: pointer;
  }}
  code.copyable.copied {{ background: var(--teal); color: #fff; }}
  .tag-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px; }}
  .tag-chip code {{ font-size: 12px; padding: 1px 6px; }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    color: #fff;
  }}
  .badge-ok {{ background: var(--ok); }}
  .badge-warning {{ background: var(--warning); }}
  .badge-error {{ background: var(--error); }}
  .badge-internal {{ background: #5c6b64; }}
  details summary {{ cursor: pointer; font-weight: 600; color: var(--teal); }}
  .exclusion-note {{ font-size: 13px; color: var(--warning); }}
  .no-candidates {{ font-size: 13px; color: #8b968f; font-style: italic; }}
  table.candidates-table {{ margin-top: 10px; font-size: 12.5px; }}
  table.candidates-table thead th {{ background: #5c6b64; position: static; }}
  .num {{ font-variant-numeric: tabular-nums; text-align: right; }}
  details.breakdown summary {{ font-size: 12px; font-weight: 500; }}
  .breakdown-list {{ list-style: none; margin: 4px 0; padding: 0; font-size: 12px; }}
  .breakdown-list li {{ padding: 2px 0; }}
  .breakdown-list .points {{ font-variant-numeric: tabular-nums; display: inline-block; min-width: 34px; color: var(--teal); font-weight: 600; }}
  .breakdown-total {{ font-size: 12px; font-weight: 700; margin: 4px 0 0; }}
</style>
</head>
<body>

<h1>Node Dashboard</h1>

<div class="intro">
  <p>Internal editorial view of every Node — generated from the current repository data. It is NOT a source of truth (the Node JSON files and <code>data/code-categories-and-tags.json</code> are), not part of the public site, and not linked from anywhere public. Regenerate after any Node change with <code>python3 generate_node_dashboard.py</code>. Related Candidate scores come directly from the production scoring functions in <code>build.py</code> — never a separately recreated formula.</p>
</div>

<div class="controls">
  <input id="searchBox" type="text" placeholder="Search ID, slug, title, status, priority, categories, tags…" autocomplete="off">
  <select id="statusFilter"><option value="">All statuses</option>{status_options}</select>
  <select id="priorityFilter">
    <option value="">All priorities</option>
    <option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option>
  </select>
  <select id="availabilityFilter">
    <option value="">Available / Unavailable</option>
    <option value="available">Available</option>
    <option value="unavailable">Unavailable</option>
  </select>
  <select id="internalFilter">
    <option value="">Internal / Public category</option>
    <option value="yes">Internal only</option>
    <option value="no">Public only</option>
  </select>
</div>

<div class="table-wrap">
  <table>
    <thead><tr>{headers_html}</tr></thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
</div>

<script>
  function applyFilters(){{
    const q = document.getElementById('searchBox').value.trim().toLowerCase();
    const status = document.getElementById('statusFilter').value;
    const priority = document.getElementById('priorityFilter').value;
    const availability = document.getElementById('availabilityFilter').value;
    const internal = document.getElementById('internalFilter').value;

    document.querySelectorAll('tr.node-row').forEach(function(row){{
      const haystack = row.dataset.search || '';
      let visible = true;
      if (q && !haystack.includes(q)) visible = false;
      if (status && row.dataset.status !== status) visible = false;
      if (priority && row.dataset.priority !== priority) visible = false;
      if (availability && row.dataset.availability !== availability) visible = false;
      if (internal && row.dataset.internal !== internal) visible = false;

      row.classList.toggle('hidden', !visible);
      const details = row.nextElementSibling;
      if (details && details.classList.contains('details-row')) {{
        details.classList.toggle('hidden', !visible);
      }}
    }});
  }}

  document.getElementById('searchBox').addEventListener('input', applyFilters);
  document.getElementById('statusFilter').addEventListener('change', applyFilters);
  document.getElementById('priorityFilter').addEventListener('change', applyFilters);
  document.getElementById('availabilityFilter').addEventListener('change', applyFilters);
  document.getElementById('internalFilter').addEventListener('change', applyFilters);

  document.querySelectorAll('code.copyable').forEach(function(el){{
    el.addEventListener('click', function(){{
      const text = el.textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(function(){{
          el.classList.add('copied');
          setTimeout(function(){{ el.classList.remove('copied'); }}, 500);
        }}).catch(function(){{}});
      }}
    }});
  }});
</script>

</body>
</html>
"""


def main():
    all_nodes, nodes_by_id = node_store.load_all_nodes_checked()
    registry = build.load_categories_and_tags()
    rows = build_dashboard_rows(all_nodes, nodes_by_id, registry)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_html(rows), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Nodes: {len(rows)}")


if __name__ == "__main__":
    main()
