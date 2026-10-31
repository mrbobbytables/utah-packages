// The package catalog: renders packages.json, which tools/package_index.py
// writes from the published image's repodata layer.
"use strict";

// Fixed order: each shelf keeps its palette slot whatever the filter shows.
const SHELVES = [
  "GNOME & GTK", "Multimedia", "Hardware", "Graphics & display",
  "Tools & services", "Fonts & i18n", "Firmware & boot", "Libraries",
];
const HEADLINERS = [
  "gnome-shell", "mutter", "gtk4", "mesa", "pipewire", "ffmpeg",
  "flatpak", "webkitgtk", "fwupd", "grub2",
];
const shelfColor = (name) => `var(--s${SHELVES.indexOf(name) + 1 || 8})`;

const state = { q: "", cat: "", sort: "name", view: "grid", failing: false };
let data = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const evr = (p) => `${p.epoch ? p.epoch + ":" : ""}${p.version}-${p.release}`;
// Metadata-derived link targets (RPM URL:, upstream tarball, recipe remote)
// are only ever web addresses; anything else (javascript:, data:) is dropped
// rather than rendered as a clickable href. esc() still escapes the attribute.
const safeUrl = (s) => {
  try {
    const url = new URL(String(s ?? ""));
    return url.protocol === "https:" || url.protocol === "http:" ? String(s) : "";
  } catch {
    return "";
  }
};

function bytes(n) {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function ago(when) {
  const seconds = (Date.now() - when.getTime()) / 1000;
  const steps = [[60, "second"], [60, "minute"], [24, "hour"], [30, "day"], [12, "month"], [Infinity, "year"]];
  let value = seconds;
  for (const [size, unit] of steps) {
    if (Math.abs(value) < size) {
      return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(-Math.round(value), unit);
    }
    value /= size;
  }
  return when.toISOString();
}

const dateOf = (epoch) => new Date(epoch * 1000);

function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.append(el);
  setTimeout(() => el.remove(), 1600);
}

async function copy(text, label = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
    toast(label);
  } catch {
    toast("Copy failed — select it by hand");
  }
}

// --- URL state ------------------------------------------------------------

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  state.q = params.get("q") || "";
  state.cat = params.get("cat") || "";
  state.sort = params.get("sort") || "name";
  state.view = params.get("view") || "grid";
  state.failing = params.get("failing") === "1";
  return params.get("pkg");
}

// A package's own address: just its name, none of the browsing state, so a
// shared link opens the same package however the sender had filtered.
const pkgHash = (name) => `#${new URLSearchParams({ pkg: name })}`;
const permalink = (name) => `${location.origin}${location.pathname}${pkgHash(name)}`;

function writeHash(pkg, push = false) {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.cat) params.set("cat", state.cat);
  if (state.sort !== "name") params.set("sort", state.sort);
  if (state.view !== "grid") params.set("view", state.view);
  if (state.failing) params.set("failing", "1");
  if (pkg) params.set("pkg", pkg);
  const hash = params.toString();
  const url = hash ? `#${hash}` : location.pathname + location.search;
  // Opening a package from the page pushes an entry, so Back closes it.
  if (push) history.pushState({ detail: pkg }, "", url);
  else history.replaceState(null, "", url);
}

// --- header widgets ---------------------------------------------------------

function renderStats() {
  const { image, totals, generated_at: generated } = data;
  const created = image.created ? new Date(image.created) : null;
  const sha = image.revision ? image.revision.slice(0, 7) : "—";
  const stat = (k, v, href) => `<div class="stat"><span class="k">${esc(k)}</span>${
    href ? `<a class="v" href="${esc(href)}">${esc(v)}</a>` : `<span class="v">${esc(v)}</span>`}</div>`;
  const repo = "https://github.com/projectbluefin/utah-packages";
  $("stats").innerHTML = [
    stat("Source packages", totals.sources.toLocaleString()),
    stat("Binary RPMs", totals.rpms.toLocaleString()),
    stat("Download", bytes(totals.size)),
    stat("Installed", bytes(totals.installed)),
    stat("Published", created ? ago(created) : "—"),
    stat("Commit", sha, image.revision ? `${repo}/commit/${image.revision}` : null),
  ].join("");
  if (created) $("stats").children[4].title = created.toLocaleString();
  if (totals.failing.length) {
    $("stats").insertAdjacentHTML("beforeend",
      `<button class="stat" id="failing-stat" style="grid-column:1/-1;text-align:left;cursor:pointer;background:none;color:inherit;font:inherit">
        <span class="k">Latest build failing — previous build still shipping</span>
        <span class="v" style="color:var(--danger)">${totals.failing.map(esc).join(", ")}</span></button>`);
    $("failing-stat").onclick = () => { state.failing = !state.failing; update(); };
  }

  const ref = image.ref.replace(/:[^:/]+$/, "");
  const from = `COPY --from=${ref}${image.digest ? "@" + image.digest : ":latest"} /repository /etc/utah-packages`;
  $("from-line").textContent = from;
  $("copy-from").onclick = () => copy(from, "Copied the COPY --from line");

  const byName = new Map(data.packages.map((p) => [p.name, p]));
  $("headliners").innerHTML = HEADLINERS.filter((n) => byName.has(n)).map((n) =>
    `<a class="chip" href="${esc(pkgHash(n))}" data-pkg="${esc(n)}"><span class="chip-k">${esc(n)}</span>` +
    `<span class="chip-v">${esc(byName.get(n).version)}</span></a>`).join("");

  $("generated").textContent = ago(new Date(generated));
  $("generated").title = generated;
  if (image.digest) $("image-link").textContent = `${ref}@${image.digest.slice(0, 19)}…`;
}

function renderShelves() {
  const counts = new Map(SHELVES.map((s) => [s, 0]));
  for (const p of data.packages) counts.set(p.category, (counts.get(p.category) || 0) + 1);
  const total = data.packages.length;
  const tip = $("tooltip");

  $("shelf-bar").innerHTML = SHELVES.filter((s) => counts.get(s)).map((s) =>
    `<button type="button" data-cat="${esc(s)}" style="--c:${shelfColor(s)};flex:${counts.get(s)}"
       aria-label="${esc(s)}: ${counts.get(s)} packages"></button>`).join("");
  $("legend").innerHTML = SHELVES.filter((s) => counts.get(s)).map((s) =>
    `<li><button type="button" data-cat="${esc(s)}" style="--c:${shelfColor(s)}">
       <span class="sw"></span>${esc(s)}<span class="n">${counts.get(s)}</span></button></li>`).join("");

  for (const el of $("shelf-bar").children) {
    el.addEventListener("pointermove", (e) => {
      const n = counts.get(el.dataset.cat);
      tip.hidden = false;
      tip.innerHTML = `<strong>${esc(el.dataset.cat)}</strong><br>${n} packages · ${Math.round(100 * n / total)}%`;
      tip.style.left = `${Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8)}px`;
      tip.style.top = `${e.clientY + 14}px`;
    });
    el.addEventListener("pointerleave", () => { tip.hidden = true; });
  }
  for (const el of document.querySelectorAll("[data-cat]")) {
    el.addEventListener("click", () => {
      state.cat = state.cat === el.dataset.cat ? "" : el.dataset.cat;
      update();
      $("packages").scrollIntoView({ behavior: "smooth" });
    });
  }
}

// --- catalog --------------------------------------------------------------

function haystack(p) {
  return p._hay ??= [p.name, p.summary, p.license, p.version, p.category,
    ...p.rpms.map((r) => r.name)].join(" ").toLowerCase();
}

function score(p, terms) {
  if (!terms.length) return 1;
  const hay = haystack(p);
  if (!terms.every((t) => hay.includes(t))) return 0;
  const name = p.name.toLowerCase();
  const q = terms.join(" ");
  if (name === q) return 100;
  if (name.startsWith(q)) return 50;
  if (name.includes(q)) return 25;
  if (p.rpms.some((r) => r.name.toLowerCase() === q)) return 20;
  return 1;
}

function filtered() {
  const terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
  const rows = [];
  for (const p of data.packages) {
    if (state.cat && p.category !== state.cat) continue;
    if (state.failing && !p.failing) continue;
    const s = score(p, terms);
    if (s) rows.push([s, p]);
  }
  const order = {
    name: (a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base" }),
    recent: (a, b) => b.buildtime - a.buildtime,
    size: (a, b) => b.installed - a.installed,
    rpms: (a, b) => b.rpms.length - a.rpms.length,
  }[state.sort];
  rows.sort((a, b) => (terms.length && state.sort === "name" ? b[0] - a[0] : 0) || order(a[1], b[1]));
  return rows.map((r) => r[1]);
}

function highlight(text) {
  const terms = state.q.split(/\s+/).filter(Boolean)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return esc(text);
  const re = new RegExp(`(${terms.join("|")})`, "ig");
  return String(text).split(re).map((part, i) => (i % 2 ? `<mark>${esc(part)}</mark>` : esc(part))).join("");
}

function renderFilters() {
  const chip = (label, on, attrs, color) =>
    `<button type="button" class="filter${on ? " on" : ""}" ${attrs}${color ? ` style="--c:${color}"` : ""}>` +
    `${color ? '<span class="sw"></span>' : ""}${esc(label)}</button>`;
  $("filters").innerHTML = [
    chip("All shelves", !state.cat, 'data-filter-cat=""'),
    ...SHELVES.map((s) => chip(s, state.cat === s, `data-filter-cat="${esc(s)}"`, shelfColor(s))),
    data.totals.failing.length ? chip("Failing builds", state.failing, "data-filter-failing", "var(--danger)") : "",
  ].join("");
  for (const el of $("filters").querySelectorAll("[data-filter-cat]")) {
    el.onclick = () => { state.cat = el.dataset.filterCat; update(); };
  }
  const failing = $("filters").querySelector("[data-filter-failing]");
  if (failing) failing.onclick = () => { state.failing = !state.failing; update(); };
  $("shelf-bar").classList.toggle("filtered", !!state.cat);
  for (const el of document.querySelectorAll("#shelf-bar [data-cat], #legend [data-cat]")) {
    el.classList.toggle("on", el.dataset.cat === state.cat);
  }
  for (const el of document.querySelectorAll("[data-sort]")) el.classList.toggle("active", el.dataset.sort === state.sort);
  for (const el of document.querySelectorAll("[data-view]")) el.classList.toggle("active", el.dataset.view === state.view);
}

function renderResults() {
  const rows = filtered();
  const n = rows.length;
  $("count").textContent = `${n.toLocaleString()} of ${data.packages.length.toLocaleString()} source packages` +
    ` · ${rows.reduce((t, p) => t + p.rpms.length, 0).toLocaleString()} RPMs`;
  $("empty").hidden = n > 0;
  const results = $("results");

  if (state.view === "table") {
    results.className = "table-wrap";
    results.innerHTML = `<table><thead><tr><th>Package</th><th>Version</th><th>Summary</th>
      <th>Shelf</th><th class="num">RPMs</th><th class="num">Installed</th><th>Built</th></tr></thead><tbody>${
      rows.map((p) => `<tr data-pkg="${esc(p.name)}" tabindex="0">
        <td><a class="name" href="${esc(pkgHash(p.name))}" tabindex="-1">${highlight(p.name)}</a>${p.failing ? ' <span class="badge-fail" title="Latest build failing">⚠</span>' : ""}</td>
        <td class="mono">${esc(evr(p))}</td>
        <td class="sum">${highlight(p.summary)}</td>
        <td><span class="sw" style="--c:${shelfColor(p.category)}"></span>${esc(p.category)}</td>
        <td class="num">${p.rpms.length}</td>
        <td class="num">${bytes(p.installed)}</td>
        <td>${dateOf(p.buildtime).toISOString().slice(0, 10)}</td></tr>`).join("")}</tbody></table>`;
    return;
  }
  results.className = "grid";
  results.innerHTML = rows.map((p, i) => `
    <a class="card" href="${esc(pkgHash(p.name))}" data-pkg="${esc(p.name)}"
      style="--c:${shelfColor(p.category)};animation-delay:${Math.min(i, 30) * 12}ms">
      <span class="card-top"><span class="card-name">${highlight(p.name)}</span>
        <span class="card-ver" title="${esc(evr(p))}">${esc(p.version)}</span></span>
      <p class="card-sum">${highlight(p.summary)}</p>
      <span class="card-meta"><span class="cat">${esc(p.category)}</span>
        <span>${p.rpms.length} RPM${p.rpms.length === 1 ? "" : "s"}</span>
        <span>${bytes(p.installed)}</span>
        ${p.failing ? '<span class="badge-fail">⚠ failing</span>' : ""}</span>
    </a>`).join("");
}

function update(pkg) {
  writeHash(pkg);
  if ($("q").value !== state.q) $("q").value = state.q;
  renderFilters();
  renderResults();
}

// --- detail window ----------------------------------------------------------

function openDetail(name, push = false) {
  const p = data.packages.find((x) => x.name === name);
  if (!p) return;
  const stat = (k, v) => `<div class="stat"><span class="k">${esc(k)}</span><span class="v" title="${esc(v)}">${esc(v)}</span></div>`;
  const built = dateOf(p.buildtime);
  const names = p.rpms.map((r) => r.name).filter((n) => !/-(debuginfo|debugsource)$/.test(n));
  const install = `dnf install ${p.rpms.some((r) => r.name === p.name) ? p.name : names[0]}`;
  const homepage = safeUrl(p.url);
  const tarball = safeUrl(p.upstream.url);
  const remote = safeUrl((p.recipe.remote || "").replace(/\.git$/, ""));
  const links = [
    homepage && `<a class="btn" href="${esc(homepage)}" rel="noopener">Project homepage</a>`,
    tarball && `<a class="btn ghost" href="${esc(tarball)}" rel="noopener">Source tarball</a>`,
    remote && p.recipe.commit &&
      `<a class="btn ghost" href="${esc(remote)}/blob/${esc(p.recipe.commit)}/f/${esc(p.name)}.spec" rel="noopener">Fedora recipe @ ${esc(p.recipe.commit.slice(0, 7))}</a>`,
    `<a class="btn ghost" href="https://github.com/projectbluefin/utah-packages/tree/main/packages/${esc(p.name)}" rel="noopener">Recipe in factory</a>`,
    `<button class="btn ghost" type="button" id="copy-link">Copy link</button>`,
    `<button class="btn ghost" type="button" id="copy-install">Copy <code>${esc(install)}</code></button>`,
  ].filter(Boolean).join("");

  $("detail-url").textContent = `packages.local/${p.name}`;
  $("detail-body").innerHTML = `
    <div class="d-head"><h2 id="detail-name">${esc(p.name)}<a class="anchor" href="${esc(pkgHash(p.name))}"
        title="Link to ${esc(p.name)}" aria-label="Link to ${esc(p.name)}">#</a></h2>
      <span class="chip"><span class="chip-k">version</span><span class="chip-v">${esc(evr(p))}</span></span>
      <span class="filter on" style="--c:${shelfColor(p.category)};cursor:default"><span class="sw"></span>${esc(p.category)}</span>
      ${p.failing ? '<span class="badge-fail">⚠ latest build failing; this is the previous build</span>' : ""}</div>
    <p class="d-sum">${esc(p.summary)}</p>
    <p class="d-desc">${esc(p.description)}</p>
    <div class="d-grid">
      ${stat("License", p.license || "—")}
      ${stat("Built", built.toISOString().slice(0, 16).replace("T", " ") + " UTC")}
      ${stat("Upstream release", p.upstream.version || "—")}
      ${stat("Binary RPMs", String(p.rpms.length))}
      ${stat("Download", bytes(p.size))}
      ${stat("Installed", bytes(p.installed))}
    </div>
    <div class="d-links">${links}</div>
    <h3 class="group-label">Binary RPMs</h3>
    <div class="table-wrap"><table class="d-rpms"><thead><tr><th>RPM</th><th>Arch</th><th>Summary</th>
      <th class="num">Download</th><th class="num">Installed</th></tr></thead><tbody>${
      p.rpms.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.arch)}</td><td>${esc(r.summary)}</td>
        <td class="num">${bytes(r.size)}</td><td class="num">${bytes(r.installed)}</td></tr>`).join("")}</tbody></table></div>`;
  $("copy-install").onclick = () => copy(install);
  $("copy-link").onclick = () => copy(permalink(p.name), "Copied a link to " + p.name);
  const dialog = $("detail");
  writeHash(p.name, push && !dialog.open);
  if (!dialog.open) dialog.showModal();
  $("detail-body").scrollTop = 0;
}

// --- wiring -----------------------------------------------------------------

function wire() {
  let timer;
  $("q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = e.target.value.trim(); update(); }, 80);
  });
  for (const el of document.querySelectorAll("[data-sort]")) {
    el.onclick = () => { state.sort = el.dataset.sort; update(); };
  }
  for (const el of document.querySelectorAll("[data-view]")) {
    el.onclick = () => { state.view = el.dataset.view; update(); };
  }
  document.addEventListener("click", (e) => {
    const target = e.target.closest("[data-pkg]");
    if (!target) return;
    // Ctrl/Cmd/Shift/middle-click keep their link meaning: a new tab or window.
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openDetail(target.dataset.pkg, true);
  });
  // Back/forward, or a #pkg= link pasted into this same tab.
  const follow = () => {
    const pkg = readHash();
    update(pkg);
    if (pkg) openDetail(pkg);
    else if ($("detail").open) $("detail").close();
  };
  window.addEventListener("popstate", follow);
  window.addEventListener("hashchange", follow);
  $("results").addEventListener("keydown", (e) => {
    const row = e.target.closest("tr[data-pkg]");
    if (row && e.key === "Enter") openDetail(row.dataset.pkg, true);
  });
  // Closing an entry this page pushed steps back over it, so Back does not
  // reopen it; one opened from a pasted link just drops pkg from the hash.
  $("detail").addEventListener("close", () => {
    if (history.state?.detail) history.back();
    else writeHash();
  });
  $("detail").addEventListener("click", (e) => { if (e.target === $("detail")) $("detail").close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== $("q") && !$("detail").open) {
      e.preventDefault();
      $("q").focus();
    }
  });
}

async function main() {
  const pkg = readHash();
  wire();
  try {
    const response = await fetch("packages.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    data = await response.json();
  } catch (error) {
    $("count").textContent = `Could not load packages.json: ${error.message}`;
    $("stats").innerHTML = "";
    return;
  }
  renderStats();
  renderShelves();
  update(pkg);
  if (pkg) openDetail(pkg);
}

main();
