#!/usr/bin/env python3
"""Add (or update) a product on the Persline Templates storefront.

Two input formats are supported:

1. A web package folder (preferred; what the product-maker bots produce):
       python3 scripts/add_product.py /path/to/product/web [--images extra1.png ...] --release --push
   The folder must contain product.json (title/name/slug/version/price_usd/summary/
   tags/description_path/preview/thumbnail/downloads[...]) and description.md.
   The first download with type "zip" (or ending in .zip) becomes the Release asset.

2. A legacy listing file (the gumroad.md format):
       python3 scripts/add_product.py --listing gumroad.md --zip product.zip \
           --images img1.png img2.png ... [--slug my-product] [--version 1.0] --release --push

Other modes:
       python3 scripts/add_product.py --rebuild          # regenerate all HTML from products/*/product.json

What it does:
  * normalises product data into products/<slug>/product.json + description.md
  * converts images to WebP (gallery <=1600px wide, card <=800px) under assets/img/<slug>/
  * regenerates index.html and p/<slug>/index.html (plain static HTML, no build step)
  * --push   : git add/commit/push to main
  * --release: creates GitHub Release "<slug>-v<version>" with the zip (or re-uploads with --clobber)
The Download button always points at
  https://github.com/<REPO>/releases/download/<slug>-v<version>/<zip-name>
Only needs Python 3.9+, Pillow, git and an authenticated `gh` CLI.
"""
import argparse, html, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ.get("STORE_REPO", "Dr1nnas/digital-products")
SITE_URL = os.environ.get("STORE_URL", "https://dr1nnas.github.io/digital-products/")
BRAND = "Persline Templates"
CONTACT = "shop@novif.app"
FOOTER_LINE = "Free during launch. Personal and commercial use per included license; no resale."
INCLUDED_RE = re.compile(r"what you get|what'?s included|included", re.I)

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

# ---------------------------------------------------------------- input parsing
def parse_gumroad(path):
    text = Path(path).read_text(encoding="utf-8")
    secs = {}
    for name, body in re.findall(r"^##\s+(.+?)\n(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S):
        secs[name.strip().lower()] = body.strip()
    def sec(prefix):
        for k, v in secs.items():
            if k.startswith(prefix):
                return v
        return ""
    name = sec("product name").splitlines()[0].strip()
    price = float(re.search(r"\$([\d.]+)", sec("price")).group(1))
    summary = sec("summary").splitlines()[0].strip()
    slug = sec("url slug").splitlines()[0].strip() if sec("url slug") else None
    # Convert plain-text description: a line followed directly by a list item becomes a heading.
    raw = [l.rstrip() for l in sec("description").splitlines()]
    raw = [l for l in raw if "gumroad" not in l.lower()]
    md = []
    for n, l in enumerate(raw):
        nxt = raw[n + 1] if n + 1 < len(raw) else ""
        if l and not re.match(r"^\s*([-*]|\d+[.)])\s", l) and re.match(r"^\s*([-*]|\d+[.)])\s", nxt):
            md += ["", "## " + l]
        else:
            md.append(l)
    desc = "\n".join(md).strip()
    included = [re.sub(r"^\s*[-*]\s+", "", l) for l in sec("what you get").splitlines() if l.strip().startswith(("-", "*"))]
    if included:
        desc += "\n\n## What you get\n" + "\n".join("- " + x for x in included)
    tags = [t.strip() for t in sec("tags").split(",") if t.strip()]
    return dict(name=name, slug=slug, price_usd=price, summary=summary, description_md=desc, tags=tags)

def load_web_package(d):
    d = Path(d)
    pj = json.loads((d / "product.json").read_text(encoding="utf-8"))
    desc_path = d / pj.get("description_path", "description.md")
    desc = desc_path.read_text(encoding="utf-8") if desc_path.exists() else ""
    summary = pj.get("summary") or ((d / "summary.txt").read_text().strip() if (d / "summary.txt").exists() else "")
    zips = [x for x in pj.get("downloads", []) if x.get("type") == "zip" or x["path"].endswith(".zip")]
    if not zips:
        sys.exit("product.json has no zip download")
    images = []
    for key in ("gallery", "images"):
        images += [str(d / p) for p in pj.get(key, [])]
    if pj.get("preview"):
        images.insert(0, str(d / pj["preview"]))
    return dict(name=pj.get("name") or pj["title"], slug=pj["slug"], version=str(pj.get("version", "1.0")),
                price_usd=float(pj["price_usd"]), summary=summary, description_md=desc,
                tags=pj.get("tags", []), compatibility=pj.get("compatibility", []),
                license_note=pj.get("license", ""), disclaimer=pj.get("disclaimer", ""),
                created=pj.get("created", ""), zip=str(d / zips[0]["path"]), images=images)

def load_code_folder(d):
    """Code-product folder: listing.md + description.md + preview.png + <name>-<version>.zip"""
    d = Path(d)
    listing = (d / "listing.md").read_text(encoding="utf-8")
    secs = {k.strip().lower(): v.strip() for k, v in
            re.findall(r"^##\s+(.+?)\n(.*?)(?=^##\s|\Z)", listing, flags=re.M | re.S)}
    def sec(prefix):
        return next((v for k, v in secs.items() if k.startswith(prefix)), "")
    h1 = re.search(r"^#\s+(.+)$", listing, flags=re.M).group(1).strip()
    name = h1.split(":")[0].strip()
    pm = re.search(r"price:?\**\s*\$([\d.]+)\s*(?:USD)?\s*\(?([^).\n]*)", listing, flags=re.I)
    zips = sorted(d.glob("*.zip"))
    if not zips: sys.exit(f"no zip in {d}")
    vm = re.search(r"-v?(\d+(?:\.\d+)+)\.zip$", zips[0].name)
    summary = " ".join(sec("short description").split())
    lic = " ".join(sec("license summary").replace("(for the listing page)", "").split())
    desc = (d / "description.md").read_text(encoding="utf-8")
    images = [str(x) for x in [d / "preview.png"] if x.exists()] + [str(x) for x in sorted(d.glob("screenshot*.png"))]
    return dict(name=name, slug=re.sub(r"^\d{4}-\d{2}-\d{2}-", "", d.name), version=vm.group(1) if vm else "1.0",
                price_usd=float(pm.group(1)), price_note=(pm.group(2).strip().rstrip(";,") if pm else ""),
                summary=summary, description_md=desc,
                tags=[t.strip() for t in re.split(r"[,\n]", sec("tags")) if t.strip()],
                compatibility=[], license_note=lic, disclaimer="", created="", zip=str(zips[0]), images=images)

def load_folder(d):
    d = Path(d)
    if (d / "product.json").exists():
        return load_web_package(d)
    if (d / "web" / "product.json").exists():
        return load_web_package(d / "web")
    if (d / "listing.md").exists() and (d / "description.md").exists():
        return load_code_folder(d)
    sys.exit(f"{d}: not a recognised product folder (need product.json, or listing.md + description.md + zip)")

# ---------------------------------------------------------------- images
def pad_to_ratio(im, ratio):
    """Pad (not crop) to width/height == ratio using the top-left pixel colour."""
    from PIL import Image
    w, h = im.size
    nw, nh = (w, round(w / ratio)) if w / h > ratio else (round(h * ratio), h)
    canvas = Image.new(im.mode, (nw, nh), im.getpixel((0, 0)))
    canvas.paste(im, ((nw - w) // 2, (nh - h) // 2))
    return canvas

def optimise_images(slug, sources, name=""):
    from PIL import Image
    out_dir = ROOT / "assets" / "img" / slug
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    seen, result = set(), []
    for src in sources:
        src = Path(src)
        if src.resolve() in seen:
            continue
        seen.add(src.resolve())
        im = Image.open(src)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        stem = re.sub(r"^[0-9]+-", "", re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-")) or "image"
        label_txt = stem.replace("-", " ").capitalize()
        entry = {"alt": f"{name}: {label_txt}" if name else label_txt}
        n = len(result) + 1
        for label, width, q in (("full", 1600, 80), ("card", 800, 78), ("thumb", 240, 72)):
            if label == "card" and result:
                continue  # card image only for the first (hero) image
            src_im = im
            if label == "card" and abs(im.width / im.height - 1.25) > 0.02:
                src_im = pad_to_ratio(im, 1.25)
            w = min(width, src_im.width)
            h = round(src_im.height * w / src_im.width)
            fname = f"{n:02d}-{stem}{'' if label == 'full' else '-' + label}.webp"
            src_im.resize((w, h), Image.LANCZOS).save(out_dir / fname, "WEBP", quality=q, method=6)
            entry[label] = f"assets/img/{slug}/{fname}"
            if label == "full":
                entry["w"], entry["h"] = w, h
            else:
                entry[label + "_w"], entry[label + "_h"] = w, h
        result.append(entry)
    return result

# ---------------------------------------------------------------- HTML
def money(x):
    return f"${x:,.2f}"

def human_size(n):
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{n / 1024:.0f} KB"

def page(title, desc, body, depth, og_image=None, canonical=""):
    pre = "../" * depth
    og = f'<meta property="og:image" content="{SITE_URL}{og_image}">' if og_image else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE_URL}{canonical}">
{og}
<link rel="canonical" href="{SITE_URL}{canonical}">
<link rel="icon" href="{pre}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{pre}assets/style.css">
</head>
<body>
<header class="site-header"><div class="wrap">
  <a class="brand" href="{pre}"><span class="logo" aria-hidden="true">P</span>{BRAND}</a>
  <nav><a href="{pre}#products">Products</a><a href="mailto:{CONTACT}">Contact</a></nav>
</div></header>
<main>
{body}
</main>
<footer class="site-footer"><div class="wrap">
  <p class="footer-line">{FOOTER_LINE}</p>
  <p>Questions or support: <a href="mailto:{CONTACT}">{CONTACT}</a></p>
  <p class="muted">&copy; 2026 {BRAND}</p>
</div></footer>
</body>
</html>
"""

def price_html(p):
    return (f'<span class="price"><s>{money(p["price_usd"])}</s> <span class="free">— free during launch</span></span>')

def build_product_page(p):
    imgs = p["images"]
    main = imgs[0]
    thumbs = "".join(
        f'<a class="thumb" href="../../{im["full"]}" data-full="../../{im["full"]}" data-alt="{html.escape(im["alt"])}">'
        f'<img src="../../{im.get("thumb", im["full"])}" alt="{html.escape(im["alt"])}" width="{im.get("thumb_w", im["w"])}" height="{im.get("thumb_h", im["h"])}" loading="lazy"></a>'
        for im in imgs) if len(imgs) > 1 else ""
    intro, secs = split_sections(p["description_md"])
    desc_md, incl_md = intro, ""
    for h, b in secs:
        if re.fullmatch(r"price|pricing", h, re.I):
            continue
        if INCLUDED_RE.search(h) and not incl_md:
            incl_md = b
        else:
            desc_md += f"\n## {h}\n{b}"
    dl = p["download"]
    compat = "".join(f"<li>{html.escape(c)}</li>" for c in p.get("compatibility", []))
    tags = "".join(f"<li>{html.escape(t)}</li>" for t in p.get("tags", [])[:10])
    disclaimer = f'<p class="disclaimer">{html.escape(p["disclaimer"])}</p>' if p.get("disclaimer") else ""
    license_note = html.escape(p.get("license_note") or "See the license included in the download.")
    body = f"""
<div class="wrap">
<nav class="crumbs"><a href="../../">Home</a> <span>/</span> {html.escape(p["name"])}</nav>
<section class="product">
  <div class="gallery">
    <figure class="main-img"><img id="main-img" src="../../{main["full"]}" alt="{html.escape(main["alt"])}" width="{main["w"]}" height="{main["h"]}" fetchpriority="high"></figure>
    <div class="thumbs">{thumbs}</div>
  </div>
  <div class="buy">
    <h1>{html.escape(p["name"])}</h1>
    <p class="lead">{html.escape(p["summary"].replace("`", ""))}</p>
    <p>{price_html(p)}{'<br><span class="small muted">' + html.escape(p["price_note"]) + '</span>' if p.get("price_note") else ''}</p>
    <a class="btn" href="{dl["url"]}" download>Download free <small>(.zip, {human_size(dl["size_bytes"])})</small></a>
    <p class="small muted">Version {html.escape(p["version"])} · Instant download, nothing is shipped.</p>
    {'<h3>Works with</h3><ul class="compat">' + compat + '</ul>' if compat else ''}
    <p class="small"><strong>License:</strong> {license_note}{'' if re.search(r"resell|resale", license_note, re.I) else ' No resale or redistribution.'}</p>
    {disclaimer}
  </div>
</section>
<section class="details">
  <div class="desc"><h2>About this product</h2>{md_to_html(desc_md, shift=1)}</div>
  {'<aside class="included"><h2>What&#39;s included</h2>' + md_to_html(incl_md, shift=1) + '<a class="btn btn-block" href="' + dl["url"] + '" download>Download free</a></aside>' if incl_md else ''}
</section>
{'<ul class="tags" aria-label="Tags">' + tags + '</ul>' if tags else ''}
</div>
<script>
document.querySelectorAll('.thumb').forEach(function(a){{a.addEventListener('click',function(e){{e.preventDefault();var m=document.getElementById('main-img');m.src=a.dataset.full;m.alt=a.dataset.alt;document.querySelectorAll('.thumb').forEach(function(t){{t.classList.remove('active')}});a.classList.add('active');}});}});
var f=document.querySelector('.thumb');if(f)f.classList.add('active');
</script>"""
    title = f'{p["name"]} | {BRAND}'
    return page(title, p["summary"].replace("`", ""), body, 2, og_image=main["full"], canonical=f'p/{p["slug"]}/')

def build_index(products):
    cards = []
    for p in products:
        im = p["images"][0]
        cards.append(f"""
<article class="card">
  <a href="p/{p["slug"]}/" class="card-img"><img src="{im["card"]}" alt="{html.escape(im["alt"])}" width="{im["card_w"]}" height="{im["card_h"]}" loading="lazy"></a>
  <div class="card-body">
    <h3><a href="p/{p["slug"]}/">{html.escape(p["name"])}</a></h3>
    <p>{html.escape(p["summary"].replace("`", ""))}</p>
    <div class="card-foot">{price_html(p)}<a class="btn btn-sm" href="p/{p["slug"]}/">View</a></div>
  </div>
</article>""")
    body = f"""
<section class="hero"><div class="wrap">
  <h1>Spreadsheet templates and tools that save you hours.</h1>
  <p>Practical, well-tested Excel &amp; Google Sheets templates and developer tools, made by {BRAND}. No sign-ups. Everything is <strong>free during our launch</strong>.</p>
  <a class="btn" href="#products">Browse products</a>
</div></section>
<section id="products" class="wrap">
  <h2 class="section-title">Products</h2>
  <div class="grid">{''.join(cards)}</div>
</section>"""
    return page(f"{BRAND} | Spreadsheet templates & tools",
                "Practical Excel & Google Sheets templates and developer tools by Persline Templates. Free during launch.", body, 0,
                og_image=products[0]["images"][0]["full"] if products else None)

def load_all():
    prods = []
    for f in sorted((ROOT / "products").glob("*/product.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        p["description_md"] = (f.parent / "description.md").read_text(encoding="utf-8")
        prods.append(p)
    prods.sort(key=lambda p: (p.get("order", 100), p.get("created", "")), reverse=False)
    return prods

def rebuild():
    prods = load_all()
    for p in prods:
        d = ROOT / "p" / p["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_product_page(p), encoding="utf-8")
    (ROOT / "index.html").write_text(build_index(prods), encoding="utf-8")
    print(f"rebuilt {len(prods)} product page(s) + index.html")

# ---------------------------------------------------------------- git / release
def run(cmd, **kw):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)

def push(msg):
    run(["git", "add", "-A"])
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        run(["git", "commit", "-q", "-m", msg])
    run(["git", "push", "-q", "origin", "main"])

def release(p, zip_path):
    tag = p["download"]["tag"]
    exists = subprocess.run(["gh", "release", "view", tag, "-R", REPO], cwd=ROOT, capture_output=True).returncode == 0
    if exists:
        run(["gh", "release", "upload", tag, str(zip_path), "--clobber", "-R", REPO])
    else:
        run(["gh", "release", "create", tag, str(zip_path), "-R", REPO, "--target", "main",
             "--title", f'{p["name"]} v{p["version"]}',
             "--notes", f'{p["summary"]}\n\nProduct page: {SITE_URL}p/{p["slug"]}/\n\n{FOOTER_LINE}'])

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("web_dir", nargs="?", help="product folder: web package (product.json) or code folder (listing.md + description.md + zip)")
    ap.add_argument("--listing", help="legacy listing file (gumroad.md format)")
    ap.add_argument("--zip", help="zip to publish (legacy mode)")
    ap.add_argument("--images", nargs="*", default=[], help="gallery images (first = hero/card image)")
    ap.add_argument("--slug"); ap.add_argument("--version"); ap.add_argument("--name", help="override display name")
    ap.add_argument("--compat", nargs="*", help="'Works with' list")
    ap.add_argument("--license-note"); ap.add_argument("--disclaimer")
    ap.add_argument("--price-note", help="small text after the price, e.g. 'one-time, team license'")
    ap.add_argument("--order", type=int, default=100, help="sort position on the home page (lower = first)")
    ap.add_argument("--release", action="store_true", help="create/update the GitHub Release asset")
    ap.add_argument("--push", action="store_true", help="commit and push to main")
    ap.add_argument("--rebuild", action="store_true", help="only regenerate HTML")
    a = ap.parse_args()

    if a.rebuild:
        rebuild()
        if a.push: push("Rebuild site")
        return
    if a.web_dir:
        p = load_folder(a.web_dir)
        if a.images:  # explicit images replace the package's preview
            p["images"] = a.images
    elif a.listing:
        if not a.zip: sys.exit("--zip is required with --listing")
        p = parse_gumroad(a.listing)
        p.update(zip=a.zip, images=a.images, version=a.version or "1.0", compatibility=[], license_note="", disclaimer="", created="")
    else:
        ap.error("give a web package folder, --listing, or --rebuild")
    for k in ("slug", "version", "name", "license_note", "disclaimer", "price_note"):
        if getattr(a, k): p[k] = getattr(a, k)
    if a.compat: p["compatibility"] = a.compat
    if not p.get("slug"): sys.exit("slug missing (use --slug)")
    if not p["images"]: sys.exit("at least one image is required (--images)")
    zip_path = Path(p.pop("zip")).resolve()
    tag = f'{p["slug"]}-v{p["version"]}'
    p["download"] = dict(tag=tag, filename=zip_path.name, size_bytes=zip_path.stat().st_size,
                         url=f"https://github.com/{REPO}/releases/download/{tag}/{zip_path.name}")
    p["images"] = optimise_images(p["slug"], p["images"], p["name"])
    p["order"] = a.order
    out = ROOT / "products" / p["slug"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "description.md").write_text(p.pop("description_md").strip() + "\n", encoding="utf-8")
    (out / "product.json").write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rebuild()
    if a.push: push(f'Add/update product: {p["name"]} v{p["version"]}')
    if a.release: release(p, zip_path)
    print("product page:", f'{SITE_URL}p/{p["slug"]}/')
    print("download:   ", p["download"]["url"])

if __name__ == "__main__":
    main()
