#!/usr/bin/env python3
"""Add (or update) products on the Persline storefront.

    python3 scripts/add_product.py <folder> [<folder> ...] [--release] [--push]
    python3 scripts/add_product.py --rebuild [--push]

Accepted folder formats (auto-detected):
  1. Templates web package: product.json (with downloads[]) + description.md + preview.png
     or a parent folder with a web/ subfolder of that shape.
  2. Code-product folder: listing.md + description.md + preview.png + <name>-1.0.0.zip
  3. Supplier folder: product.json (type digital|physical, files[], images[]) + description.md
     Internal fields (supplier_url, unit_cost_usd, moq, …) are written only to
     /workspace/products/internal/<slug>.json and NEVER committed.
  4. Legacy: --listing gumroad.md --zip Product.zip --images …

Batch: pass many folders; images are converted once each, the site is rebuilt once,
then (optionally) one git push and one Release per digital product.

Physical items with image_license "unknown" are refused. Product URLs stay /p/<slug>/.
"""
import argparse, html, json, os, re, shutil, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as site  # noqa: E402

REPO = os.environ.get("STORE_REPO", "Dr1nnas/digital-products")
SITE_URL = os.environ.get("STORE_URL", "https://shop.novif.app/")
INTERNAL_DIR = Path("/workspace/products/internal")
INTERNAL_FIELDS = ("supplier_url", "unit_cost_usd", "moq", "supplier", "supplier_sku", "cost_notes")
PUBLIC_KEYS = ("name", "slug", "type", "category", "version", "price_usd", "compare_at_usd",
               "summary", "tags", "specs", "whats_included", "compatibility", "license_note",
               "disclaimer", "shipping_estimate", "lead_time_days", "created", "added",
               "featured", "order", "price_note", "images", "download")

# ---------------------------------------------------------------- markdown helpers (for gumroad only)
def parse_gumroad(path):
    text = Path(path).read_text(encoding="utf-8")
    secs = {k.strip().lower(): v.strip() for k, v in
            re.findall(r"^##\s+(.+?)\n(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S)}
    def sec(prefix):
        return next((v for k, v in secs.items() if k.startswith(prefix)), "")
    name = sec("product name").splitlines()[0].strip()
    price = float(re.search(r"\$([\d.]+)", sec("price")).group(1))
    summary = sec("summary").splitlines()[0].strip()
    slug = sec("url slug").splitlines()[0].strip() if sec("url slug") else None
    raw = [l.rstrip() for l in sec("description").splitlines() if "gumroad" not in l.lower()]
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
    return dict(name=name, slug=slug, price_usd=price, summary=summary, description_md=desc, tags=tags,
                type="digital", version="1.0", compatibility=[], license_note="", disclaimer="", created="")

def load_web_package(d):
    d = Path(d)
    pj = json.loads((d / "product.json").read_text(encoding="utf-8"))
    desc = (d / pj.get("description_path", "description.md")).read_text(encoding="utf-8") if (d / pj.get("description_path", "description.md")).exists() else ""
    summary = pj.get("summary") or ((d / "summary.txt").read_text().strip() if (d / "summary.txt").exists() else "")
    zips = [x for x in pj.get("downloads", []) if x.get("type") == "zip" or x["path"].endswith(".zip")]
    if not zips:
        sys.exit(f"{d}: product.json has no zip download")
    images = [str(d / p) for key in ("gallery", "images") for p in pj.get(key, [])]
    if pj.get("preview"):
        images.insert(0, str(d / pj["preview"]))
    return dict(name=pj.get("name") or pj["title"], slug=pj["slug"], version=str(pj.get("version", "1.0")),
                type="digital", category=pj.get("category", ""), price_usd=float(pj["price_usd"]),
                summary=summary, description_md=desc, tags=pj.get("tags", []),
                compatibility=pj.get("compatibility", []), license_note=pj.get("license", ""),
                disclaimer=pj.get("disclaimer", ""), created=pj.get("created", ""),
                whats_included=pj.get("whats_included", []), specs=pj.get("specs", {}),
                zip=str(d / zips[0]["path"]), images=images)

def load_code_folder(d):
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
    images = [str(x) for x in [d / "preview.png"] if x.exists()] + [str(x) for x in sorted(d.glob("screenshot*.png"))]
    return dict(name=name, slug=re.sub(r"^\d{4}-\d{2}-\d{2}-", "", d.name),
                version=vm.group(1) if vm else "1.0", type="digital", category="dev-tools",
                price_usd=float(pm.group(1)), price_note=(pm.group(2).strip().rstrip(";,") if pm else ""),
                summary=" ".join(sec("short description").split()),
                description_md=(d / "description.md").read_text(encoding="utf-8"),
                tags=[t.strip() for t in re.split(r"[,\n]", sec("tags")) if t.strip()],
                compatibility=[], license_note=" ".join(sec("license summary").replace("(for the listing page)", "").split()),
                disclaimer="", created="", zip=str(zips[0]), images=images)

def load_supplier_folder(d):
    d = Path(d)
    pj = json.loads((d / "product.json").read_text(encoding="utf-8"))
    kind = pj.get("type", "digital")
    if kind not in ("digital", "physical"):
        sys.exit(f"{d}: type must be 'digital' or 'physical'")
    if kind == "physical" and str(pj.get("image_license", "unknown")).lower() == "unknown":
        sys.exit(f"{d}: refusing physical product with image_license 'unknown'")
    desc = (d / "description.md").read_text(encoding="utf-8") if (d / "description.md").exists() else ""
    images = [str(d / p) for p in pj.get("images", [])]
    if pj.get("preview") and str(d / pj["preview"]) not in images:
        images.insert(0, str(d / pj["preview"]))
    files = [str(d / (f["path"] if isinstance(f, dict) else f)) for f in pj.get("files", [])]
    zips = [f for f in files if f.endswith(".zip")]
    if kind == "digital" and not zips:
        sys.exit(f"{d}: digital supplier product needs a .zip in files[]")
    internal = {k: pj[k] for k in INTERNAL_FIELDS if k in pj}
    internal.update(slug=pj["slug"], image_license=pj.get("image_license", ""),
                    shipping_estimate=pj.get("shipping_estimate", ""), lead_time_days=pj.get("lead_time_days"))
    return dict(name=pj.get("name") or pj["title"], slug=pj["slug"], type=kind,
                category=pj.get("category", "physical-products" if kind == "physical" else ""),
                version=str(pj.get("version", "1.0")), price_usd=float(pj["price_usd"]),
                compare_at_usd=pj.get("compare_at_usd"), summary=pj.get("summary", ""),
                description_md=desc, tags=pj.get("tags", []), specs=pj.get("specs", {}),
                whats_included=pj.get("whats_included", []), compatibility=pj.get("compatibility", []),
                license_note=pj.get("license", ""), disclaimer=pj.get("disclaimer", ""),
                shipping_estimate=pj.get("shipping_estimate", ""), lead_time_days=pj.get("lead_time_days"),
                created=pj.get("created", ""), zip=zips[0] if zips else None, images=images, _internal=internal)

def load_folder(d):
    d = Path(d)
    if (d / "listing.md").exists() and (d / "description.md").exists() and not (d / "product.json").exists():
        return load_code_folder(d)
    if (d / "product.json").exists():
        pj = json.loads((d / "product.json").read_text(encoding="utf-8"))
        # supplier shape: explicit type, or files[], or supplier_url
        if pj.get("type") in ("digital", "physical") or "files" in pj or "supplier_url" in pj:
            # but web packages also have type-less downloads[]; prefer web if downloads present and no supplier fields
            if "downloads" in pj and "files" not in pj and "supplier_url" not in pj and pj.get("type") != "physical":
                return load_web_package(d)
            return load_supplier_folder(d)
        return load_web_package(d)
    if (d / "web" / "product.json").exists():
        return load_web_package(d / "web")
    sys.exit(f"{d}: not a recognised product folder")

# ---------------------------------------------------------------- images
def pad_to_ratio(im, ratio):
    from PIL import Image
    w, h = im.size
    nw, nh = (w, round(w / ratio)) if w / h > ratio else (round(h * ratio), h)
    canvas = Image.new(im.mode, (nw, nh), im.getpixel((0, 0)))
    canvas.paste(im, ((nw - w) // 2, (nh - h) // 2))
    return canvas

def optimise_images(slug, sources, name=""):
    from PIL import Image
    out_dir = ROOT / "assets" / "img" / slug
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    seen, result = set(), []
    for src in sources:
        src = Path(src)
        if not src.exists() or src.resolve() in seen: continue
        seen.add(src.resolve())
        im = Image.open(src)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        stem = re.sub(r"^[0-9]+-", "", re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-")) or "image"
        label_txt = stem.replace("-", " ").capitalize()
        entry = {"alt": f"{name}: {label_txt}" if name else label_txt}
        n = len(result) + 1
        for label, width, q in (("full", 1600, 80), ("card", 800, 78), ("thumb", 240, 72)):
            if label == "card" and result: continue
            src_im = im
            if label == "card" and abs(im.width / im.height - 1.25) > 0.02:
                src_im = pad_to_ratio(im, 1.25)
            w = min(width, src_im.width)
            h = round(src_im.height * w / src_im.width)
            fname = f"{n:02d}-{stem}{'' if label == 'full' else '-' + label}.webp"
            src_im.resize((w, h), Image.LANCZOS).save(out_dir / fname, "WEBP", quality=q, method=6)
            entry[label] = f"assets/img/{slug}/{fname}"
            if label == "full": entry["w"], entry["h"] = w, h
            else: entry[label + "_w"], entry[label + "_h"] = w, h
        result.append(entry)
    return result

# ---------------------------------------------------------------- save / release / push
def save_product(p, order, featured):
    internal = p.pop("_internal", None)
    zip_path = p.pop("zip", None)
    if zip_path:
        z = Path(zip_path).resolve()
        tag = f'{p["slug"]}-v{p["version"]}'
        p["download"] = dict(tag=tag, filename=z.name, size_bytes=z.stat().st_size,
                             url=f"https://github.com/{REPO}/releases/download/{tag}/{z.name}")
    p["images"] = optimise_images(p["slug"], p["images"], p["name"]) if p.get("images") else []
    p["order"] = order
    if featured: p["featured"] = True
    p.setdefault("type", "digital")
    from datetime import datetime
    old = ROOT / "products" / p["slug"] / "product.json"
    p["added"] = (json.loads(old.read_text()).get("added") if old.exists() else None) or datetime.now().isoformat(timespec="seconds")
    out = ROOT / "products" / p["slug"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "description.md").write_text((p.pop("description_md") or "").strip() + "\n", encoding="utf-8")
    public = {k: v for k, v in p.items() if k in PUBLIC_KEYS and v not in (None, "", [], {})}
    (out / "product.json").write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if internal:
        INTERNAL_DIR.mkdir(parents=True, exist_ok=True)
        (INTERNAL_DIR / f'{p["slug"]}.json').write_text(json.dumps(internal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return (Path(zip_path).resolve() if zip_path else None), public

def run(cmd):
    print("+", " ".join(cmd)); subprocess.run(cmd, cwd=ROOT, check=True)

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
             "--notes", f'{p["summary"]}\n\nProduct page: {SITE_URL}p/{p["slug"]}/\n\nFree during launch. Personal and commercial use per included license; no resale.'])

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", help="product folder(s)")
    ap.add_argument("--listing"); ap.add_argument("--zip"); ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--slug"); ap.add_argument("--version"); ap.add_argument("--name")
    ap.add_argument("--compat", nargs="*"); ap.add_argument("--license-note"); ap.add_argument("--disclaimer")
    ap.add_argument("--price-note"); ap.add_argument("--category")
    ap.add_argument("--type", dest="ptype", choices=["digital", "physical"])
    ap.add_argument("--order", type=int, default=100); ap.add_argument("--featured", action="store_true")
    ap.add_argument("--release", action="store_true"); ap.add_argument("--push", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    if a.rebuild and not a.folders and not a.listing:
        site.build(); 
        if a.push: push("Rebuild site")
        return
    items = []
    if a.listing:
        if not a.zip: sys.exit("--zip is required with --listing")
        p = parse_gumroad(a.listing); p.update(zip=a.zip, images=a.images, version=a.version or p["version"])
        items.append(p)
    for f in a.folders:
        p = load_folder(f)
        if a.images: p["images"] = a.images
        items.append(p)
    if not items: ap.error("give one or more product folders, --listing, or --rebuild")
    releases = []
    for p in items:
        for k, attr in (("slug", "slug"), ("version", "version"), ("name", "name"),
                        ("license_note", "license_note"), ("disclaimer", "disclaimer"),
                        ("price_note", "price_note"), ("category", "category")):
            if getattr(a, attr): p[k] = getattr(a, attr)
        if a.ptype: p["type"] = a.ptype
        if a.compat: p["compatibility"] = a.compat
        if not p.get("slug"): sys.exit("slug missing")
        if not p.get("images"): sys.exit(f'{p["slug"]}: at least one image is required')
        zip_path, public = save_product(p, a.order, a.featured)
        if a.release and zip_path: releases.append((public, zip_path))
        print("product page:", f'{SITE_URL}p/{public["slug"]}/')
        if public.get("download"): print("download:   ", public["download"]["url"])
    site.build()
    if a.push: push("Add/update " + ", ".join(it.get("slug", "?") for it in items))
    for public, zip_path in releases: release(public, zip_path)

if __name__ == "__main__":
    main()
