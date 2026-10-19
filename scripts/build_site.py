#!/usr/bin/env python3
"""Build the Persline static store from products/<slug>/product.json + description.md.

    python3 scripts/build_site.py            # full build (fast: ~1-2 s per 1,000 products)
    python3 scripts/build_site.py --root DIR # build another checkout (used for load tests)

Outputs (all committed, served as-is by GitHub Pages, no Jekyll):
  index.html                     home: hero, featured, categories, newest
  p/<slug>/index.html            product pages (URL scheme is stable)
  c/<cat>/index.html, c/<cat>/page/<n>/index.html   paginated category pages
  search/index.html              client-side search, filters (category, type, price) and sort
  data/catalog.json              compact catalog used by search (all products)
  data/c/<cat>.json              per-category chunks used by category-page filtering/sorting
  sitemap.xml, robots.txt, 404.html
"""
import argparse, html, json, math, os, re, shutil, sys, time
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = os.environ.get("STORE_URL", "https://shop.novif.app/")
BRAND = "Persline"
LEGAL = "Persline Templates"
CONTACT = "shop@novif.app"
FOOTER_LINE = "Free during launch. Personal and commercial use per included license; no resale."
PER_PAGE = 24
NEWEST = 8
INCLUDED_RE = re.compile(r"what you get|what'?s included|included", re.I)
CATEGORIES = [  # known categories, in nav order; unknown slugs get an auto title
    {"slug": "spreadsheet-templates", "name": "Spreadsheet Templates", "short": "Templates",
     "blurb": "Excel & Google Sheets templates for business, money and life admin. No macros."},
    {"slug": "dev-tools", "name": "Dev Tools", "short": "Dev Tools",
     "blurb": "Small, dependency-free tools and boilerplates that save developers hours."},
    {"slug": "notion-templates", "name": "Notion Templates", "short": "Notion",
     "blurb": "Import packs for Notion: linked databases, formulas and pages you build in your own workspace."},
    {"slug": "printables", "name": "Printables", "short": "Printables",
     "blurb": "Print-ready PDF planners and checklists in A4 and US Letter."},
    {"slug": "physical-products", "name": "Physical Products", "short": "Physical",
     "blurb": "Hand-picked physical goods. Coming soon: ask to be notified."},
]
# ---------------------------------------------------------------- markdown (tiny, dependency-free)
def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', s)
    return s

def md_to_html(md, shift=1):
    """Render a small markdown subset. Headings are shifted down by `shift` levels."""
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip() or re.match(r"^\s*!\[.*\]\(.*\)\s*$", line):
            i += 1; continue
        if line.lstrip().startswith("```"):
            i += 1; code = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code.append(lines[i]); i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>"); continue
        if re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", line):
            i += 1; continue
        if line.startswith("    ") and (not out or not out[-1].startswith("<ul")):
            code = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                code.append(lines[i][4:]); i += 1
            out.append("<pre><code>" + html.escape("\n".join(code).rstrip(), quote=False) + "</code></pre>"); continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            lvl = min(6, len(m.group(1)) + shift)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); i += 1; continue
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            t = ['<div class="table-wrap"><table>']
            for n, r in enumerate(rows):
                tag = "th" if n == 0 else "td"
                t.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in r) + "</tr>")
            out.append("".join(t) + "</table></div>"); continue
        lm = re.match(r"^\s*([-*]|\d+[.)])\s+", line)
        if lm:
            ordered = lm.group(1)[0].isdigit()
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+[.)])\s+", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+[.)])\s+", "", lines[i].rstrip())); i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>"); continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6}\s|\s*([-*]|\d+[.)])\s|\s*\||\s*```)", lines[i]):
            para.append(lines[i].strip()); i += 1
        out.append("<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(out)

def split_sections(md):
    """Return (intro, [(heading, body)]) for level-2 sections; drops a leading H1."""
    md = re.sub(r"^\s*#\s+.*\n", "", md, count=1)
    parts = re.split(r"^##\s+(.*)$", md, flags=re.M)
    intro, secs = parts[0], []
    for k in range(1, len(parts), 2):
        secs.append((parts[k].strip(), parts[k + 1]))
    return intro, secs

# ---------------------------------------------------------------- helpers
esc = lambda s: html.escape(str(s or ""), quote=True)
plain = lambda s: re.sub(r"[`*_]", "", str(s or ""))

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")

def money(x):
    return f"${x:,.2f}" if x is not None else ""

def human_size(n):
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, round(n / 1024))} KB"

def cat_info(slug):
    for c in CATEGORIES:
        if c["slug"] == slug:
            return c
    return {"slug": slug, "name": slug.replace("-", " ").title(), "short": slug.replace("-", " ").title(), "blurb": ""}

def is_physical(p):
    return p.get("type") == "physical"

def default_category(p):
    if is_physical(p): return "physical-products"
    if p.get("price_note") and "developer" in p.get("price_note", ""): return "dev-tools"
    return "spreadsheet-templates"

# ---------------------------------------------------------------- layout
ICON_SEARCH = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M10 2a8 8 0 0 1 6.32 12.9l5.39 5.4-1.41 1.4-5.4-5.38A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/></svg>'

def nav_cats(cats_present):
    return [c for c in CATEGORIES if c["slug"] in cats_present] + \
           [cat_info(s) for s in sorted(cats_present) if s not in {c["slug"] for c in CATEGORIES}]

def layout(ctx, title, desc, body, pre, canonical, og_image=None, og_type="website", extra_head="", scripts=""):
    nav = "".join(f'<a href="{pre}c/{c["slug"]}/">{esc(c["short"])}</a>' for c in ctx["navcats"])
    og_img = f'<meta property="og:image" content="{SITE_URL}{og_image}"><meta name="twitter:card" content="summary_large_image">' if og_image else '<meta name="twitter:card" content="summary">'
    foot_cats = "".join(f'<li><a href="{pre}c/{c["slug"]}/">{esc(c["name"])}</a></li>' for c in ctx["navcats"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc[:300])}">
<link rel="canonical" href="{SITE_URL}{canonical}">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc[:300])}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{SITE_URL}{canonical}">
{og_img}
<meta name="theme-color" content="#1f6f5c">
<link rel="icon" href="{pre}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{pre}assets/style.css?v={ctx["v"]}">
{extra_head}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
 <div class="wrap hdr">
  <a class="brand" href="{pre}"><span class="logo" aria-hidden="true">P</span>{BRAND}</a>
  <form class="hsearch" action="{pre}search/" method="get" role="search">
   <input type="search" name="q" placeholder="Search products" aria-label="Search products" autocomplete="off">
   <button type="submit" aria-label="Search">{ICON_SEARCH}</button>
  </form>
 </div>
 <nav class="catnav" aria-label="Categories"><div class="wrap"><a href="{pre}search/">All products</a>{nav}</div></nav>
</header>
<main id="main">
{body}
</main>
<footer class="site-footer">
 <div class="wrap fgrid">
  <div><a class="brand" href="{pre}"><span class="logo" aria-hidden="true">P</span>{BRAND}</a>
   <p class="muted">Practical templates, tools and goods by {LEGAL}.</p></div>
  <div><h4>Shop</h4><ul><li><a href="{pre}search/">All products</a></li>{foot_cats}</ul></div>
  <div><h4>Help</h4><ul><li><a href="mailto:{CONTACT}">{CONTACT}</a></li><li><a href="{pre}sitemap.xml">Sitemap</a></li></ul></div>
 </div>
 <div class="wrap fbottom">
  <p class="footer-line">{FOOTER_LINE}</p>
  <p class="muted">&copy; {date.today().year} {LEGAL}. Questions or support: <a href="mailto:{CONTACT}">{CONTACT}</a></p>
 </div>
</footer>
{scripts}
</body>
</html>
"""

def price_block(p, big=False):
    cls = "price big" if big else "price"
    if is_physical(p):
        ca = f' <s>{money(p["compare_at_usd"])}</s>' if p.get("compare_at_usd") else ""
        return f'<span class="{cls}"><b>{money(p["price_usd"])}</b>{ca}</span>'
    return f'<span class="{cls}"><s>{money(p["price_usd"])}</s> <b class="free">Free</b><span class="launch"> during launch</span></span>'

def badge(p):
    return '<span class="badge soon">Coming soon</span>' if is_physical(p) else '<span class="badge free">Free</span>'

def card(p, pre, eager=False):
    im = p["images"][0] if p.get("images") else None
    img = (f'<img src="{pre}{im.get("card", im["full"])}" alt="" width="{im.get("card_w", im["w"])}" height="{im.get("card_h", im["h"])}"'
           f'{"" if eager else " loading=\"lazy\""} decoding="async">') if im else '<div class="noimg"></div>'
    return (f'<article class="card"><a class="card-link" href="{pre}p/{p["slug"]}/">'
            f'<div class="card-img">{img}{badge(p)}</div>'
            f'<div class="card-body"><p class="card-cat">{esc(cat_info(p["category"])["name"])}</p>'
            f'<h3>{esc(p["name"])}</h3><p class="card-sum">{esc(plain(p["summary"]))}</p>'
            f'<div class="card-foot">{price_block(p)}</div></div></a></article>')

def pager(cur, total, base_pre, cat_slug):
    if total <= 1: return ""
    def href(n):
        return f'{base_pre}c/{cat_slug}/' if n == 1 else f'{base_pre}c/{cat_slug}/page/{n}/'
    items = []
    if cur > 1: items.append(f'<a rel="prev" href="{href(cur-1)}">&larr; Prev</a>')
    shown = sorted({1, total, cur - 1, cur, cur + 1} & set(range(1, total + 1)))
    last = 0
    for n in shown:
        if n - last > 1: items.append('<span class="gap">…</span>')
        items.append(f'<span class="cur" aria-current="page">{n}</span>' if n == cur else f'<a href="{href(n)}">{n}</a>')
        last = n
    if cur < total: items.append(f'<a rel="next" href="{href(cur+1)}">Next &rarr;</a>')
    return f'<nav class="pager" aria-label="Pages">{"".join(items)}</nav>'

def toolbar(cat_slug=None, with_cat=False, cats=()):
    cat_sel = ""
    if with_cat:
        opts = "".join(f'<option value="{c["slug"]}">{esc(c["name"])}</option>' for c in cats)
        cat_sel = f'<label>Category<select name="cat"><option value="">All</option>{opts}</select></label>'
    return f"""<form class="toolbar" id="filters" data-cat="{cat_slug or ''}" onsubmit="return false">
 {'<label class="grow">Search<input type="search" name="q" placeholder="Search products…"></label>' if with_cat else ''}
 {cat_sel}
 <label>Type<select name="type"><option value="">All</option><option value="d">Digital</option><option value="p">Physical</option></select></label>
 <label>Min $<input type="number" name="min" min="0" step="1" inputmode="numeric" placeholder="0"></label>
 <label>Max $<input type="number" name="max" min="0" step="1" inputmode="numeric" placeholder="any"></label>
 <label>Sort<select name="sort"><option value="new">Newest</option><option value="pa">Price: low to high</option><option value="pd">Price: high to low</option><option value="az">Name A–Z</option></select></label>
</form>"""

# ---------------------------------------------------------------- pages
def specs_rows(p):
    rows = [("Category", cat_info(p["category"])["name"]), ("Type", "Physical product" if is_physical(p) else "Digital download")]
    if not is_physical(p):
        if p.get("version"): rows.append(("Version", p["version"]))
        if p.get("download"): rows.append(("Download", f'{p["download"]["filename"]} ({human_size(p["download"]["size_bytes"])})'))
        if p.get("compatibility"): rows.append(("Works with", "; ".join(p["compatibility"])))
    for k, v in (p.get("specs") or {}).items():
        rows.append((k, ", ".join(map(str, v)) if isinstance(v, list) else v))
    if is_physical(p):
        if p.get("shipping_estimate"): rows.append(("Shipping", p["shipping_estimate"]))
    if p.get("license_note") and not is_physical(p): rows.append(("License", p["license_note"]))
    if p.get("created"): rows.append(("Added", p["created"]))
    return "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)

def product_page(ctx, p, related):
    pre = "../../"
    imgs = p.get("images") or []
    main = imgs[0] if imgs else None
    gallery = ""
    if main:
        thumbs = "".join(
            f'<button type="button" class="thumb{" active" if n == 0 else ""}" data-full="{pre}{im["full"]}" data-w="{im["w"]}" data-h="{im["h"]}" aria-label="Show image {n+1}">'
            f'<img src="{pre}{im.get("thumb", im["full"])}" alt="" width="{im.get("thumb_w", 240)}" height="{im.get("thumb_h", 192)}" loading="lazy" decoding="async"></button>'
            for n, im in enumerate(imgs)) if len(imgs) > 1 else ""
        gallery = (f'<figure class="main-img"><img id="main-img" src="{pre}{main["full"]}" alt="{esc(p["name"])}" width="{main["w"]}" height="{main["h"]}" fetchpriority="high"></figure>'
                   f'<div class="thumbs">{thumbs}</div>')
    intro, secs = split_sections(p.get("description_md", ""))
    desc_md, incl_md = intro, ""
    for h, b in secs:
        if re.fullmatch(r"price|pricing", h, re.I): continue
        if INCLUDED_RE.search(h) and not incl_md: incl_md = b
        else: desc_md += f"\n## {h}\n{b}"
    if p.get("whats_included"):
        incl_md = "\n".join("- " + x for x in p["whats_included"])
    if is_physical(p):
        subj = quote(f'Notify me: {p["name"]}')
        body = quote(f'Hi, please let me know when "{p["name"]}" is available.\n\n{SITE_URL}p/{p["slug"]}/')
        cta = (f'<a class="btn btn-lg" href="mailto:{CONTACT}?subject={subj}&amp;body={body}">Coming soon: notify me</a>'
               f'<p class="small muted">No checkout yet. Email <a href="mailto:{CONTACT}">{CONTACT}</a> and we will tell you when it ships.</p>')
        cta2 = f'<a class="btn btn-block" href="mailto:{CONTACT}?subject={subj}&amp;body={body}">Notify me</a>'
    else:
        dl = p["download"]
        cta = (f'<a class="btn btn-lg" href="{dl["url"]}">Download free <small>(.zip, {human_size(dl["size_bytes"])})</small></a>'
               f'<p class="small muted">Instant download, no sign-up. Free during launch.</p>')
        cta2 = f'<a class="btn btn-block" href="{dl["url"]}">Download free</a>'
        for x in p.get("extra_downloads", []):
            cta += f'<p class="small"><a href="{x["url"]}">Also available: {esc(x["label"])} (.zip, {human_size(x["size_bytes"])})</a></p>'
    pnote = f'<p class="small muted pnote">{esc(p["price_note"])}</p>' if p.get("price_note") else ""
    if is_physical(p):
        ship = f' · Shipping: {esc(p["shipping_estimate"])}' if p.get("shipping_estimate") else ""
        pnote += f'<p class="small muted pnote">Price excl. VAT and shipping; shipping estimate shown.{ship}</p>'
    disclaimer = f'<p class="disclaimer">{esc(p["disclaimer"])}</p>' if p.get("disclaimer") else ""
    lic = p.get("license_note", "")
    lic_html = "" if is_physical(p) else f'<p class="small"><strong>License:</strong> {esc(lic or "See the license in the download.")}{"" if re.search(r"resell|resale", lic, re.I) else " No resale or redistribution."}</p>'
    tags = "".join(f'<li><a href="{pre}search/?q={quote(t)}">{esc(t)}</a></li>' for t in p.get("tags", [])[:12])
    rel = "".join(card(r, pre) for r in related)
    cat = cat_info(p["category"])
    ld = {"@context": "https://schema.org", "@type": "Product", "name": p["name"], "description": plain(p["summary"]),
          "image": [SITE_URL + im["full"] for im in imgs[:3]], "category": cat["name"], "brand": {"@type": "Brand", "name": BRAND},
          "offers": {"@type": "Offer", "priceCurrency": "USD", "url": f'{SITE_URL}p/{p["slug"]}/',
                     "price": f'{p["price_usd"]:.2f}' if is_physical(p) else "0.00",
                     "availability": "https://schema.org/PreOrder" if is_physical(p) else "https://schema.org/InStock"}}
    body = f"""
<div class="wrap">
<nav class="crumbs" aria-label="Breadcrumb"><a href="{pre}">Home</a><span>/</span><a href="{pre}c/{cat["slug"]}/">{esc(cat["name"])}</a><span>/</span><span aria-current="page">{esc(p["name"])}</span></nav>
<section class="product">
  <div class="gallery">{gallery}</div>
  <div class="buy">
    <p class="card-cat">{esc(cat["name"])}</p>
    <h1>{esc(p["name"])}</h1>
    <p class="lead">{esc(plain(p["summary"]))}</p>
    <div class="pricebox">{price_block(p, big=True)}{pnote}</div>
    {cta}
    {lic_html}
    {disclaimer}
  </div>
</section>
<section class="details">
  <div class="desc">
    <h2>Description</h2>{md_to_html(desc_md, shift=1)}
  </div>
  <aside class="side">
    {('<div class="included"><h2>What&#39;s included</h2>' + md_to_html(incl_md, shift=1) + cta2 + '</div>') if incl_md.strip() else ''}
    <div class="specs"><h2>Specifications</h2><table>{specs_rows(p)}</table></div>
  </aside>
</section>
{'<ul class="tags" aria-label="Tags">' + tags + '</ul>' if tags else ''}
{'<section class="related"><h2 class="section-title">More in ' + esc(cat["name"]) + '</h2><div class="grid">' + rel + '</div></section>' if rel else ''}
</div>"""
    js = f'<script src="{pre}assets/product.js?v={ctx["v"]}" defer></script>'
    head = '<script type="application/ld+json">' + json.dumps(ld).replace("</", "<\\/") + '</script>'
    return layout(ctx, f'{p["name"]} | {BRAND}', plain(p["summary"]), body, pre, f'p/{p["slug"]}/',
                  og_image=main["full"] if main else None, og_type="product", extra_head=head, scripts=js)

def home_page(ctx, prods, bycat):
    pre = ""
    featured = [p for p in prods if p.get("featured")] or sorted(prods, key=lambda p: p.get("order", 100))[:1]
    f = featured[0] if featured else None
    feat = ""
    if f:
        im = f["images"][0]
        feat = f"""<section class="wrap featured"><a class="feat" href="p/{f["slug"]}/">
 <div class="feat-img"><img src="{im["full"]}" alt="" width="{im["w"]}" height="{im["h"]}" fetchpriority="high"></div>
 <div class="feat-body"><p class="eyebrow">Featured</p><h2>{esc(f["name"])}</h2><p>{esc(plain(f["summary"]))}</p>
 <div class="feat-foot">{price_block(f, big=True)}<span class="btn">View product</span></div></div></a></section>"""
    tiles = ""
    for c in CATEGORIES + [cat_info(s) for s in bycat if s not in {x["slug"] for x in CATEGORIES}]:
        n = len(bycat.get(c["slug"], []))
        label = f'{n} product{"s" if n != 1 else ""}' if n else "Coming soon"
        href = f'c/{c["slug"]}/' if n else f'mailto:{CONTACT}?subject={quote("Notify me: " + c["name"])}'
        tiles += f'<a class="tile tile-{c["slug"]}" href="{href}"><h3>{esc(c["name"])}</h3><p>{esc(c["blurb"])}</p><span class="count">{label} &rarr;</span></a>'
    newest = sorted(prods, key=lambda p: p.get("added", ""), reverse=True)[:NEWEST]
    total = len(prods)
    body = f"""
<section class="hero"><div class="wrap">
  <p class="eyebrow">{total} product{"s" if total != 1 else ""} · free during launch</p>
  <h1>Templates, tools and goods that save you hours.</h1>
  <p class="sub">Spreadsheet templates for Excel &amp; Google Sheets, small developer tools, and soon hand-picked physical products. Clear, tested, no sign-ups.</p>
  <form class="bigsearch" action="search/" method="get" role="search"><input type="search" name="q" placeholder="Search {total} products…" aria-label="Search products"><button class="btn" type="submit">Search</button></form>
</div></section>
{feat}
<section class="wrap"><h2 class="section-title">Shop by category</h2><div class="tiles">{tiles}</div></section>
<section class="wrap"><div class="section-head"><h2 class="section-title">Newest</h2><a href="search/?sort=new">View all &rarr;</a></div>
<div class="grid">{"".join(card(p, pre, eager=i < 4) for i, p in enumerate(newest)) or '<p class="empty">New products are on their way. Check back soon.</p>'}</div></section>
<section class="wrap why"><div><h3>Free during launch</h3><p>Every digital product is free to download while we launch. Prices shown are the regular price.</p></div>
<div><h3>Tested, no macros</h3><p>Templates work in Excel, Google Sheets and LibreOffice. Tools ship with tests and docs.</p></div>
<div><h3>Real support</h3><p>Questions? Email <a href="mailto:{CONTACT}">{CONTACT}</a> and a person will answer.</p></div></section>"""
    og = f["images"][0]["full"] if f else None
    return layout(ctx, f"{BRAND} | Templates, tools & goods", "Spreadsheet templates, developer tools and hand-picked goods by Persline. Free during launch.", body, pre, "", og_image=og)

def category_page(ctx, c, items, page_no, pages):
    pre = "../../" if page_no == 1 else "../../../../"
    canon = f'c/{c["slug"]}/' + ("" if page_no == 1 else f'page/{page_no}/')
    chunk = items[(page_no - 1) * PER_PAGE: page_no * PER_PAGE]
    grid = "".join(card(p, pre, eager=i < 4) for i, p in enumerate(chunk)) or '<p class="empty">Nothing here yet. <a href="mailto:' + CONTACT + '">Ask to be notified</a>.</p>'
    title = c["name"] + ("" if page_no == 1 else f" (page {page_no})")
    body = f"""
<div class="wrap">
<nav class="crumbs" aria-label="Breadcrumb"><a href="{pre}">Home</a><span>/</span><span aria-current="page">{esc(c["name"])}</span></nav>
<header class="cat-head"><h1>{esc(title)}</h1><p class="muted">{esc(c["blurb"])} <span class="count">{len(items)} product{"s" if len(items) != 1 else ""}</span></p></header>
{toolbar(c["slug"]) if len(items) > 1 else ''}
<p class="result-info" id="result-info" hidden></p>
<div class="grid" id="results" data-pre="{pre}">{grid}</div>
<div id="static-pager">{pager(page_no, pages, pre, c["slug"])}</div>
</div>"""
    js = f'<script src="{pre}assets/store.js?v={ctx["v"]}" defer></script>' if len(items) > 1 else ""
    head = ""
    if page_no > 1: head += f'<link rel="prev" href="{SITE_URL}c/{c["slug"]}/' + ("" if page_no == 2 else f'page/{page_no-1}/') + '">'
    if page_no < pages: head += f'<link rel="next" href="{SITE_URL}c/{c["slug"]}/page/{page_no+1}/">'
    return layout(ctx, f'{title} | {BRAND}', c["blurb"] or c["name"], body, pre, canon, extra_head=head, scripts=js,
                  og_image=items[0]["images"][0]["full"] if items and items[0].get("images") else None)

def search_page(ctx, cats):
    pre = "../"
    body = f"""
<div class="wrap">
<header class="cat-head"><h1>All products</h1><p class="muted">Search, filter and sort the whole catalog.</p></header>
{toolbar(None, with_cat=True, cats=cats)}
<p class="result-info" id="result-info">Loading…</p>
<div class="grid" id="results" data-pre="{pre}"></div>
<nav class="pager" id="more-wrap" hidden><button type="button" class="btn" id="more">Show more</button></nav>
<noscript><p>Search needs JavaScript. Browse by category instead: {" · ".join(f'<a href="{pre}c/{c["slug"]}/">{esc(c["name"])}</a>' for c in cats)}</p></noscript>
</div>"""
    js = f'<script src="{pre}assets/store.js?v={ctx["v"]}" defer></script>'
    return layout(ctx, f"All products | {BRAND}", "Search Persline's catalog of templates, tools and goods.", body, pre, "search/", scripts=js,
                  extra_head='<meta name="robots" content="noindex,follow">')

def not_found(ctx):
    body = f'<div class="wrap nf"><h1>Page not found</h1><p>That page does not exist (any more). Try the <a href="/">home page</a> or <a href="/search/">search</a>.</p></div>'
    return layout(ctx, f"Not found | {BRAND}", "Page not found", body, "/", "404.html")

# ---------------------------------------------------------------- data + build
def load_products(root):
    prods = []
    for f in (root / "products").glob("*/product.json"):
        p = json.loads(f.read_text(encoding="utf-8"))
        d = f.parent / "description.md"
        p["description_md"] = d.read_text(encoding="utf-8") if d.exists() else ""
        p.setdefault("type", "digital")
        p["category"] = slugify(p.get("category") or default_category(p))
        p.setdefault("added", p.get("created", ""))
        prods.append(p)
    prods.sort(key=lambda p: (p.get("order", 100), p.get("added", "")))
    return prods

def catalog_row(p):
    im = p["images"][0] if p.get("images") else {}
    r = {"s": p["slug"], "n": p["name"], "c": p["category"], "t": "p" if is_physical(p) else "d",
         "p": p["price_usd"], "u": plain(p["summary"])[:140], "g": " ".join(p.get("tags", []))[:200],
         "i": im.get("card", im.get("full", "")), "a": p.get("added", "")}
    if p.get("compare_at_usd"): r["x"] = p["compare_at_usd"]
    return r

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def build(root=ROOT, quiet=False):
    t0 = time.time()
    prods = load_products(root)
    bycat = {}
    for p in prods:
        bycat.setdefault(p["category"], []).append(p)
    ctx = {"navcats": nav_cats(set(bycat) | {"physical-products"}) , "v": str(int(t0))}
    # clean generated dirs (product pages are regenerated; stale slugs removed)
    for d in ("c", "data"):
        if (root / d).exists(): shutil.rmtree(root / d)
    keep = {p["slug"] for p in prods}
    if (root / "p").exists():
        for d in (root / "p").iterdir():
            if d.name not in keep: shutil.rmtree(d)
    for c_slug, items in bycat.items():
        items.sort(key=lambda p: p.get("added", ""), reverse=True)
    for p in prods:
        same = [x for x in bycat[p["category"]] if x["slug"] != p["slug"]][:4]
        write(root / "p" / p["slug"] / "index.html", product_page(ctx, p, same))
    for c in ctx["navcats"]:
        items = bycat.get(c["slug"], [])
        pages = max(1, math.ceil(len(items) / PER_PAGE))
        for n in range(1, pages + 1):
            path = root / "c" / c["slug"] / ("index.html" if n == 1 else f"page/{n}/index.html")
            write(path, category_page(ctx, c, items, n, pages))
        write(root / "data" / "c" / f'{c["slug"]}.json', json.dumps([catalog_row(p) for p in items], separators=(",", ":"), ensure_ascii=False))
    newest_first = sorted(prods, key=lambda p: p.get("added", ""), reverse=True)
    write(root / "data" / "catalog.json", json.dumps({"cats": [{"s": c["slug"], "n": c["name"]} for c in ctx["navcats"]],
                                                        "items": [catalog_row(p) for p in newest_first]}, separators=(",", ":"), ensure_ascii=False))
    write(root / "index.html", home_page(ctx, prods, bycat))
    write(root / "search" / "index.html", search_page(ctx, ctx["navcats"]))
    write(root / "404.html", not_found(ctx))
    urls = [("", "1.0")] + [(f'c/{c["slug"]}/', "0.8") for c in ctx["navcats"] if bycat.get(c["slug"])] + [(f'p/{p["slug"]}/', "0.6") for p in prods]
    today = date.today().isoformat()
    write(root / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
          "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{today}</lastmod><priority>{pr}</priority></url>\n" for u, pr in urls) + "</urlset>\n")
    write(root / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n")
    dt = time.time() - t0
    if not quiet:
        print(f"built {len(prods)} products, {len(ctx['navcats'])} categories in {dt:.2f}s")
    return dt

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args()
    build(Path(a.root))
