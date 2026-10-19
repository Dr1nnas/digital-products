# Persline store (shop.novif.app)

Static, data-driven store on GitHub Pages: **https://shop.novif.app/** (custom domain; HTTPS enforced).
No build step on GitHub (`.nojekyll`): pages are generated locally and committed.

## How it works

```
products/<slug>/product.json   public product data (one file per product) — source of truth
products/<slug>/description.md long description (markdown subset, fenced code ok)
scripts/build_site.py          generator (≈0.6 s for 1,000 products)
scripts/add_product.py         ingest product folders → images, data, build, push, releases
assets/                        style.css, store.js (search/filters), product.js (gallery), img/<slug>/*.webp
```

Generated: `index.html` (hero, featured, categories, newest), `p/<slug>/` product pages,
`c/<cat>/` + `c/<cat>/page/<n>/` (24 per page), `search/` (client-side search + filters + sort),
`data/catalog.json` (all products, compact), `data/c/<cat>.json` (per-category chunks used when
filtering/sorting a category page), `sitemap.xml`, `robots.txt`, `404.html`.

Downloads are GitHub Release assets (`<slug>-v<version>`), never committed. Digital products are
free during launch (price shown struck through). Physical products show the price and a
"Coming soon: notify me" mailto button (shop@novif.app); there is no checkout.

## Adding products (one command, batch-capable)

```bash
python3 scripts/add_product.py <folder> [<folder> ...] [--category printables] [--release] [--push]
```

Folder formats are auto-detected:

| format | contents |
|---|---|
| templates web package | `product.json` with `downloads[]` (+ `description.md`, `preview.png`), or a parent with `web/` |
| code product | `listing.md` + `description.md` + `preview.png` + `<name>-1.0.0.zip` (category `dev-tools`) |
| supplier | `product.json` with `type` digital/physical, `category`, `price_usd`, `compare_at_usd?`, `summary`, `tags`, `specs{}`, `whats_included[]`, `images[]`, `files[]` (digital: must include a .zip) + `description.md` |
| legacy | `--listing gumroad.md --zip X.zip --images …` |

Supplier rules:
- `supplier_url`, `unit_cost_usd`, `moq`, `supplier`, `supplier_sku`, `cost_notes`, `image_license`
  are written **only** to `/workspace/products/internal/<slug>.json` (outside this repo). The public
  `product.json` is built from a whitelist, so unknown fields never reach the site.
- Physical items with `image_license` missing or `"unknown"` are refused.
- `shipping_estimate` and `lead_time_days` are shown to customers.

Batch mode: pass many folders; everything is rebuilt once, pushed once, then one Release per digital product.
Useful flags: `--images a.png b.png` (gallery, first = card), `--name`, `--category`, `--price-note`,
`--compat …`, `--license-note`, `--disclaimer`, `--featured`, `--order N`, `--rebuild`.

Categories are listed in `CATEGORIES` in `scripts/build_site.py` (unknown category slugs get an auto title).

## After publishing

`/workspace/sites/check_live.sh "<text on home page>"` waits for the deploy, checks the home page
status and certificate, every product page, every download, categories, search, catalog and sitemap.

## Rules

Licenses inside each zip apply; no resale. Products about third-party platforms carry a
not-affiliated disclaimer. Contact: shop@novif.app
