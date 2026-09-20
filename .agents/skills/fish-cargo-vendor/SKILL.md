---
name: fish-cargo-vendor
description: >-
  Fix a Rust package build in this factory that fails because Fedora 44+ ships
  no binary crate RPMs. Use when a package's spec relies on the system-crate
  model (%cargo_generate_buildrequires / %cargo_prep without -v) and the build
  fails for missing crate RPMs, or when asked to vendor crates instead.
---

# Vendoring Rust crates for a F44+ build

Fedora 44 dropped the binary `crate-*` RPMs. A spec that pulls Rust deps from
the system-crate registry (`%cargo_generate_buildrequires` emitting
`BuildRequires: rust-*`, or `%cargo_prep` in its default local-registry mode)
no longer resolves and the build fails. The fix is `cargo vendor`: commit the
crate tree and build against it fully offline.

## When to Use

- A rebuild job fails with "no package provides `crate(<name>)`" / missing
  `rust-*` BuildRequires, or the ticket names F44 + a Rust package.
- The spec uses `%cargo_generate_buildrequires` or `%cargo_prep` (no `-v`).

## Procedure

1. **Generate the vendor tree.** Extract the release source, install cargo
   via rustup (no root), and run `cargo vendor --locked vendor` from the
   source root. `--locked` pins the tree to `Cargo.lock` for reproducibility.
   The emitted config maps `crates-io` -> `vendored-sources` and any git dep
   -> the same.
2. **Package it.** `tar -czf <name>-<version>-vendor.tar.gz -C <src> vendor`.
   Commit the tarball in `packages/<name>/`. Two repo guards are set up to
   allow this, both keyed on the `*-vendor.tar.gz` suffix — name the file that
   way or you will fight them:
   - `.gitignore` ignores `packages/*/*.tar.*` and `packages/*/*.gz` because
     those are normally pipeline-fetched artefacts. A negation re-includes
     `!packages/*/*-vendor.tar.gz`, so a plain `git add` works; a differently
     named tarball needs `git add -f`.
   - `check-added-large-files` caps additions at 500 KB by default, and a
     vendor tree is far bigger (fish's is ~12 MB). The hook carries an
     `exclude` for the same suffix. Do **not** reach for `git commit
     --no-verify` — that skips every other hook, including
     `detect-private-key` and the factory-contract check.
3. **Do NOT list it in `sources`.** `source_pipeline.py` only fetches
   sources-file entries, and this factory cannot push to
   `src.fedoraproject.org` lookaside, so a listed tarball 404s and fails the
   build. Committing it is enough: build-stage stages `packages/<name>/` with
   `cp -a`, so `Source11` is present without any fetch.

   The trade-off is that `verify_staged_sources` never checksums it, so git
   history is the only integrity anchor — unlike every other source, which the
   sha512 manifest covers. Two things follow. Generate the tree with
   `--locked` so it is reproducible from `Cargo.lock`, and say so in the PR
   body: a reviewer has to spot-check the vendored crates against crates.io,
   because no automated gate will. Record in the spec, next to `Source11`, why
   the tarball is absent from `sources`.
4. **Add the source.** `Source11: <name>-<version>-vendor.tar.gz` in the spec.
5. **Extract in %prep.** `tar -xf %{SOURCE11}` (after the upstream source and
   any fork extraction, before %autopatch).
6. **Switch cargo prep to vendor mode.** Replace `%cargo_prep` with
   `%cargo_prep -v vendor`. That macro emits `[net] offline = true` and
   `[source.crates-io] replace-with = "vendored-sources"` pointing at `vendor/`.
   Keep the existing `mv .cargo/config.toml … ; cat … >> .cargo/config.toml`
   dance so the upstream `[alias]` (xtask) survives — `%cargo_prep` wipes
   `.cargo/`.
7. **Drop the system-crate macro.** Remove the whole
   `%generate_buildrequires` / `%cargo_generate_buildrequires` block. It is
   the code that emitted the now-missing `rust-*` BuildRequires.
8. **Keep offline.** Leave `export CARGO_NET_OFFLINE=true` in %build.
9. **Declare bundled crates.** Add `Provides: bundled(crate(<name>)) = <ver>`
   for each vendored crate. Derive name+version from each
   `vendor/<crate>/Cargo.toml` [package] section (split the dir on the last
   `-` only when it is a clean name-version pair).

## Pitfalls

- **Git deps.** `%cargo_prep -v` does not emit a `[source."git+…"]` block. If a
  crate is a git source that is NOT converted to a path dep by a patch, either
  add the git->vendored-sources mapping manually or convert it to a path dep
  first (fish converts `pcre2` to a path dep via Patch1001, so the default
  mapping suffices).
- **Cargo.lock.** fish's build invokes `cargo build` with no `--locked`, so a
  patch that changes a crate from git to a path dep is reconciled at build time.
  If you build with `--locked`, a lock/source mismatch aborts the build.
- **`--locked` on generation.** Always run `cargo vendor --locked` so the
  committed tree matches `Cargo.lock`; otherwise rebuilds drift.
- **RPM version syntax in Provides.** RPM spec parsers reject hyphens in the
  version component of EVR (e.g. `Invalid version (double separator '-')`).
  When declaring `bundled(crate(...))` provides for crates with build metadata
  containing hyphens (such as `0.11.1+wasi-snapshot-preview1` or `1.0.1+wasi-0.2.4`),
  sanitize hyphens to underscores (e.g. `0.11.1+wasi_snapshot_preview1` and
  `1.0.1+wasi_0.2.4`).
- **Don't hand-edit `.hummingbird-upstream.json`.** Re-import it (see
  `hummingbird` skill) instead of editing by hand.

## Verification

- `python3 tools/factory_contract.py .` — no violations.
- `python3 tools/validate.py .` — package has a source lock and packit config.
- `python3 -m pytest tests -q` — passes (every package is in
  `config/upstream-sources.json`).
- `pre-commit run --files packages/<name>/<name>.spec packages/<name>/<name>-<v>-vendor.tar.gz` — passes.
  Note this only proves the hooks accept the files; `check-added-large-files`
  inspects *newly added* paths, so it reports "no files to check" once the
  tarball is committed. To prove the guards really let a fresh vendor tree in,
  stage it in a scratch clone and run the hook there before trusting it.
- If rpmbuild is available: `rpmbuild -br --define "_sourcedir ." packages/<name>/<name>.spec`
  and confirm `.cargo/config.toml` contains `replace-with = "vendored-sources"`.
