// SAFETY MECHANISMS bubble: ranked PSI research (data: /app/static/safety/research.json, built by safety_research.py)
(function () {
  "use strict";
  const URL_DATA = "app/static/safety/research.json";  // relative (Streamlit Cloud serves under /~/+/)
  const $ = (id) => document.getElementById(id);
  const root = $("sm-root");
  if (!root) return;
  const grid = $("sm-grid"), detail = $("sm-detail"), layout = $("sm-layout"), how = $("sm-how"), howBtn = $("sm-how-btn");
  let data = null, filter = "All", openAcc = null;
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");
  const CHECK = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.2 4.2L19 7"/></svg>`;
  const WARN = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 16.5v.2"/><circle cx="12" cy="12" r="9"/></svg>`;
  function resize() { if (window.frameElement) { const h = document.body.scrollHeight; if (h > 200) window.frameElement.style.height = (h + 20) + "px"; } }
  function openFile(id, columns) { if (id) window.dispatchEvent(new CustomEvent("flama:abrir-archivo", { detail: { archivo: id, columnas: columns || [] } })); }

  function verification(src) {
    if (!src.record_available) return { ok: false, text: "PSI record not available locally" };
    if (src.doi_check && src.doi_check.ok) return { ok: true, text: `Verified · local record + DOI resolves (${src.doi_check.checked})` };
    if (src.doi) return { ok: true, text: "Local PSI record with DOI · online check not run" };
    return { ok: false, text: "No DOI in the local record" };
  }

  function card(it) {
    const v = verification(it.source);
    return `<article class="sm-card" tabindex="0" role="button" aria-current="${openAcc === it.acc}" data-acc="${esc(it.acc)}" aria-label="${esc(it.acronym)}, FLAMA Score ${it.score}. Open details">
      <div class="sm-top"><span class="sm-rank">${pad(it.rank)}</span><span class="sm-acr">${esc(it.acronym)}</span><span class="sm-acc">${esc(it.acc)}</span>
        <span class="sm-cat sm-cat-${esc(it.category)}">${esc(it.category)}</span></div>
      <div class="sm-title">${esc(it.title)}</div>
      <p class="sm-sum">${esc(it.summary)}</p>
      <div><div class="sm-scorelbl">FLAMA Score</div>
        <div class="sm-scorebox"><span class="sm-score">${it.score}<small>/100</small></span><span class="sm-meter" aria-hidden="true"><i style="width:${it.score}%"></i></span></div></div>
      <div class="sm-verify ${v.ok ? "" : "warn"}">${v.ok ? CHECK : WARN}${esc(v.text)}</div>
      <div class="sm-actions"><button class="sm-btn sm-explore" type="button" data-file="${esc(it.source.record_lib)}">Explore Research</button>
        <button class="sm-btn ghost sm-more" type="button">Details</button></div>
    </article>`;
  }

  function render() {
    if (!data) return;
    const items = data.items.filter((it) => filter === "All" || it.tags.includes(filter));
    grid.innerHTML = items.length ? items.map(card).join("") : `<div class="sm-empty">No research in this category.</div>`;
    resize();
  }

  function block(n, title, inner) { return `<section class="sm-block"><h5><span class="sm-n">${n}</span>${esc(title)}</h5>${inner}</section>`; }

  function showDetail(acc) {
    const it = data.items.find((x) => x.acc === acc); if (!it) return;
    openAcc = acc; layout.classList.add("open"); detail.hidden = false; render();
    const s = it.source, c = it.criteria, v = verification(s);
    const crit = ["A", "H", "E", "F"].map((k) => {
      const names = { A: "Direct safety application · 40%", H: "Relevance to crewed habitats · 25%", E: "Evidence strength & access · 20%", F: "Value for future design · 15%" };
      return `<b>${k}</b><span>${names[k]} — ${esc(c[k].why)} <span class="sm-label ${c[k].editorial ? "ours" : "data"}">${c[k].editorial ? "FLAMA assessment" : "computed"}</span></span><em>${c[k].score}/3</em>`;
    }).join("");
    const hist = it.history && it.history.length ? it.history.map((h) => `<div class="sm-hist"><span class="sm-label hist">${esc(h.link)}</span><p><b>${esc(h.event)}.</b> ${esc(h.text)}</p></div>`).join("")
      + `<p class="sm-meta">Historical context comes from the general historical record, not from <code>base_de_datos</code>.</p>`
      : `<p class="sm-meta">No accident is linked to this study.</p>`;
    detail.innerHTML = `
      <div class="sm-d-head"><div><h4>${pad(it.rank)} · ${esc(it.acronym)}</h4><p>${esc(it.title)} · ${esc(it.acc)}</p></div>
        <button class="sm-close" type="button" aria-label="Close details"><svg width="12" height="12" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 1l8 8M9 1L1 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button></div>
      ${block("1", "What NASA Studied", `<span class="sm-label quote">Quoted from the PSI record</span>
        <p class="sm-quote">${esc(it.studied.objective)}</p>
        ${it.studied.hypothesis ? `<p><b>Hypothesis.</b> ${esc(it.studied.hypothesis)}</p>` : ""}
        ${it.studied.hardware ? `<p class="sm-meta">Hardware: ${esc(it.studied.hardware)}</p>` : ""}`)}
      ${block("2", "Key Findings", `<span class="sm-label data">Measured · computed from base_de_datos</span>
        <ul>${it.findings.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        <p class="sm-meta">Source table: <code>${esc(s.table_file || "not available")}</code>${s.table_rows ? ` · ${s.table_rows} rows` : ""}</p>`)}
      ${block("3", "Safety Application", `<span class="sm-label ours">FLAMA assessment · possible application</span>
        <p>${esc(it.application)}</p>
        ${it.impact_quote ? `<span class="sm-label quote">The PSI record says</span><p class="sm-quote">${esc(it.impact_quote)}</p>` : ""}
        <span class="sm-label ours">Limitation</span><p>${esc(it.limitation)}</p>`)}
      ${block("4", "Source & Evidence", `<div class="sm-verify ${v.ok ? "" : "warn"}">${v.ok ? CHECK : WARN}${esc(v.text)}</div>
        <div class="sm-links">${s.doi ? `<a href="${esc(s.doi_url)}" target="_blank" rel="noopener">DOI ${esc(s.doi)}</a>` : ""}
          <a href="${esc(s.psi_url)}" target="_blank" rel="noopener">NASA PSI repository page</a></div>
        <div class="sm-actions"><button class="sm-btn sm-open" type="button" data-file="${esc(s.record_lib)}">Open record in library</button>
          ${s.table_lib ? `<button class="sm-btn ghost sm-open" type="button" data-file="${esc(s.table_lib)}">Open data table</button>` : ""}</div>
        <p class="sm-meta">Local files: <code>base_de_datos/${esc(s.record_file)}</code>${s.table_file ? ` · <code>base_de_datos/${esc(s.table_file)}</code>` : ""} · ${s.publications} publications listed in the record.</p>
        <div class="sm-crit">${crit}</div>
        <p class="sm-meta">FLAMA Score ${it.score}/100 = round(100 × (0.40·${c.A.score} + 0.25·${c.H.score} + 0.20·${c.E.score} + 0.15·${c.F.score}) / 3)</p>`)}
      ${block("5", "Historical Context", hist)}`;
    resize();
    if (window.flammyBuddy && window.flammyBuddy.scrollParentTo && window.innerWidth <= 980) window.flammyBuddy.scrollParentTo(detail, 16);
  }

  function hideDetail() { openAcc = null; detail.hidden = true; layout.classList.remove("open"); render(); }

  function renderHow() {
    const w = data.weights;
    how.innerHTML = `<h4>FLAMA Score — this project's own ranking, not a NASA rating</h4>
      <div class="sm-formula">Score = round( 100 × (0.40·A + 0.25·H + 0.20·E + 0.15·F) / 3 )</div>
      <div class="sm-weights">
        <div class="sm-weight"><span class="sm-pct">${Math.round(w.A * 100)}%</span><b>A · Direct safety application</b>Explicit link to fire prevention, detection or suppression. Scored 0–3 by FLAMA from the PSI record.</div>
        <div class="sm-weight"><span class="sm-pct">${Math.round(w.H * 100)}%</span><b>H · Relevance to crewed habitats</b>Microgravity, cabin atmospheres, ventilation and real spacecraft materials. Scored 0–3 by FLAMA.</div>
        <div class="sm-weight"><span class="sm-pct">${Math.round(w.E * 100)}%</span><b>E · Evidence strength & access</b>Computed: +1 DOI in the local record, +1 measured values in ≥10 rows of the local table, +1 ≥10 publications listed.</div>
        <div class="sm-weight"><span class="sm-pct">${Math.round(w.F * 100)}%</span><b>F · Value for future design</b>Documented use for sensors, materials, models or extinguishing strategies. Scored 0–3 by FLAMA.</div>
      </div>
      <small>Each criterion is an integer 0–3. A, H and F are our assessments, justified on every card; E is computed from the files. Ties are ordered by accession.</small>`;
  }

  root.addEventListener("click", (e) => {
    const chip = e.target.closest(".sm-chip");
    if (chip) {
      filter = chip.dataset.cat;
      root.querySelectorAll(".sm-chip").forEach((c) => c.setAttribute("aria-selected", String(c === chip)));
      render(); return;
    }
    if (e.target.closest("#sm-how-btn")) { const open = how.hidden; how.hidden = !open; howBtn.setAttribute("aria-expanded", String(open)); resize(); return; }
    const ex = e.target.closest(".sm-explore, .sm-open");
    if (ex) { e.stopPropagation(); openFile(ex.dataset.file); return; }
    if (e.target.closest(".sm-close")) { hideDetail(); return; }
    const c = e.target.closest(".sm-card");
    if (c) showDetail(c.dataset.acc);
  });
  root.addEventListener("keydown", (e) => {
    const c = e.target.closest && e.target.closest(".sm-card");
    if (c && (e.key === "Enter" || e.key === " ") && e.target === c) { e.preventDefault(); showDetail(c.dataset.acc); }
    if (e.key === "Escape" && openAcc) hideDetail();
  });

  fetch(URL_DATA, { cache: "no-cache" }).then((r) => r.json()).then((d) => { data = d; renderHow(); render(); })
    .catch(() => { grid.innerHTML = `<div class="sm-empty">Research data not available. Restart the web app so it can be generated from base_de_datos.</div>`; resize(); });
})();
