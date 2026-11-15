// Flammy rule engine — browser port of flammy_agent/engine.py + agent.py (same rules, same output shape).
// Runs entirely client-side so Flammy works on any host (no local HTTP port, no mixed content).
// Knowledge (rules, materials, sources, fire response...) is injected as window.FLAMMY_KNOWLEDGE,
// built read-only from base_de_datos by psi_database.py.
(function () {
  "use strict";
  const K = window.FLAMMY_KNOWLEDGE || {};
  const MATERIALS = K.materials || {}, RULES = K.rules || [], FIRE = K.fire_response || {}, CLASS_NOTES = K.class_notes || {};
  const SOURCES = K.sources || {}, EXPERIMENTS = K.experiments || {}, FALLBACK = K.fallback || {}, DISCLAIMER = K.disclaimer || "";
  const LEVELS = { info: 1, caution: 2, danger: 3 }, SIGNAL = { info: "blue", caution: "amber", danger: "red" };
  let nextId = 1;
  const lastSig = {};

  const norm = (s) => String(s == null ? "" : s).toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const uniq = (a) => a.filter((x, i) => a.indexOf(x) === i);
  const asList = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

  const GRAV = [
    ["micro", /microgravity|micro-gravity|zero[- ]?g\b|zero gravity|weightless|freefall|free-fall|\b0 ?g\b|\biss\b|space station/],
    ["lunar", /\bmoon\b|lunar|\b1\/6\b|0\.16|artemis/],
    ["earth", /\bearth\b|\b1 ?g\b|normal gravity|terrestrial|ground[- ]based|drop tower on earth/],
  ];
  const IGN = [
    ["battery", /batter|li-?ion|lithium|laptop|tablet|power ?bank|thermal runaway/],
    ["electrical", /spark|short[- ]circuit|electrical|overheat|\barc(ing)?\b/],
    ["hot", /hot surface|heater|heating element/],
    ["flame", /open flame|welding|candle|lighter|\bmatch(es)?\b/],
  ];
  const TOPIC = [
    ["fire", /\bfire\b|\bburn|combust|ignit|blaze/],
    ["flame", /flame|spherical|\bblue\b|invisible|visible/],
    ["extinguisher", /extinguish|suppress|put out|fire[- ]?fight/],
    ["smoke", /smoke|detector|alarm|detection/],
    ["gas", /\bgas(es)?\b|carbon monoxide|toxic|\bco2\b|\bco\b|fumes/],
    ["standard", /standard|6001|certif|qualif|approved|rated/],
  ];
  const MAT = Object.fromEntries(Object.entries(MATERIALS).map(([mid, m]) => [mid,
    (m.aliases || []).map((a) => new RegExp("(?<![a-z0-9])" + norm(a).split(/[ -]/).map(reEsc).join("[\\s-]?") + "(?![a-z0-9])"))]));
  const O2_A = /(\d{1,2}(?:\.\d+)?)\s*%\s*(?:of\s*)?(?:o2|oxygen)/, O2_B = /(?:o2|oxygen)[^\d%]{0,25}(\d{1,2}(?:\.\d+)?)\s*%/;
  const PRESS = /(\d+(?:\.\d+)?)\s*(psia|psi|kpa|atm|bar)\b/, PUNIT = { psia: 6.894757, psi: 6.894757, kpa: 1, atm: 101.325, bar: 100 };
  const VENT_NONE = /no ventilation|without ventilation|still air|quiescent|no airflow|no air flow|stagnant|fan off|ventilation off|no flow/;
  const VENT_FORCED = /ventilation|\bfan\b|airflow|air flow|forced flow|draft/;

  function gravFrom(v) {
    if (typeof v === "number") return v <= 0.05 ? "micro" : v <= 0.5 ? "lunar" : "earth";
    const n = norm(v);
    if (["micro", "lunar", "earth"].includes(n)) return n;
    for (const [g, rx] of GRAV) if (rx.test(n)) return g;
    return null;
  }
  const matsFrom = (n) => Object.keys(MAT).filter((mid) => MAT[mid].some((r) => r.test(n)));

  function extract(text) {
    const n = norm(text), c = { gravities: [], materials: [], ignitions: [], topics: [], o2: null, pressure_kpa: null, ventilation: null, assumed_gravity: false };
    c.gravities = GRAV.map(([g, rx]) => [n.search(rx), g]).filter(([i]) => i >= 0).sort((a, b) => a[0] - b[0]).map(([, g]) => g);
    c.materials = matsFrom(n);
    c.ignitions = IGN.filter(([, rx]) => rx.test(n)).map(([g]) => g);
    c.topics = TOPIC.filter(([, rx]) => rx.test(n)).map(([g]) => g);
    const m = n.match(O2_A) || n.match(O2_B); if (m) c.o2 = parseFloat(m[1]);
    const p = n.match(PRESS); if (p) c.pressure_kpa = parseFloat(p[1]) * PUNIT[p[2]];
    if (VENT_NONE.test(n)) c.ventilation = "none"; else if (VENT_FORCED.test(n)) c.ventilation = "forced";
    return c;
  }

  function buildContext(params, text, defaultGravity) {
    params = params || {};
    const c = text ? extract(text) : { gravities: [], materials: [], ignitions: [], topics: [], o2: null, pressure_kpa: null, ventilation: null, assumed_gravity: false };
    if (params.gravity != null) { const g = gravFrom(params.gravity); if (g) c.gravities = [g]; }
    for (const m of asList(params.material)) c.materials = uniq(c.materials.concat(MATERIALS[m] ? [m] : matsFrom(norm(m))));
    if (params.o2 != null) { const o2 = parseFloat(params.o2); c.o2 = o2 <= 1 ? o2 * 100 : o2; }
    if (params.pressure_kpa != null) c.pressure_kpa = parseFloat(params.pressure_kpa);
    else if (params.pressure_psi != null) c.pressure_kpa = parseFloat(params.pressure_psi) * 6.894757;
    const v = params.ventilation;
    if (v === "none" || v === 0) c.ventilation = "none";
    else if (v === "forced" || (typeof v === "number" && v > 0)) c.ventilation = "forced";
    if (params.flow_cm_s != null) c.ventilation = parseFloat(params.flow_cm_s) > 0 ? "forced" : "none";
    c.ignitions = uniq(c.ignitions.concat(asList(params.ignition)));
    c.topics = uniq(c.topics.concat(asList(params.topic)));
    if (c.materials.includes("battery")) c.ignitions = uniq(c.ignitions.concat(["battery"]));
    if (c.materials.includes("electrical")) c.ignitions = uniq(c.ignitions.concat(["electrical"]));
    if (!c.gravities.length) { c.gravities = [defaultGravity]; c.assumed_gravity = true; }
    return c;
  }

  function matches(w, c) {
    const anyOf = (wanted, have) => wanted.some((x) => have.includes(x));
    if (w.gravity && !anyOf(w.gravity, c.gravities)) return false;
    if (w.material && !anyOf(w.material, c.materials)) return false;
    if (w.ignition && !anyOf(w.ignition, c.ignitions)) return false;
    if (w.topic && !anyOf(w.topic, c.topics)) return false;
    if ("o2_min" in w && (c.o2 == null || c.o2 < w.o2_min)) return false;
    if ("o2_max" in w && (c.o2 == null || c.o2 > w.o2_max)) return false;
    if ("pressure_max_kpa" in w && (c.pressure_kpa == null || c.pressure_kpa > w.pressure_max_kpa)) return false;
    if (w.ventilation && (c.ventilation == null || !w.ventilation.includes(c.ventilation))) return false;
    return true;
  }
  const srcs = (ids) => uniq(asList(ids)).filter((i) => SOURCES[i]).map((i) => Object.assign({}, SOURCES[i], { id: i }));

  function advise(params, text, eventType, defaultGravity, experiment, maxHazards = 4) {
    const c = buildContext(params, text, defaultGravity);
    const score = (r) => LEVELS[r.level] * 10 + Object.keys(r.when).length * 2;
    let hit = RULES.map((r, i) => [r, i]).filter(([r]) => matches(r.when, c))
      .sort((a, b) => (score(b[0]) - score(a[0])) || (a[1] - b[1])).slice(0, maxHazards).map(([r]) => r);
    if (!hit.length) hit = [Object.assign({ id: "fallback", level: "info" }, { title: FALLBACK.title, short: FALLBACK.short || "", why: FALLBACK.why || [], actions: FALLBACK.actions || [], sources: FALLBACK.sources || [] })];
    const lvl = hit.map((r) => r.level).reduce((a, b) => (LEVELS[b] > LEVELS[a] ? b : a));
    const regime = c.gravities[0], fr = FIRE[regime] || FIRE.micro || { label: "", steps: [], sources: [] };
    const classes = uniq(c.materials.map((m) => (MATERIALS[m] || {}).cls).filter(Boolean)
      .concat(c.ignitions.includes("electrical") ? ["C"] : []).concat(c.ignitions.includes("battery") ? ["battery"] : []));
    const top = hit[0], short = String(top.short || "");
    return {
      id: nextId++, timestamp: Date.now() / 1000, event_type: eventType, level: lvl, signal: SIGNAL[lvl],
      headline: top.title, summary: short ? short[0].toUpperCase() + short.slice(1) : "",
      hazards: hit.map((r) => ({ id: r.id, level: r.level, title: r.title, summary: r.short, why: r.why, actions: r.actions, sources: srcs(r.sources) })),
      actions: uniq(hit.flatMap((r) => r.actions || [])).slice(0, 6),
      if_fire: { regime, label: fr.label, steps: fr.steps, class_notes: classes.filter((x) => CLASS_NOTES[x]).map((x) => CLASS_NOTES[x]), sources: srcs(fr.sources) },
      sources: srcs(hit.flatMap((r) => r.sources || []).concat((experiment || {}).sources || [])),
      context: { gravity: regime, gravities: c.gravities, materials: c.materials, ignitions: c.ignitions, o2_percent: c.o2, pressure_kpa: c.pressure_kpa, ventilation: c.ventilation, topics: c.topics },
      assumed_gravity: c.assumed_gravity,
      experiment: experiment ? { name: experiment.name, note: experiment.note } : null,
      repeat: false, disclaimer: DISCLAIMER,
    };
  }

  // Agent layer (agent.py): event types + repeat detection while sliders move.
  function observe(payload, defaultGravity = "micro", dedupeSeconds = 8) {
    const p = Object.assign({}, payload || {}); const type = p.type || "manual"; delete p.type;
    let a;
    if (type === "question") a = advise(null, `${p.question || ""} . ${p.answer || ""}`, type, defaultGravity);
    else if (type === "experiment") {
      const id = String(p.experiment || p.id || ""); delete p.experiment; delete p.id;
      const exp = EXPERIMENTS[id.toLowerCase()];
      a = exp ? advise(Object.assign({}, exp.ctx || {}, p), "", type, defaultGravity, exp) : advise(p, id, type, defaultGravity);
    } else a = advise(p, "", type, defaultGravity);
    const sig = a.hazards.map((h) => h.id).concat([a.context.gravity]).join("|"), now = Date.now() / 1000, prev = lastSig[type];
    a.repeat = !!prev && prev.sig === sig && now - prev.t < dedupeSeconds;
    lastSig[type] = { t: now, sig };
    return a;
  }

  window.FlammyEngine = { observe, advise, extract };
})();
