---
name: package-catalog
description: >-
  How the GitHub Pages package catalog is built: tools/package_index.py reads
  the published image's repodata layer from ghcr.io, site/ renders it, and
  .github/workflows/pages.yml deploys it. Load before changing the catalog,
  its data, its styling, or anything that would make Pages serve RPMs.
metadata:
  type: reference
---

# The package catalog

GitHub Pages serves a browsable index of every source package and binary RPM
the factory publishes: search, shelves, a table view, per-package detail with
subpackages, sizes, licenses and links to the upstream tarball and the Fedora
recipe commit.

It is **a view, not a publication**. The Pages RPM mirror was retired (README,
"What it produces"; `docs/targeting-hummingbird.md`) and the OCI image is the
only thing consumers read. Never add RPMs, repodata or a `.repo` file to the
site: that rebuilds the mirror the history already removed.

## Where the data comes from

`tools/package_index.py` reads `ghcr.io/<owner>/utah-packages:latest` over
the registry HTTP API — no podman, no container:

- **layers[0] only.** `publish-repository.yml` builds the image as
  `COPY repository/repodata` then `COPY repository`, so the first layer is
  repodata alone (about 3.5 MiB) and the second is every RPM (about 1.7 GiB).
  The tool refuses a first layer of 64 MiB or more rather than pull the RPMs
  by accident. If the image layout changes, this is the assumption that breaks.
- **primary.xml** (found through `repomd.xml`; gz, xz or zst) gives each RPM's
  name, EVR, summary, description, URL, license, sizes, build time and
  source RPM. Binaries are folded into their source package by `sourcerpm`.
- **Image labels** give the commit, the run, and
  `org.projectbluefin.factory.state`, whose `failed` map marks packages whose
  latest build failed and still ship an older one.
- **The checkout** adds only what the image does not carry: the upstream
  tarball URL from `config/upstream-sources.json` and the Fedora recipe commit
  from `packages/<name>/.hummingbird-upstream.json`.

Gotchas, learned rendering the first catalog:

- **Anonymous token first.** ghcr.io refuses a token scoped to some other
  repository even for a public image, so the tool asks anonymously and falls
  back to `GITHUB_TOKEN` only when that fails.
- **The source's own binary may not exist.** `jpegxl` ships `libjxl*`, and the
  first one in repodata is `libjxl-doc`. `lead_rank` picks the text: the
  same-named binary, then a runtime package, then `-devel`, then docs and
  debug data.
- **Numeric cells never wrap.** Size columns sit in tables whose text cells
  wrap; a `.num` cell without `white-space: nowrap` splits "10.1 KiB" over
  two lines in the detail window.
- **Shelves are capped at eight.** The site colours them from the dataviz
  reference palette's eight categorical slots, in fixed order. Python modules
  fold into Libraries for that reason. `CATEGORIES` is a reading aid only;
  nothing in the factory relies on it.

## Package links

Every package has a shareable address, `<site>/#pkg=<name>`: cards, table
names and headline chips are real `<a href="#pkg=…">` links, and the detail
window has a `#` anchor and **Copy link**. Keep them links, not buttons:
Ctrl/middle-click and "copy link address" only work on an `href`. The
permalink carries the name alone, never the sender's search or filters.
Opening a package from the page pushes a history entry so Back closes it;
closing it steps back over that entry so Back does not reopen it.

## Run it locally

```sh
python3 tools/package_index.py --output site/packages.json   # live registry
python3 -m http.server -d site 8000
```

`site/packages.json` is gitignored. Tests use `--layer` and `--config` against
a synthetic layer (`tests/test_package_index.py`); nothing in `just check`
touches the network.

## Deploy

`.github/workflows/pages.yml` runs after every completed `Build verified
upstream RPMs` run on `main`, on pushes to `site/**` or the tool, daily, and
on dispatch. Pages deploys from the default branch only, which suits a view of
`:latest` — that tag is only published from `main` too.

Pages must be enabled once by a repository admin with **Settings → Pages →
Source: GitHub Actions**; the workflow's token cannot enable it.

## Styling

Borrowed from <https://projectbluefin.io/server/>: its colour tokens
(`#0c1016` / `#f1f6f8`, blue `#4285f4` / `#2059ae`), the translucent blurred
cards, uppercase eyebrows, mono version chips, the pill tab strip, and the
browser-window chrome around the detail view. The wallpapers and wordmark are
hot-linked from projectbluefin.io rather than copied, so a site refresh there
carries over; if one of those paths 404s, take the new path from that site's
page source.
