const $ = (id) => document.getElementById(id);
const PSI_TO_KPA = 6.894757;
const ctl = { g: $("g"), p: $("p"), o2: $("o2"), flow: $("flow"), mat: $("mat"), q: $("q") };

function params() {
  return {
    gravity_g: +ctl.g.value,
    pressure_psi: +ctl.p.value,
    o2_pct: +ctl.o2.value,
    airflow_cm_s: +ctl.flow.value,
    material: ctl.mat.value.trim(),
    question: ctl.q.value.trim(),
  };
}

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n, d = 1) => n.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });

function regime(g) { return g <= 0.01 ? "0g" : g >= 0.99 ? "1g" : "partial"; }

function updateReadout() {
  const p = params();
  const kpa = p.pressure_psi * PSI_TO_KPA, ppo2 = kpa * p.o2_pct / 100;
  $("gOut").textContent = `${p.gravity_g.toFixed(2)} g`;
  $("pOut").textContent = `${fmt(kpa)} kPa (${p.pressure_psi.toFixed(1)} psi)`;
  $("o2Out").textContent = `${fmt(p.o2_pct)} %`;
  $("flowOut").textContent = `${p.airflow_cm_s} cm/s`;
  $("kRegime").textContent = { "0g": "Microgravedad", "1g": "Terrestre", partial: "Parcial" }[regime(p.gravity_g)];
  $("kP").textContent = `${fmt(kpa)} kPa`;
  $("kPO2").textContent = `${fmt(ppo2)} kPa`;
  $("kO2").textContent = `${fmt(p.o2_pct)} %`;

  for (const box of document.querySelectorAll(".chips")) {
    const v = +ctl[box.dataset.for].value;
    for (const b of box.children) b.classList.toggle("on", Math.abs(+b.dataset.v - v) < 1e-6);
  }

  // Indicadores cualitativos (no sustituyen al análisis): sólo umbrales físicos simples.
  const flags = [];
  if (regime(p.gravity_g) === "partial")
    flags.push(["info", "Gravedad parcial: sin datos PSI directos. El análisis usará el Motor de Extrapolación (límites 0g / 1g)."]);
  if (p.o2_pct > 30) flags.push(["crit", `Atmósfera enriquecida (${fmt(p.o2_pct)} % O₂): límites de inflamabilidad ampliados.`]);
  else if (p.o2_pct > 23.5) flags.push(["warn", `O₂ por encima del aire (${fmt(p.o2_pct)} %): mayor riesgo de inflamabilidad.`]);
  if (ppo2 > 21.3 * 1.05) flags.push(["warn", `pO₂ de ${fmt(ppo2)} kPa, superior al nivel del mar.`]);
  if (regime(p.gravity_g) === "0g" && p.airflow_cm_s === 0)
    flags.push(["info", "0 g sin flujo inducido: el transporte de oxidante es sólo difusivo."]);
  $("flags").innerHTML = flags.map(([c, t]) => `<div class="flag ${c}">${esc(t)}</div>`).join("");
}

let retrieveTimer;
function scheduleRetrieve() {
  clearTimeout(retrieveTimer);
  retrieveTimer = setTimeout(async () => {
    const r = await fetch("/api/retrieve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params()) });
    if (r.ok) renderSources((await r.json()).hits);
  }, 250);
}

function renderSources(hits) {
  $("hitCount").textContent = `(${hits.length} fragmentos)`;
  $("sources").innerHTML = hits.length ? hits.map((h) => `
    <li id="src-${esc(h.id)}"><details>
      <summary><span class="sid">${esc(h.id)}</span> ${esc(h.heading || h.title)}
        ${h.gravity.map((g) => `<span class="tag">${esc(g)}</span>`).join("")}
        ${h.source === "SEED" ? '<span class="tag seed">SEED</span>' : ""}
        <span class="tag">bm25 ${h.score}</span></summary>
      <p>${esc(h.title)}</p><p>${esc(h.text)}</p>
    </details></li>`).join("") : '<li class="empty">Sin fragmentos relevantes.</li>';
}

function renderMarkdown(md, streaming) {
  let html = DOMPurify.sanitize(marked.parse(md));
  html = html.replace(/\[([A-Z0-9]+-\d{2})\]/g, '<a class="cite" href="#src-$1">$1</a>');
  $("out").innerHTML = html;
  $("out").classList.toggle("cursor", streaming);
}

async function analyze() {
  const btn = $("run");
  btn.disabled = true;
  $("meta").textContent = "";
  $("out").innerHTML = '<p class="empty">Recuperando evidencia y consultando el modelo…</p>';
  let md = "";
  try {
    const r = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params()) });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = /^event: (.*)$/m.exec(block)?.[1];
        const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? "null");
        if (ev === "sources") renderSources(data);
        else if (ev === "text") { md += data; renderMarkdown(md, true); }
        else if (ev === "error") { md += `\n\n<p class="err">⚠ ${esc(data)}</p>`; renderMarkdown(md, false); }
        else if (ev === "done") $("meta").textContent =
          `· ${data.model} · ${data.input_tokens} in / ${data.output_tokens} out${data.cache_read ? ` · caché ${data.cache_read}` : ""}`;
      }
    }
  } catch (e) {
    md += `\n\n<p class="err">⚠ ${esc(String(e))}</p>`;
  } finally {
    renderMarkdown(md || '<p class="empty">Sin respuesta.</p>', false);
    btn.disabled = false;
  }
}

for (const box of document.querySelectorAll(".chips"))
  box.addEventListener("click", (e) => {
    if (!e.target.dataset.v) return;
    ctl[box.dataset.for].value = e.target.dataset.v;
    updateReadout(); scheduleRetrieve();
  });
for (const el of Object.values(ctl)) el.addEventListener("input", () => { updateReadout(); scheduleRetrieve(); });
$("run").addEventListener("click", analyze);

fetch("/api/status").then((r) => r.json()).then((s) => {
  const st = $("status");
  st.textContent = `${s.model} · ${s.documents.length} documentos · ${s.chunks} fragmentos${s.seed_only ? " · corpus SEED (no oficial)" : ""}`;
  st.classList.toggle("warn", s.seed_only);
});
updateReadout();
scheduleRetrieve();
