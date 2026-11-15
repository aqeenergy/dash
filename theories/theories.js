// THEORY LAB (bubble 4): AI theories from cross-reading the PSI archive.
// Data: /app/static/theories/theories.json (built by ia_web/teorias.py). Topic runs: AI server POST /ia/teorias.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = $("tl-root");
  if (!root) return;
  const CFG = window.FLAMA_IA || { puerto: 8001 };
  const host = (() => { try { return window.parent.location.hostname || "localhost"; } catch (e) { return "localhost"; } })();
  const LOCAL = /^(localhost|127\.|\[::1\]|$)/.test(host);
  const API = (CFG.base ? String(CFG.base).replace(/\/+$/, "") : `http://${host}:${CFG.puerto}`) + "/ia/teorias";
  const DEPLOYED = !!CFG.base || LOCAL;
  const list = $("tl-list"), status = $("tl-status"), hl = $("tl-highlights"), q = $("tl-q");
  let base = null, shown = [], openId = null, topicData = null;
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad = (n) => String(n).padStart(2, "0");
  const norm = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
  function resize() { if (window.frameElement) { const h = document.body.scrollHeight; if (h > 200) window.frameElement.style.height = (h + 20) + "px"; } }
  function setStatus(html, err) { status.innerHTML = html; status.classList.toggle("err", !!err); resize(); }

  // ------------------------------------------------------------------ highlights
  function renderHighlights(items) {
    if (!items.length) { hl.innerHTML = `<p class="tl-hl-h">Highest consensus</p><p class="tl-none">No theory has reached 10 supporting investigations yet.</p>`; return; }
    const top = [...items].sort((a, b) => (b.probability * b.n_support) - (a.probability * a.n_support)).slice(0, 3);
    hl.innerHTML = `<p class="tl-hl-h">Highest consensus</p>
      ${top.map((t) => `<button class="tl-hl-item" type="button" data-open="${esc(t.id)}"><span class="tl-hl-pct">${t.probability}%</span>
        <span class="tl-hl-t">${esc(t.title)}</span><span class="tl-hl-s">✅ ${t.n_support} for · ⚠️ ${t.n_against} against</span></button>`).join("")}
      <div class="tl-hl-sep"></div><p class="tl-hl-h">Recommended next experiments</p>
      ${top.map((t) => `<div class="tl-hl-exp"><b>${esc(t.experiment.title)}</b> — ${esc(t.experiment.platform)}</div>`).join("")}`;
  }

  // ------------------------------------------------------------------ cards
  function docHTML(d, against) {
    return `<div class="tl-doc"><div class="tl-doc-h"><b>${esc(d.acc)}</b><span>${esc(d.title)}</span><em>${esc(d.area)}</em></div>
      ${against ? `<span class="tl-stance">${d.stance === "contradicts" ? "Contradicts" : "Qualifies"}</span>` : ""}
      <div>${esc(d.datum)}</div><q>“${esc(d.quote)}”</q>
      <button class="tl-open" type="button" data-lib="${esc(d.lib)}" data-quote="${esc(d.quote)}">Open this document in the database library</button></div>`;
  }
  function cardHTML(t) {
    const open = openId === t.id, e = t.experiment;
    return `<article class="tl-card ${open ? "open" : ""}" data-id="${esc(t.id)}">
      <button class="tl-card-head" type="button" aria-expanded="${open}">
        <span class="tl-rank">${pad(t.rank)}</span>
        <span class="tl-title">${esc(t.title)}</span>
        <span class="tl-prob"><b>${t.probability}%</b><span>probability</span></span>
        <span class="tl-sum">${esc(t.summary)}</span>
        <span class="tl-meta"><span>✅ ${t.n_support} for | ⚠️ ${t.n_against} against</span><span class="tl-exptag">Suggested experiment: ${esc(e.title)}</span>
          <span class="tl-tags">${(t.tags || []).map((g) => `<span class="tl-tag">${esc(g)}</span>`).join("")}</span></span>
      </button>
      <div class="tl-detail" ${open ? "" : "hidden"}>
        <h5>Hypothesis</h5><p class="tl-hyp">${esc(t.hypothesis)}</p>
        <div class="tl-exp"><h5>Proposed microgravity experiment · ${esc(e.title)}</h5><p>${esc(e.design)}</p>
          <dl><dt>Platform</dt><dd>${esc(e.platform)}</dd><dt>Vary</dt><dd>${esc((e.variables || []).join(" · "))}</dd><dt>Measure</dt><dd>${esc((e.measurements || []).join(" · "))}</dd></dl></div>
        <div class="tl-cols">
          <div class="tl-col for"><h6>✅ Supporting investigations (${t.n_support})</h6>${t.support.map((d) => docHTML(d, false)).join("")}</div>
          <div class="tl-col against"><h6>⚠️ Contradicting or qualifying (${t.n_against})</h6>${t.against.length ? t.against.map((d) => docHTML(d, true)).join("") : `<p class="tl-none">No PSI document contradicts or qualifies this hypothesis in the checked set.</p>`}</div>
        </div>
        <p class="tl-none">Probability ${t.probability}% = (S + 1) / (S + C + 2) with S = ${t.n_support}, C = ${t.contra_weight} · ${t.checked} investigations checked.</p>
      </div></article>`;
  }
  function render(items, title) {
    shown = items;
    $("tl-listtitle").textContent = title;
    list.innerHTML = items.length ? items.map(cardHTML).join("") : `<div class="tl-empty">No theory matches this filter. Press <b>Ask the AI</b> to run a new synthesis on this topic.</div>`;
    resize();
  }
  const top10 = (items) => [...items].sort((a, b) => (b.n_support - a.n_support) || (b.probability - a.probability)).slice(0, 10)
    .sort((a, b) => (b.probability - a.probability) || (b.n_support - a.n_support));
  function applyFilter() {
    if (!base) return;
    const term = norm(q.value.trim());
    const pool = topicData ? topicData.theories : base.theories;
    const items = !term ? top10(pool) : pool.filter((t) => norm([t.title, t.summary, t.hypothesis, (t.tags || []).join(" "), t.experiment.title,
      ...t.support.map((d) => d.acc + " " + d.title), ...t.against.map((d) => d.acc + " " + d.title)].join(" ")).includes(term));
    const n = items.length;
    render(items, topicData ? `AI theories on “${topicData.topic}” (${n})` : term ? `Theories matching “${q.value.trim()}” (${n})`
      : n >= 10 ? "Top 10 theories" : `Top theories · ${n} have reached 10+ supporting investigations so far`);
  }

  // Flammy comments on the theory being read (never invents: counts and experiment come from the data)
  function flammySays(t) {
    if (!t || !window.flammyBuddy || !window.flammyBuddy.tip) return;
    const against = t.n_against ? `${t.n_against} contradicting or qualifying` : "nothing in the checked set contradicts it yet";
    window.flammyBuddy.tip(`${t.probability}% · ${t.title}`,
      `Backed by ${t.n_support} PSI investigations; ${against}. Next step: ${t.experiment.title} (${t.experiment.platform}). Still a hypothesis to confirm.`);
  }

  // ------------------------------------------------------------------ AI topic run
  async function askAI(tema) {
    if (!DEPLOYED) {
      setStatus(`Public site: showing the stored theories (each one built and cited from the base_de_datos files) that match “${esc(tema)}”. New syntheses run on the local version.`);
      applyFilter(); return;
    }
    const btn = $("tl-ask"); btn.disabled = true;
    setStatus(`The AI is cross-reading all ${base ? base.corpus.investigations : 133} investigations for <b>${esc(tema)}</b>. This takes a few minutes; you can keep browsing.`);
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tema }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
      const { job } = await r.json();
      const t0 = Date.now();
      for (;;) {
        await new Promise((res) => setTimeout(res, 4000));
        const s = await (await fetch(`${API}/${job}`)).json();
        if (s.estado === "listo") {
          topicData = s.resultado; q.value = "";
          const st = topicData.stats;
          setStatus(`Done: ${st.candidates} candidate hypotheses on <b>${esc(tema)}</b>, ${st.kept} kept with ≥10 supporting investigations, ${st.discarded_low_support} discarded. <button class="tl-open" type="button" id="tl-back">Back to the global Top 10</button>`);
          applyFilter(); renderHighlights(topicData.theories.length ? topicData.theories : base.theories);
          if (window.flammyBuddy && window.flammyBuddy.tip) window.flammyBuddy.tip(`Theory Lab · ${tema}`, st.kept
            ? `${st.kept} hypotheses passed the 10-investigation filter. Open one to see the evidence for and against.`
            : `No hypothesis on this topic reached 10 supporting investigations, so none is shown.`);
          break;
        }
        if (s.estado === "error") throw new Error(s.mensaje || "synthesis failed");
        setStatus(`Synthesising <b>${esc(tema)}</b>… ${Math.round((Date.now() - t0) / 1000)} s`);
      }
    } catch (err) {
      setStatus(`Could not run the AI synthesis (${esc(err.message)}). Start the AI server: <code>voz\\.venv\\Scripts\\python -m uvicorn ia_web.servidor_web:app --port ${CFG.puerto}</code>. Showing filtered results from the last full synthesis instead.`, true);
      applyFilter();
    } finally { btn.disabled = false; }
  }

  // ------------------------------------------------------------------ events
  $("tl-form").addEventListener("submit", (e) => { e.preventDefault(); const t = q.value.trim(); if (t.length >= 2) askAI(t); });
  q.addEventListener("input", () => { topicData = null; applyFilter(); });
  $("tl-how").addEventListener("click", () => {
    const p = $("tl-howpanel"), open = p.hidden; p.hidden = !open; $("tl-how").setAttribute("aria-expanded", String(open)); resize();
  });
  root.addEventListener("click", (e) => {
    if (e.target.id === "tl-back") { topicData = null; setStatus(""); applyFilter(); renderHighlights(base.theories); return; }
    const op = e.target.closest(".tl-open[data-lib]");
    if (op) { window.dispatchEvent(new CustomEvent("flama:abrir-archivo", { detail: { archivo: op.dataset.lib, extracto: op.dataset.quote } })); return; }
    const hi = e.target.closest("[data-open]");
    if (hi) { openId = hi.dataset.open; applyFilter(); flammySays(shown.find((t) => t.id === openId)); const c = list.querySelector(`[data-id="${CSS.escape(openId)}"]`); if (c && window.flammyBuddy) window.flammyBuddy.scrollParentTo(c, 16); return; }
    const head = e.target.closest(".tl-card-head");
    if (head) {
      const id = head.closest(".tl-card").dataset.id; openId = openId === id ? null : id; applyFilter();
      if (openId) flammySays(shown.find((t) => t.id === openId));
    }
  });

  fetch("app/static/theories/theories.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => {
    base = d;
    const st = d.stats, rules = d.rules;
    $("tl-howpanel").innerHTML = `<p><b>How the AI builds each theory</b></p><ol>
      <li><b>Discover:</b> the model reads all ${d.corpus.investigations} PSI investigations (${esc(d.corpus.areas.join(", "))}) and proposes cross-cutting hypotheses.</li>
      <li><b>Verify:</b> for each hypothesis it re-reads every candidate investigation and must quote it verbatim; quotes not found word-for-word in the document are discarded (${st.quotes_rejected} rejected in this run).</li>
      <li><b>Filter:</b> only hypotheses with at least ${rules.min_support} different supporting investigations are shown (${st.kept} kept, ${st.discarded_low_support} discarded).</li></ol>
      <div class="tl-formula">Probability = (S + 1) / (S + C + 2)</div>
      <p>S = verified supporting investigations · C = contradicting + 0.5 × qualifying. It is a Laplace-smoothed evidence balance, not a measured statistic. Last full synthesis: ${esc(d.generated)} with ${esc(d.model || "Gemini")}.</p>`;
    renderHighlights(d.theories);
    applyFilter();
  }).catch(() => { list.innerHTML = `<div class="tl-empty">No synthesis has been generated yet. Run <code>voz\\.venv\\Scripts\\python -m ia_web.teorias</code> or ask the AI about a topic.</div>`; resize(); });
})();
