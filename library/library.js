// Database library: browse every file of base_de_datos as text (rendered by biblioteca.py).
// Opened from Bubble 1 (SORT → Database library) or from an AI citation (flama:abrir-archivo).
(function () {
  "use strict";
  const URL_INDEX = "/app/static/library/index.json";
  const $ = (id) => document.getElementById(id);
  const root = $("psi-library"), list = $("lib-list"), view = $("lib-view");
  if (!root) return;
  let files = null, current = null, filterText = "";
  const KIND = { record: "Investigation record", table: "Experimental table", workbook: "Workbook sheet", doc: "Document", catalog: "Catalogue", log: "Log" };

  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));  // safe in text AND attributes
  const fmtSize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : b > 1024 ? Math.round(b / 1024) + " KB" : b + " B");
  const norm = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
  function resize() { if (window.frameElement) { const h = document.body.scrollHeight; if (h > 200) window.frameElement.style.height = (h + 20) + "px"; } }

  async function load() {
    if (files) return files;
    try { files = (await (await fetch(URL_INDEX, { cache: "no-cache" })).json()).files || []; }
    catch (e) { files = []; list.innerHTML = `<div class="lib-empty">The text library is not available yet. Restart the web app so it can be generated.</div>`; }
    return files;
  }

  // ------------------------------------------------------------------ list
  function renderList() {
    if (!files) return;
    const q = norm(filterText);
    const shown = files.filter((f) => !q || norm(`${f.file} ${f.label} ${f.investigation} ${f.acc} ${f.title}`).includes(q));
    const groups = new Map();
    for (const f of shown) {
      const k = f.acc ? `${f.acc}` : "General";
      if (!groups.has(k)) groups.set(k, { name: f.acc ? `${f.acc} · ${f.investigation}` : "General", title: f.acc ? f.title : "Guides, catalogue and logs", items: [] });
      groups.get(k).items.push(f);
    }
    list.innerHTML = shown.length ? [...groups.values()].map((g) => `
      <div class="lib-group"><div class="lib-group-h">${esc(g.name)} <span>${esc(g.title ? "— " + g.title : "")}</span></div>
      ${g.items.map((f) => `<button class="lib-item" type="button" data-id="${esc(f.id)}" aria-current="${current && current.id === f.id}">
        <b>${esc(f.label)}</b><small>${esc(f.file)}${f.rows != null ? " · " + f.rows + " rows" : ""} · ${fmtSize(f.size)}</small></button>`).join("")}
      </div>`).join("") : `<div class="lib-empty">No database file matches “${esc(filterText)}”.</div>`;
  }

  // ------------------------------------------------------------------ parsers / renderers
  function parseCSV(text) {
    const rows = []; let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
      else if (c === '"') q = true;
      else if (c === ",") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
      else cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows.filter((r) => r.some((c) => c.trim() !== ""));
  }
  function tableHTML(rows, highlightCols) {
    if (!rows.length) return `<div class="lib-hint">This file has no rows.</div>`;
    const head = rows[0], wanted = (highlightCols || []).map(norm).filter(Boolean);
    const hl = head.map((h) => wanted.length > 0 && wanted.some((w) => norm(h) === w || norm(h).startsWith(w) || w.startsWith(norm(h))));
    const th = `<tr><th class="lib-rn">#</th>${head.map((h, i) => `<th class="${hl[i] ? "hl" : ""}">${esc(h)}</th>`).join("")}</tr>`;
    const body = rows.slice(1, 2001).map((r, n) => `<tr><td class="lib-rn">${n + 1}</td>${head.map((_, i) => `<td class="${hl[i] ? "hl" : ""}">${esc(r[i] ?? "")}</td>`).join("")}</tr>`).join("");
    const more = rows.length > 2001 ? `<div class="lib-hint">Showing the first 2,000 of ${rows.length - 1} rows.</div>` : "";
    return `<table class="lib-table"><thead>${th}</thead><tbody>${body}</tbody></table>${more}`;
  }
  function inline(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<em>$2</em>"); }
  function mdHTML(md) {
    const out = []; const lines = md.split(/\r?\n/); let i = 0, para = [];
    const flush = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
    while (i < lines.length) {
      const l = lines[i];
      if (/^#\s/.test(l)) { flush(); out.push(`<h1>${inline(l.slice(2))}</h1>`); }
      else if (/^##\s/.test(l)) { flush(); out.push(`<h2>${inline(l.slice(3))}</h2>`); }
      else if (/^\s*[-*]\s/.test(l)) { flush(); const items = []; while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) items.push(`<li>${inline(lines[i++].replace(/^\s*[-*]\s/, ""))}</li>`); out.push(`<ul>${items.join("")}</ul>`); continue; }
      else if (/^\|/.test(l)) {
        flush(); const rows = []; while (i < lines.length && /^\|/.test(lines[i])) { if (!/^\|[\s|:-]+\|$/.test(lines[i])) rows.push(lines[i].split("|").slice(1, -1).map((c) => c.trim())); i++; }
        out.push(`<table><thead><tr>${rows[0].map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`); continue;
      }
      else if (!l.trim()) flush();
      else para.push(l.trim());
      i++;
    }
    flush();
    return `<div class="lib-md">${out.join("")}</div>`;
  }
  // Highlight the cited excerpt inside a rendered record (best effort; text-node level, no HTML injection)
  function markExcerpt(container, excerpt) {
    if (!excerpt) return false;
    const clean = excerpt.replace(/[#*_`>|-]+/g, " ").replace(/\s+/g, " ").trim();
    const words = clean.split(" ");
    const probes = [];
    for (let s = 0; s + 7 <= words.length && probes.length < 12; s += 4) probes.push(words.slice(s, s + 7).join(" "));
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const probe of probes) {
      const p = probe.toLowerCase();
      for (const n of nodes) {
        const idx = n.nodeValue.toLowerCase().indexOf(p);
        if (idx < 0) continue;
        const range = document.createRange(); range.setStart(n, idx); range.setEnd(n, idx + probe.length);
        const mark = document.createElement("mark"); range.surroundContents(mark);
        return mark;
      }
    }
    return false;
  }

  // ------------------------------------------------------------------ preview
  async function open(id, opts = {}) {
    await load();
    const f = files.find((x) => x.id === id);
    if (!f) { view.innerHTML = `<div class="lib-hint">This file is not in the library: ${esc(id)}</div>`; return; }
    current = f; renderList();
    const item = list.querySelector('.lib-item[aria-current="true"]');
    if (item) list.scrollTop = Math.max(0, item.offsetTop - list.offsetTop - 40);  // keep the opened file visible in the list
    const tags = [`<span class="lib-tag">${esc(KIND[f.kind] || f.kind)}</span>`];
    if (f.rows != null) tags.push(`<span class="lib-tag">${f.rows} rows · ${f.cols} columns</span>`);
    if (opts.columns && opts.columns.length) tags.push(`<span class="lib-tag hl">Columns used by the AI: ${esc(opts.columns.join(", "))}</span>`);
    if (opts.excerpt) tags.push(`<span class="lib-tag hl">Passage consulted by the AI highlighted</span>`);
    view.innerHTML = `<div class="lib-view-h"><h4>${esc(f.acc ? f.acc + " · " + f.investigation + " — " + f.label : f.label)}</h4>
      <div class="lib-path">Database file <code>base_de_datos/${esc(f.file)}</code>${f.sheet ? " · sheet “" + esc(f.sheet) + "”" : ""} · ${fmtSize(f.size)}${f.kind === "record" ? " · readable rendering" : ""}</div>
      <div class="lib-tags">${tags.join("")}</div></div><div class="lib-body" id="lib-body"><div class="lib-hint">Loading…</div></div>`;
    const body = $("lib-body");
    try {
      const text = await (await fetch(f.url, { cache: "no-cache" })).text();
      if (/\.csv$/.test(f.id)) body.innerHTML = tableHTML(parseCSV(text), opts.columns);
      else if (/\.md$/.test(f.id)) body.innerHTML = mdHTML(text);
      else body.innerHTML = `<pre class="lib-pre">${esc(text)}</pre>`;
      if (opts.excerpt) { const m = markExcerpt(body, opts.excerpt); if (m) body.scrollTop = Math.max(0, m.offsetTop - 80); }
      if (opts.columns && opts.columns.length) { const th = body.querySelector("th.hl"); if (th) body.scrollLeft = Math.max(0, th.offsetLeft - 60); }
    } catch (e) { body.innerHTML = `<div class="lib-hint">Could not load this file.</div>`; }
    resize();
  }

  list.addEventListener("click", (e) => { const b = e.target.closest(".lib-item"); if (b) open(b.dataset.id); });

  window.flamaLibrary = {
    async show() { root.hidden = false; await load(); renderList(); if (!current) view.innerHTML = `<div class="lib-hint">Choose a file to preview it. Every entry is a file of <code>base_de_datos</code>, shown as text.</div>`; resize(); },
    hide() { root.hidden = true; resize(); },
    filter(t) { filterText = t || ""; renderList(); },
    open,
  };
})();
