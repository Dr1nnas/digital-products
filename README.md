# Persline Templates storefront

Static storefront for Persline Templates, served by GitHub Pages from `main` / root:
**https://dr1nnas.github.io/digital-products/**

Plain HTML/CSS, no build step on GitHub (`.nojekyll` disables Jekyll). Pages are generated
locally by `scripts/add_product.py` and committed. Download zips are **not** stored in git;
each product version is a GitHub Release (`<slug>-v<version>`) with the zip as its asset.

During launch every product is free: the page shows the normal price struck through
("$16.99 — free during launch") and the Download button links straight to the Release asset.

## Layout

```
index.html                  home page (generated: product cards)
p/<slug>/index.html         product page (generated)
products/<slug>/product.json  normalised product data (source of truth for the pages)
products/<slug>/description.md  long description (markdown subset)
assets/style.css            site styles
assets/img/<slug>/*.webp    optimised images (1600px gallery, 800px card, 240px thumbs)
scripts/add_product.py      add/update a product, rebuild pages, push, create release
```

## Adding a new product (one command)

Requirements: Python 3.9+, Pillow, git, `gh` logged in with `repo` scope, a clone of this repo.

### From a product-maker web package (preferred)

The package folder looks like this:

```
web/
  product.json      title, name, slug, version, price_usd, summary, tags, compatibility,
                    license, description_path, preview, thumbnail, downloads[...]
  description.md    long description; a "## What you get" section becomes the sidebar box
  preview.png       hero image (used if no --images given)
  downloads/<Name>-v1.0.zip   the first download of type "zip" is published
```

```bash
python3 scripts/add_product.py /path/to/product/web \
  --images hero.png screen2.png screen3.png \   # optional gallery; first image = card/hero
  --license-note "Personal use only; see LICENSE.pdf in the download." \
  --release --push
```

Optional `product.json` keys the script also understands: `gallery` (list of extra image
paths), `disclaimer` (shown under the Download button).

### From a code-product folder (Product Maker: Code)

```
2026-10-19-envrampart/
  listing.md        "# name: tagline", "**Suggested price:** $19 USD (one-time; ...)",
                    "## Short description", "## License summary", "## Tags"
  description.md    long description (fenced code blocks supported; "## Price" is dropped,
                    "## What's included" becomes the sidebar box)
  preview.png       hero image (any ratio; the card version is padded to 5:4, not cropped)
  <name>-1.0.0.zip  published as the Release asset; version is read from the file name
```

```bash
python3 scripts/add_product.py /path/to/2026-10-19-envrampart \
  --name "envrampart: .env Validator & Secret Scanner CLI" \
  --compat "Python 3.8 or newer" "Linux, macOS and Windows" --release --push
```

The slug is the folder name without the date prefix. The script auto-detects the format:
`product.json` (or a `web/` subfolder with one) = web package; `listing.md` + `description.md` + zip = code folder.

### From a legacy listing file (gumroad.md format)

```bash
python3 scripts/add_product.py --listing gumroad.md --zip Product-v1.0.zip \
  --images 01-hero.png 02-screen.png --version 1.0 \
  --compat "Microsoft Excel" "Google Sheets" --disclaimer "Not affiliated with ..." \
  --release --push
```

### What the flags do

| flag | effect |
|---|---|
| *(none)* | writes `products/<slug>/`, images, and regenerates all HTML locally |
| `--push` | `git add -A && git commit && git push origin main` (Pages redeploys in ~1 min) |
| `--release` | creates Release `<slug>-v<version>` with the zip (or re-uploads it with `--clobber`) |
| `--name`, `--price-note`, `--compat`, `--license-note`, `--disclaimer` | override/add display fields |
| `--order N` | position on the home page (lower first; default 100) |
| `--rebuild` | regenerate HTML for all products from `products/*/product.json` (e.g. after a CSS/template change) |

New version of an existing product: bump `version` in its package and run the command again;
a new release tag is created and the page's Download button points at it.

### Checklist after publishing

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://dr1nnas.github.io/digital-products/p/<slug>/
curl -sL -o /dev/null -w '%{http_code}\n' https://github.com/Dr1nnas/digital-products/releases/download/<slug>-v<version>/<zip>
```

## Rules

- Licenses inside each zip apply; no resale or redistribution.
- Products about third-party platforms must carry a not-affiliated disclaimer (`--disclaimer`).
- Contact: shop@novif.app
