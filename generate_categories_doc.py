#!/usr/bin/env python3
"""
generate_categories_doc.py — builds docs/gila-categories-and-tags.html.

This is an internal, English-only reference page for the site owner —
NOT part of the public site, and never copied into dist/. It exists so
a human can browse the approved category/tag IDs and copy them exactly,
without ever hand-maintaining a second, independently-typed list that
could drift from data/code-categories-and-tags.json.

Every id shown on the page is read from the registry (the flat
"categories"/"tags" arrays) — the CATEGORY_TAG_GROUPS below only decides
which tags are displayed under which category heading (a purely
editorial/display grouping); it does not define new ids. Every id used
here is cross-validated against the registry before the page is
written, so the two can never disagree.

Usage:
    python3 generate_categories_doc.py
"""

import html
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
REGISTRY_PATH = BASE_DIR / "data" / "code-categories-and-tags.json"
OUTPUT_PATH = BASE_DIR / "docs" / "gila-categories-and-tags.html"

# Editorial grouping only — which approved tag ids are shown under each
# approved category heading on the reference page. A tag may legitimately
# appear under more than one category here (the topic is genuinely
# relevant to both); that repetition is a display choice and has no
# effect on the canonical registry, which stores each id exactly once.
CATEGORY_TAG_GROUPS = [
    ("gynecological-exams", ["pelvic-exam", "patient-comfort", "examination-position",
        "speculum-exam", "bimanual-exam", "cervix-visualization", "exam-preparation",
        "exam-during-period", "appointment-planning"]),
    ("menstruation", ["heavy-bleeding", "painful-periods", "irregular-periods",
        "missed-period", "spotting", "period-delay", "period-length", "menstrual-cycle"]),
    ("contraception", ["birth-control-pills", "continuous-pill-use", "iud",
        "emergency-contraception", "contraceptive-implant", "contraceptive-ring",
        "contraceptive-patch"]),
    ("fertility", ["ovulation", "trying-to-conceive", "fertility-evaluation",
        "fertile-window", "amh", "ivf", "embryo-transfer", "menstruation"]),
    ("pregnancy", ["pregnancy-test", "early-pregnancy", "pregnancy-symptoms",
        "nutrition-in-pregnancy", "exercise-in-pregnancy", "travel-in-pregnancy",
        "vaccination-in-pregnancy"]),
    ("pregnancy-loss", ["miscarriage", "recurrent-miscarriage", "missed-miscarriage",
        "medical-management", "surgical-management", "recovery-after-miscarriage"]),
    ("postpartum", ["breastfeeding", "postpartum-recovery", "baby-blues",
        "postpartum-bleeding", "pelvic-floor", "postpartum-checkup"]),
    ("menopause", ["hot-flashes", "night-sweats", "sleep", "mood", "weight", "bone-health"]),
    ("hormone-replacement-therapy", ["hrt-benefits", "hrt-risks", "breast-cancer-risk",
        "hrt-types", "estrogen", "progesterone", "hrt-myths"]),
    ("sexual-health", ["pain-during-sex", "low-libido", "sexual-function", "lubricants", "intimacy"]),
    ("vulva-and-vagina", ["vaginal-discharge", "itching", "yeast-infection",
        "bacterial-vaginosis", "vaginal-dryness"]),
    ("cervix", ["pap-smear", "colposcopy", "cervical-polyp", "cervicitis"]),
    ("uterus", ["endometrial-polyp", "adenomyosis", "abnormal-bleeding", "endometrial-thickness"]),
    ("ovaries", ["ovarian-cyst", "ovarian-torsion", "ovarian-reserve", "ovulation-pain"]),
    ("pelvic-pain", ["chronic-pelvic-pain", "acute-pelvic-pain", "pelvic-infection", "diagnosis"]),
    ("endometriosis-and-adenomyosis", ["endometriosis", "adenomyosis", "diagnosis",
        "treatment", "fertility-impact"]),
    ("pcos", ["pcos-diagnosis", "irregular-periods", "acne", "hirsutism",
        "weight-management", "fertility"]),
    ("fibroids", ["fibroids", "heavy-bleeding", "fibroid-treatment", "embolization", "myomectomy"]),
    ("hpv", ["hpv-vaccine", "hpv-testing", "hpv-transmission", "hpv-clearance", "high-risk-hpv"]),
    ("cervical-cancer-prevention", ["screening", "pap-smear", "hpv-testing", "vaccination"]),
    ("breast-health", ["breast-pain", "breast-lump", "breast-self-awareness",
        "mammography", "breast-ultrasound"]),
    ("gynecologic-cancers", ["ovarian-cancer", "endometrial-cancer", "cervical-cancer", "warning-signs"]),
    ("urogynaecology", ["urinary-incontinence", "pelvic-organ-prolapse", "overactive-bladder", "pelvic-floor"]),
    ("adolescent-gynaecology", ["first-period", "puberty", "teen-contraception", "confidentiality"]),
    ("sexual-development", ["puberty", "breast-development", "menarche", "normal-development"]),
    ("sexually-transmitted-infections", ["chlamydia", "gonorrhea", "herpes", "syphilis", "hiv"]),
    ("preventive-medicine", ["screening", "vaccination", "healthy-lifestyle", "routine-checkup"]),
    ("common-myths", ["myths", "misconceptions", "social-media", "evidence-based-medicine"]),
    ("medical-procedures", ["hysteroscopy", "endometrial-biopsy", "ultrasound", "office-procedures"]),
    ("general-womens-health", ["healthy-lifestyle", "nutrition", "exercise", "mental-health"]),
]

# Reserved for the internal template Node (nodes/template-node.json) only.
# Never use this category/tag on a real content Node.
RESERVED_CATEGORY_GROUPS = [
    ("template-node", ["template-node"]),
]


def load_registry() -> dict:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {"categories": data["categories"], "tags": data["tags"]}


def validate_groups(registry: dict) -> None:
    """
    Fails loudly if CATEGORY_TAG_GROUPS references any id that isn't in
    the registry, or omits/duplicates a registry category — this is what
    guarantees the generated page can never disagree with the canonical
    JSON.
    """
    category_ids = set(registry["categories"])
    tag_ids = set(registry["tags"])
    errors = []

    all_groups = CATEGORY_TAG_GROUPS + RESERVED_CATEGORY_GROUPS
    grouped_categories = [c for c, _ in all_groups]
    if len(grouped_categories) != len(set(grouped_categories)):
        errors.append("CATEGORY_TAG_GROUPS/RESERVED_CATEGORY_GROUPS lists the same category more than once")
    missing = category_ids - set(grouped_categories)
    extra = set(grouped_categories) - category_ids
    if missing:
        errors.append(f"Registry categories missing from the grouping: {sorted(missing)}")
    if extra:
        errors.append(f"Grouping references unknown category ids: {sorted(extra)}")

    for category_id, group_tags in all_groups:
        for tag_id in group_tags:
            if tag_id not in tag_ids:
                errors.append(f"Category '{category_id}' references unknown tag id '{tag_id}'")

    if errors:
        raise SystemExit("FAILED — category/tag grouping disagrees with the registry:\n" +
                          "\n".join(f"  - {e}" for e in errors))


def render_category_section(category_id: str, group_tags: list, reserved: bool = False) -> str:
    cat_esc = html.escape(category_id, quote=True)
    tag_chips = "\n".join(
        f'        <li class="tag-chip"><code>{html.escape(t, quote=True)}</code></li>'
        for t in group_tags
    )
    extra_class = " reserved" if reserved else ""
    warning = (
        '\n    <p class="reserved-warning">Internal category (see "internalCategoryIds" in the registry) — reserved for technical/editorial Nodes only. Never use on a real public medical content Node. No Hebrew Topic label is required or shown for internal categories.</p>'
        if reserved else ""
    )
    return (
        f'  <section class="category-block{extra_class}" data-search="{cat_esc} {" ".join(html.escape(t) for t in group_tags)}">\n'
        f'    <h2><code>{cat_esc}</code></h2>{warning}\n'
        f'    <ul class="tag-list">\n{tag_chips}\n    </ul>\n'
        '  </section>'
    )


def render_html(registry: dict) -> str:
    sections = [render_category_section(c, t) for c, t in CATEGORY_TAG_GROUPS]
    sections += [render_category_section(c, t, reserved=True) for c, t in RESERVED_CATEGORY_GROUPS]
    sections_html = "\n\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Categories and Tags Registry</title>
<style>
  :root {{
    --ink: #20302c;
    --paper: #f6f3ec;
    --paper-raised: #ffffff;
    --teal: #1f4d46;
    --line: rgba(32,48,44,0.14);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 24px 16px 64px;
    background: var(--paper);
    color: var(--ink);
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    max-width: 860px;
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
  .intro ul {{ margin: 8px 0 0; padding-inline-start: 20px; }}
  .intro code {{ background: rgba(31,77,70,0.08); padding: 1px 5px; border-radius: 4px; }}
  #searchBox {{
    display: block;
    width: 100%;
    padding: 10px 12px;
    font-size: 14px;
    border: 1px solid var(--line);
    border-radius: 8px;
    margin-bottom: 20px;
    background: var(--paper-raised);
    color: var(--ink);
  }}
  .category-block {{
    background: var(--paper-raised);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 12px;
  }}
  .category-block h2 {{ font-size: 15px; margin: 0 0 10px; }}
  .category-block h2 code {{ font-size: 15px; }}
  .category-block.reserved {{ border-color: #c65f48; background: rgba(198,95,72,0.06); }}
  .reserved-warning {{ color: #c65f48; font-size: 12.5px; font-weight: 600; margin: -6px 0 10px; }}
  .tag-list {{
    list-style: none;
    margin: 0; padding: 0;
    display: flex; flex-wrap: wrap;
    gap: 6px;
  }}
  .tag-chip code {{
    display: inline-block;
    background: rgba(31,77,70,0.08);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 13px;
    cursor: pointer;
  }}
  .tag-chip code:hover {{ background: rgba(31,77,70,0.16); }}
  .tag-chip code.copied {{ background: var(--teal); color: #fff; }}
  code {{ font-family: ui-monospace, Consolas, monospace; }}
  .category-block.hidden {{ display: none; }}
</style>
</head>
<body>

<h1>Categories and Tags Registry</h1>

<div class="intro">
  <p>This is a human-readable reference for the approved category and tag IDs. It is generated directly from <code>data/code-categories-and-tags.json</code>, which remains the only canonical source of truth — this page cannot disagree with it.</p>
  <ul>
    <li>IDs are controlled — only IDs already in the registry may be used.</li>
    <li>IDs must be copied exactly as written (click an ID below to copy it).</li>
    <li>New IDs require explicit approval before being added to the registry.</li>
  </ul>
</div>

<input id="searchBox" type="text" placeholder="Search categories or tags…" autocomplete="off">

{sections_html}

<script>
  document.getElementById('searchBox').addEventListener('input', function(e){{
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll('.category-block').forEach(function(block){{
      const haystack = (block.dataset.search || '').toLowerCase();
      block.classList.toggle('hidden', q.length > 0 && !haystack.includes(q));
    }});
  }});

  document.querySelectorAll('.tag-chip code, h2 code').forEach(function(el){{
    el.addEventListener('click', function(){{
      const text = el.textContent;
      const done = function(){{
        el.classList.add('copied');
        setTimeout(function(){{ el.classList.remove('copied'); }}, 500);
      }};
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(done).catch(function(){{}});
      }}
    }});
  }});
</script>

</body>
</html>
"""


def main():
    registry = load_registry()
    validate_groups(registry)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_html(registry), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Categories: {len(registry['categories'])}  Tags: {len(registry['tags'])}")


if __name__ == "__main__":
    main()
