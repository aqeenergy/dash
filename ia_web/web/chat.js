// Chat de la IA de voz y texto (pantalla inicial de FLAMA).
// Protocolo: ia_web/servidor_web.py (voz/ + citas). Audio: referencia del README de voz/.
(function () {
  "use strict";
  const CFG = window.FLAMA_IA || { puerto: 8001 };
  const host = (() => { try { return window.parent.location.hostname || "localhost"; } catch (e) { return location.hostname || "localhost"; } })();
  // FLAMA_IA_URL (a deployed AI server) wins; otherwise the local server on this machine.
  const LOCAL = /^(localhost|127\.|\[::1\]|$)/.test(host);
  const BASE_HTTP = CFG.base ? String(CFG.base).replace(/\/+$/, "") : `http://${host}:${CFG.puerto}`;
  const URL_WS = BASE_HTTP.replace(/^http/, "ws") + "/ws/voz";
  const DEPLOYED = !!CFG.base || LOCAL;
  const $ = (id) => document.getElementById(id);
  const lista = $("ia-mensajes");
  const ESTADOS = { desconectada: "AI not connected", conectando: "Connecting to the AI…", conectada: "AI connected", escuchando: "Listening…", pausa: "AI paused · resumes when you speak or type", error: "AI disconnected" };

  let ws = null, listo = false, cola = [], silenciada = false, modoSimulado = false;
  let ctxOut = null, siguiente = 0, fuentes = [];
  let ctxMic = null, micro = null, nodoMic = null, escuchando = false;
  const turnos = new Map();      // turno -> {el, texto, citas, consultando, n}
  let burbujaUsuario = null;     // transcripción de voz en curso
  let turnoActual = null;        // último turno de la IA visto
  let esperandoRespuesta = false; // hay una pregunta sin respuesta todavía

  // ---------------------------------------------------------------- utilidades
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));  // safe in text AND attributes
  function estado(e, txt) { const el = $("ia-estado"); el.dataset.estado = e === "pausa" ? "conectada" : e; $("ia-estado-txt").textContent = txt || ESTADOS[e] || e; }
  function bajar() { lista.scrollTop = lista.scrollHeight; if (window.frameElement) { const h = document.body.scrollHeight; if (h > 200) window.frameElement.style.height = (h + 20) + "px"; } }
  function nodo(clase, html) { const d = document.createElement("div"); d.className = clase; d.innerHTML = html; lista.appendChild(d); bajar(); return d; }

  function mensajeUsuario(texto) {
    const el = nodo("ia-msg ia-msg-usuario", `<span class="ia-quien">You</span><div class="ia-texto"></div>`);
    el.querySelector(".ia-texto").textContent = texto || "";
    $("ia-limpiar").hidden = false;
    return el;
  }
  function turno(n) {
    if (n == null) n = turnoActual != null ? turnoActual : 0;
    if (!turnos.has(n)) {
      const el = nodo("ia-msg ia-msg-ia", `<span class="ia-quien">${esc(CFG.nombre || "Llama")} · AI</span><div class="ia-texto"></div>
        <div class="ia-consultando" hidden>🔎 Checking the data…</div><div class="ia-pie"></div>`);
      turnos.set(n, { el, texto: "", citas: [], abiertas: 0, cerrado: false });
      burbujaUsuario = null; esperandoRespuesta = false;
    }
    turnoActual = n;
    return turnos.get(n);
  }

  // ---------------------------------------------------------------- citas
  function htmlCita(c, id) {
    const cab = `${esc(c.investigacion || "Document")}${c.accesion ? " · " + esc(c.accesion) : ""}`;
    // DOI shown as an identifier only: the citation opens the LOCAL database file, not a NASA web page
    const doi = c.doi ? `<div class="ia-cita-dato"><b>DOI:</b> ${esc(c.doi)}</div>` : "";
    const abrir = c.archivo ? `<div><button class="ia-cita-abrir" type="button" data-archivo="${esc(c.archivo)}"
        data-columnas="${esc(JSON.stringify(c.columnas || []))}" data-extracto="${esc(c.extracto || "")}">${c.tipo === "tabla" ? "Preview this table in the database library" : "Preview this record in the database library"}</button></div>` : "";
    const ver = abrir;
    let det = "";
    if (c.tipo === "tabla") {
      det = `<div class="ia-cita-dato"><b>Table:</b> ${esc(c.tabla)}</div>
             <div class="ia-cita-dato"><b>Query:</b> ${esc(c.consulta)} · <b>${esc(c.filas)}</b> tests</div>`;
    } else {
      const pag = c.pagina != null ? ` · p. ${esc(c.pagina)}` : "";
      det = `<div class="ia-cita-dato"><b>Source:</b> ${esc(c.fuente)}${pag}</div>
             <details><summary>Show the passage consulted</summary><p>${esc(c.extracto)}</p></details>`;
    }
    return `<div class="ia-cita"><span class="ia-cita-n">[${id}]</span>
      <div class="ia-cita-cab">${cab}<span class="ia-tipo">${c.tipo === "tabla" ? "test table" : "document"}</span></div>
      ${c.titulo ? `<div class="ia-cita-tit">${esc(c.titulo)}</div>` : ""}${doi}${det}${ver}</div>`;
  }
  function pintarPie(t, interrumpido) {
    const pie = t.el.querySelector(".ia-pie");
    let html = "";
    if (t.citas.length) {
      html += `<div class="ia-citas"><span class="ia-citas-titulo">Data consulted for this answer</span>${t.citas.sort((a, b) => a.id - b.id).map((x) => htmlCita(x.cita, x.id)).join("")}</div>`;
    }
    if (interrumpido) html += `<span class="ia-etiqueta interrumpida">Answer interrupted</span>`;
    else if (t.cerrado && !t.citas.length) html += `<span class="ia-etiqueta">General explanation · no data consulted</span>`;
    pie.innerHTML = html;
    bajar();
  }

  // ---------------------------------------------------------------- audio de salida (24 kHz)
  function asegurarAltavoz() {
    if (!ctxOut) ctxOut = new AudioContext({ sampleRate: 24000 });
    if (ctxOut.state === "suspended") ctxOut.resume();
  }
  function vaciarAudio() { fuentes.forEach((s) => { try { s.stop(); } catch (e) {} }); fuentes = []; siguiente = 0; }
  function reproducir(data) {
    if (silenciada || !ctxOut) return;
    const i16 = new Int16Array(data), f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;
    const buf = ctxOut.createBuffer(1, f32.length, 24000); buf.copyToChannel(f32, 0);
    const src = ctxOut.createBufferSource(); src.buffer = buf; src.connect(ctxOut.destination);
    siguiente = Math.max(siguiente, ctxOut.currentTime); src.start(siguiente);
    siguiente += buf.duration; fuentes.push(src);
    src.onended = () => (fuentes = fuentes.filter((s) => s !== src));
  }

  // ---------------------------------------------------------------- conexión
  function conectar() {
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    if (!DEPLOYED) return;  // public site without an AI server: database mode (see below), nothing to connect
    listo = false; estado("conectando");
    $("ia-reconectar").hidden = true;
    ws = new WebSocket(URL_WS);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (e) => (e.data instanceof ArrayBuffer ? reproducir(e.data) : alEvento(JSON.parse(e.data)));
    ws.onclose = () => {
      listo = false;
      if (escuchando) pararMicro(true);
      if ($("ia-estado").dataset.estado !== "error") estado("desconectada");
    };
    ws.onerror = () => {
      mostrarError(LOCAL
        ? `Cannot reach the AI at ${URL_WS}. Start the server: <code>voz\\.venv\\Scripts\\python -m uvicorn ia_web.servidor_web:app --port ${CFG.puerto}</code>`
        : `Cannot reach the AI server at ${esc(BASE_HTTP)}. It may be waking up: press Reconnect in a minute.`, true);
    };
  }
  function enviar(obj) {
    const msg = typeof obj === "string" ? obj : JSON.stringify(obj);
    if (ws && ws.readyState === 1 && listo) ws.send(msg); else { cola.push(msg); conectar(); }
  }
  function mostrarError(html, esHtml) {
    estado("error");
    const el = nodo("ia-error", `<span>${esHtml ? html : esc(html)}</span>`);
    const b = document.createElement("button"); b.className = "ia-mini"; b.type = "button"; b.textContent = "Reconnect";
    b.addEventListener("click", reconectar); el.appendChild(b);
    $("ia-reconectar").hidden = false;
  }
  function reconectar() { try { ws && ws.close(); } catch (e) {} ws = null; conectar(); }

  // ---------------------------------------------------------------- eventos de la IA
  function alEvento(ev) {
    switch (ev.tipo) {
      case "listo":
        listo = true; estado(escuchando ? "escuchando" : "conectada");
        while (cola.length && ws.readyState === 1) ws.send(cola.shift());
        break;
      case "transcripcion_usuario":
        if (!burbujaUsuario) burbujaUsuario = mensajeUsuario("");
        burbujaUsuario.querySelector(".ia-texto").textContent += ev.texto;
        burbujaUsuario._texto = (burbujaUsuario._texto || "") + ev.texto;
        bajar();
        break;
      case "transcripcion_ia": {
        const t = turno(ev.turno);
        t.texto += ev.texto;  // pensada para voz: se muestra tal cual, sin "corregir"
        t.el.querySelector(".ia-texto").textContent = t.texto;
        bajar();
        break;
      }
      case "herramienta": {
        const t = turno(ev.turno); t.abiertas++;
        t.el.querySelector(".ia-consultando").hidden = false; bajar();
        break;
      }
      case "resultado_herramienta": {
        const t = turno(ev.turno); t.abiertas = Math.max(0, t.abiertas - 1);
        if (!t.abiertas) t.el.querySelector(".ia-consultando").hidden = true;
        break;
      }
      case "cita": {
        const t = turno(ev.turno);
        if (!t.citas.some((x) => x.id === ev.id)) t.citas.push({ id: ev.id, cita: ev.cita });
        pintarPie(t, false);
        break;
      }
      case "interrumpido": {
        vaciarAudio();
        const t = turnos.get(ev.turno); if (t) { t.cerrado = true; t.interrumpido = true; t.el.querySelector(".ia-consultando").hidden = true; pintarPie(t, true); }
        break;
      }
      case "turno_completo": {
        let t = turnos.get(ev.turno);
        if (!t && (burbujaUsuario || esperandoRespuesta)) t = turno(ev.turno);  // respuesta vacía tras una pregunta
        if (t) {
          t.cerrado = true; t.el.querySelector(".ia-consultando").hidden = true;
          pintarPie(t, !!t.interrumpido);
          // Flammy mantiene sus recomendaciones sobre la pregunta (voz o texto) y la respuesta
          const pregunta = t.pregunta || (t.el.previousElementSibling && t.el.previousElementSibling.classList.contains("ia-msg-usuario")
            ? t.el.previousElementSibling.querySelector(".ia-texto").textContent : "");
          if (pregunta && !t.avisadoFlammy) {
            t.avisadoFlammy = true;
            window.dispatchEvent(new CustomEvent("flama:pregunta", { detail: { pregunta, respuesta: t.texto, citas: t.citas.map((x) => x.cita) } }));
          }
        }
        break;
      }
      case "aviso": nodo("ia-aviso", esc(ev.mensaje)); break;
      case "en_pausa": estado("pausa"); break;
      case "reconectando": estado("conectando", "Reconnecting to the AI…"); break;
      case "error": mostrarError(ev.mensaje); break;
      default: break;  // diagnostico, fuentes: no se muestran
    }
  }

  // ---------------------------------------------------------------- micrófono (16 kHz, trozos de 40 ms)
  async function empezarMicro() {
    asegurarAltavoz();
    conectar();
    try {
      ctxMic = new AudioContext({ sampleRate: 16000 });
      await ctxMic.audioWorklet.addModule(URL.createObjectURL(new Blob([`
        class Pcm extends AudioWorkletProcessor {
          constructor() { super(); this.buf = new Int16Array(640); this.n = 0; }
          process([entrada]) {
            const c = entrada[0]; if (!c) return true;
            for (let i = 0; i < c.length; i++) {
              this.buf[this.n++] = Math.max(-1, Math.min(1, c[i])) * 0x7fff;
              if (this.n === this.buf.length) {
                this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
                this.buf = new Int16Array(640); this.n = 0;
              }
            }
            return true;
          }
        }
        registerProcessor("pcm", Pcm);`], { type: "application/javascript" })));
      micro = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      nodoMic = new AudioWorkletNode(ctxMic, "pcm");
      nodoMic.port.onmessage = (e) => { if (ws && ws.readyState === 1 && listo) ws.send(e.data); };
      ctxMic.createMediaStreamSource(micro).connect(nodoMic);
      escuchando = true;
      estado("escuchando");
      document.getElementById("hub-voice-btn")?.classList.add("ia-escuchando", "recording");
    } catch (err) {
      pararMicro(true);
      const motivo = err && err.name === "NotAllowedError" ? "The browser blocked the microphone. Allow access (padlock icon) and press the mic again."
        : err && /sampleRate|sample-rate|NotSupported/i.test(String(err)) ? "This browser cannot record at 16 kHz: use Chrome or Edge."
        : `Could not open the microphone: ${err && err.message ? err.message : err}`;
      nodo("ia-error", `<span>${esc(motivo)}</span>`);
    }
  }
  function pararMicro(silencioso) {
    try { micro && micro.getTracks().forEach((t) => t.stop()); } catch (e) {}
    try { ctxMic && ctxMic.close(); } catch (e) {}
    micro = ctxMic = nodoMic = null;
    if (escuchando && !silencioso && ws && ws.readyState === 1) ws.send(JSON.stringify({ tipo: "fin_audio" }));
    escuchando = false;
    document.getElementById("hub-voice-btn")?.classList.remove("ia-escuchando", "recording");
    if (listo) estado("conectada");
  }

  // ---------------------------------------------------------------- API pública
  window.flamaChat = {
    preguntar(texto) {
      texto = (texto || "").trim(); if (!texto) return;
      asegurarAltavoz();
      mensajeUsuario(texto);
      burbujaUsuario = null; esperandoRespuesta = true;
      if (!DEPLOYED) { BaseDatos.responder(texto); return; }
      enviar({ tipo: "texto", texto });
    },
    alternarMicro() { if (!DEPLOYED) return BaseDatos.dictado(); escuchando ? pararMicro(false) : empezarMicro(); },
    get escuchando() { return escuchando; },
  };

  $("ia-silencio").addEventListener("click", () => {
    silenciada = !silenciada;
    $("ia-silencio").setAttribute("aria-pressed", String(silenciada));
    $("ia-silencio-txt").textContent = silenciada ? "Voice muted · text only" : "Voice on";
    if (silenciada) { vaciarAudio(); try { speechSynthesis.cancel(); } catch (e) {} }
  });
  $("ia-reconectar").addEventListener("click", reconectar);
  $("ia-limpiar").addEventListener("click", () => {
    lista.innerHTML = ""; turnos.clear(); turnoActual = null; burbujaUsuario = null; $("ia-limpiar").hidden = true;
    if (DEPLOYED) reconectar();  // nueva sesión = nueva conversación
  });
  lista.addEventListener("click", (e) => {
    const a = e.target.closest(".ia-cita-abrir");
    if (a) {
      let columnas = [];
      try { columnas = JSON.parse(a.dataset.columnas || "[]"); } catch (err) {}
      window.dispatchEvent(new CustomEvent("flama:abrir-archivo", { detail: { archivo: a.dataset.archivo, columnas, extracto: a.dataset.extracto || "" } }));
    }
  });

  // ================================================================ DATABASE MODE (public site, no LLM)
  // Without an AI server (e.g. flama-nasa.streamlit.app) the chat answers ONLY from the text library of
  // base_de_datos/ (static/library/search.json + the tables' CSV): it ranks the records' passages, quotes
  // them verbatim, computes ranges from the exact experimental tables and cites every file it used.
  // Nothing is generated or invented; if the files do not cover the question it says so.
  const BaseDatos = (() => {
    const RAIZ = "app/static/library/";
    let docs = null, pasajes = null, df = null, N = 0, avgLen = 1, cargando = null;
    const STOP = new Set(("a an the of and or in on at to for from by with without is are was were be been what which who how why when where " +
      "does do did can could would should will it its this that these those there about into than then as if not no any some " +
      "me my we our you your i el la los las un una unos unas de del al y o en con sin por para que qué cual cuál como cómo " +
      "es son fue ser se lo le les su sus mi mis tu hay más menos muy sobre entre cuando donde dónde porque pasa pasaría ocurre " +
      "tell explain show give data dime explica cuéntame dato datos").split(" "));
    const SIN = { fuego: "fire", incendio: "fire", incendios: "fire", llama: "flame", llamas: "flame", oxigeno: "oxygen",
      extincion: "extinction", extinguir: "extinction", apagar: "extinction", apaga: "extinction", apagan: "extinction",
      extingue: "extinction", extinguish: "extinction", extinguished: "extinction", extinguishment: "extinction", extinguishing: "extinction", extintor: "suppressant", supresion: "suppression",
      hollin: "soot", gota: "droplet", gotas: "droplet", combustible: "fuel", presion: "pressure", gravedad: "gravity",
      microgravedad: "microgravity", luna: "lunar", lunar: "lunar", marte: "mars", materiales: "material", propagacion: "spread",
      velocidad: "velocity", temperatura: "temperature", humo: "smoke", ventilacion: "ventilation", flujo: "flow",
      algodon: "cotton", tela: "fabric", tejido: "fabric", plastico: "plastic", ignicion: "ignition", inflamabilidad: "flammability",
      nave: "spacecraft", estacion: "station", radiacion: "radiation", quemar: "burn", arde: "burn", combustion: "combustion",
      nitrogeno: "nitrogen", helio: "helium", aire: "air", espesor: "thickness", grosor: "thickness", tasa: "rate",
      o2: "oxygen", xo2: "oxygen", mo2: "oxygen", n2: "nitrogen", he: "helium", sf6: "sf6",
      deteccion: "detection", detector: "detection", sensor: "sensor", vela: "candle", metano: "methane", etileno: "ethylene" };
    const raiz = (w) => { w = SIN[w] || w; if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
      if (w.length > 4 && w.endsWith("s") && !w.endsWith("ss")) return w.slice(0, -1); return w; };
    const GENERICO = new Set(["flame", "fire", "combustion", "microgravity", "test", "type", "sample", "data", "experiment",
      "time", "date", "day", "number", "investigation", "psi", "space", "study", "effect", "affect", "result", "nasa"]);
    const tokens = (t) => String(t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
      .split(/[^a-z0-9]+/).filter((w) => w && (w.length > 1 || /\d/.test(w)) && !STOP.has(w)).map(raiz);

    function cargar() {
      if (cargando) return cargando;
      cargando = fetch(RAIZ + "search.json").then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then((j) => {
        docs = j.docs; pasajes = []; df = new Map();
        for (const d of docs) {
          if (!d.passages) continue;
          const cab = tokens(`${d.inv} ${d.acc} ${d.title}`);
          d.passages.forEach(([sec, txt], i) => {
            const tk = tokens(txt).concat(tokens(sec));
            const tf = new Map(); tk.forEach((w) => tf.set(w, (tf.get(w) || 0) + 1));
            pasajes.push({ d, sec, txt, tf, len: tk.length || 1, cab: new Set(cab), i });
            new Set(tk).forEach((w) => df.set(w, (df.get(w) || 0) + 1));
          });
        }
        N = pasajes.length; avgLen = pasajes.reduce((a, p) => a + p.len, 0) / Math.max(1, N);
      });
      return cargando;
    }

    function buscar(pregunta) {
      const q = [...new Set(tokens(pregunta))];
      const acc = (pregunta.match(/psi[\s-]?(\d+)/i) || [])[1];
      const k1 = 1.4, b = 0.75;
      const res = [];
      for (const p of pasajes) {
        let s = 0;
        for (const w of q) {
          const f = p.tf.get(w); const n = df.get(w) || 0;
          const idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
          if (f) s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * p.len / avgLen));
          if (p.cab.has(w)) s += idf * 0.8;   // the question names this investigation (FLEX, SAFFIRE, …)
        }
        if (acc && p.d.acc === "PSI-" + acc) s += 6;
        if (p.sec === "Objective" || /result|finding|conclusion|summary|description/i.test(p.sec)) s *= 1.15;
        if (/^[A-Z][A-Za-z /()-]{2,40}: /.test(p.txt) && p.txt.length < 200) s *= 0.25;   // metadata line
        if (/^Publications/i.test(p.sec)) s *= 0.4;
        if (s > 0) res.push({ p, s });
      }
      res.sort((a, b2) => b2.s - a.s);
      return { q, res };
    }

    // the most relevant sentences of a passage (verbatim), so a long abstract is quoted, not dumped
    function extracto(txt, q) {
      const frases = txt.match(/[^.!?]+[.!?]+(\s|$)|[^.!?]+$/g) || [txt];
      if (txt.length <= 420) return txt.trim();
      const pun = frases.map((f, i) => ({ i, f, s: tokens(f).filter((w) => q.includes(w)).length }));
      const mejor = pun.slice().sort((a, b) => b.s - a.s || a.i - b.i).slice(0, 2).sort((a, b) => a.i - b.i);
      return mejor.map((m) => m.f.trim()).join(" … ");
    }

    function csv(texto) {
      const filas = []; let fila = [], campo = "", comillas = false;
      for (let i = 0; i < texto.length; i++) {
        const c = texto[i];
        if (comillas) { if (c === '"') { if (texto[i + 1] === '"') { campo += '"'; i++; } else comillas = false; } else campo += c; }
        else if (c === '"') comillas = true;
        else if (c === ",") { fila.push(campo); campo = ""; }
        else if (c === "\n" || c === "\r") { if (c === "\r" && texto[i + 1] === "\n") i++; fila.push(campo); filas.push(fila); fila = []; campo = ""; }
        else campo += c;
      }
      if (campo || fila.length) { fila.push(campo); filas.push(fila); }
      return filas.filter((f) => f.some((x) => x.trim()));
    }
    const fmt = (x) => Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) >= 1 ? (+x.toFixed(2)).toString() : (+x.toPrecision(2)).toString();

    async function tablas(q, accs) {
      const util = q.filter((w) => !GENERICO.has(w));
      const cand = docs.filter((d) => d.cols && d.kind === "table").map((d) => {
        const propio = new Set(tokens(d.inv));   // "FLEX" must not match the column "FLEX Test #"
        const enc = d.cols.map((c, i) => ({ c, i, s: tokens(c).filter((w) => util.includes(w) && !propio.has(w)).length }))
          .filter((x) => x.s > 0 && !/#|identifier|id/i.test(x.c));
        const s = enc.reduce((a, x) => a + 2 * x.s, 0) + (accs.includes(d.acc) ? 3 : 0);
        return { d, enc, s };
      }).filter((x) => x.s >= 3).sort((a, b) => b.s - a.s).slice(0, 4);
      const out = [];
      for (const { d, enc } of cand) {
        if (out.length >= 2) break;
        try {
          const filas = csv(await (await fetch(RAIZ + d.id)).text());
          const cab = filas[0] || []; let datos = filas.slice(1);
          // rows whose text values name what was asked (e.g. Material = Cotton): the query is applied to the table
          let filtro = "";
          const enCabecera = new Set(cab.flatMap((c) => tokens(c)));
          const valores = util.filter((w) => !enCabecera.has(w));   // words that name a value, not a column
          for (let i = 0; i < cab.length && !filtro; i++) {
            if (/#|identifier|notes?|comments?|date|gmt|camera|pi/i.test(cab[i])) continue;
            const vals = datos.map((f) => String(f[i] || ""));
            if (vals.filter((v) => isFinite(parseFloat(v))).length > vals.length / 2) continue;
            for (const w of valores) {
              const sel = datos.filter((f) => tokens(f[i]).includes(w));
              if (sel.length && sel.length < datos.length) { datos = sel; filtro = `${cab[i].trim()} contains “${w}”`; break; }
            }
          }
          const resumen = [];
          for (const { c, i } of enc.slice(0, 3)) {
            const nums = datos.map((f) => parseFloat(String(f[i] || "").replace(",", "."))).filter((x) => isFinite(x)).sort((a, b) => a - b);
            if (nums.length >= 2) resumen.push(`${c.trim()}: ${fmt(nums[0])} – ${fmt(nums[nums.length - 1])} (median ${fmt(nums[Math.floor(nums.length / 2)])}, ${nums.length} tests)`);
            else {
              const vals = {}; datos.forEach((f) => { const v = (f[i] || "").trim(); if (v) vals[v] = (vals[v] || 0) + 1; });
              const top = Object.entries(vals).sort((a, b) => b[1] - a[1]).slice(0, 4);
              if (top.length > 1 || (top.length && filtro)) resumen.push(`${c.trim()}: ${top.map(([v, n]) => `${v} (${n})`).join(", ")}`);
            }
          }
          if (!resumen.length) continue;
          out.push({ d, filas: datos.length, filtro, columnas: enc.slice(0, 3).map((x) => x.c.trim()), resumen });
        } catch (e) { /* table not reachable: skip it rather than guess */ }
      }
      return out;
    }

    async function responder(pregunta) {
      const n = (turnoActual != null ? turnoActual : 0) + 1;
      const t = turno(n);
      t.pregunta = pregunta;
      t.el.querySelector(".ia-consultando").hidden = false;
      try { await cargar(); } catch (e) {
        t.el.querySelector(".ia-texto").textContent = "The database library could not be loaded on this site. Reload the page and try again.";
        t.cerrado = true; t.el.querySelector(".ia-consultando").hidden = true; pintarPie(t, false); return;
      }
      const { q, res } = buscar(pregunta);
      // rank investigations by their best passages (not by one lucky line); an exact acronym in the question wins
      const qn = " " + tokens(pregunta).join(" ") + " ";
      const porInv = new Map();
      for (const r of res) { const k = r.p.d.id; if (!porInv.has(k)) porInv.set(k, []); const l = porInv.get(k); if (l.length < 3) l.push(r); }
      const ranking = [...porInv.values()].map((l) => {
        const d = l[0].p.d, inv = tokens(d.inv).join(" ");
        let s = l.reduce((a, r) => a + r.s, 0);
        if (inv && qn.includes(" " + inv + " ")) s *= 2.5;
        return { d, l, s };
      }).sort((a, b) => b.s - a.s);
      const elegidos = [], vistos = new Set();
      for (const [j, g] of ranking.slice(0, 3).entries()) {
        if (j && g.s < ranking[0].s * 0.3) break;
        for (const r of g.l.slice(0, j ? 1 : 2)) {
          if (elegidos.length >= 4 || vistos.has(r.p.txt)) continue;
          vistos.add(r.p.txt); elegidos.push(r);
        }
      }
      const accs = [...new Set(elegidos.map((r) => r.p.d.acc))];
      const tabs = elegidos.length ? await tablas(q, accs) : [];
      let html = "", hablar = "", id = 0;
      t.citas = [];
      if (!elegidos.length) {
        html = "I could not find this in the database files. Try naming a material, gas, fuel, gravity level or an experiment (for example FLEX, SAFFIRE, BASS, ACME).";
        hablar = html;
      } else {
        const d0 = elegidos[0].p.d;
        html = `<p>Closest investigation in the database: <b>${esc(d0.inv === d0.acc ? "" : d0.inv + " — ")}${esc(d0.title)} (${esc(d0.acc)})</b>.</p>`;
        hablar = `The closest investigation in the database is ${d0.inv}, ${d0.acc}. `;
        for (const r of elegidos) {
          const ex = extracto(r.p.txt, q); id++;
          html += `<p class="ia-bd-cita">“${esc(ex)}” <span class="ia-bd-ref">— ${esc(r.p.d.inv === r.p.d.acc ? r.p.d.acc : r.p.d.inv + " (" + r.p.d.acc + ")")}, ${esc(r.p.sec)} <b>[${id}]</b></span></p>`;
          if (id === 1) hablar += ex;
          t.citas.push({ id, cita: { tipo: "documento", investigacion: r.p.d.inv, accesion: r.p.d.acc, titulo: r.p.d.title,
            fuente: "base_de_datos/" + r.p.d.file + " · section “" + r.p.sec + "”", extracto: ex, archivo: r.p.d.id } });
        }
        for (const tb of tabs) {
          id++;
          html += `<p class="ia-bd-cita"><b>${esc(tb.d.label)}</b> (${esc(tb.d.acc)}) · ${tb.filas} tests${tb.filtro ? " where " + esc(tb.filtro) : ""}:</p>` +
            (tb.resumen.length ? `<ul class="ia-bd-lista">${tb.resumen.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "") +
            `<p class="ia-bd-ref">Computed from the table file <b>[${id}]</b></p>`;
          t.citas.push({ id, cita: { tipo: "tabla", investigacion: tb.d.inv, accesion: tb.d.acc, titulo: tb.d.title, tabla: tb.d.label,
            consulta: (tb.filtro ? "rows where " + tb.filtro + " · " : "all rows · ") + "columns " + tb.columnas.join(" · "), filas: tb.filas,
            columnas: tb.columnas, archivo: tb.d.id } });
        }
        html += `<p class="ia-bd-nota">Database mode: quoted verbatim from the base_de_datos files, no generative AI. Open each source below to check it.</p>`;
      }
      t.texto = hablar;
      t.el.querySelector(".ia-texto").innerHTML = html;
      t.cerrado = true; t.el.querySelector(".ia-consultando").hidden = true;
      pintarPie(t, false);
      if (!silenciada && "speechSynthesis" in window) {
        try { speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(hablar.slice(0, 400)); u.lang = "en-US"; speechSynthesis.speak(u); } catch (e) {}
      }
      window.dispatchEvent(new CustomEvent("flama:pregunta", { detail: { pregunta, respuesta: hablar, citas: t.citas.map((x) => x.cita) } }));
    }

    // voice input with the browser's own speech recognition (Chrome / Edge); no audio leaves to Gemini
    let rec = null;
    function dictado() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) { nodo("ia-error", "<span>Voice input needs Chrome or Edge on this site. You can type the question instead.</span>"); return; }
      if (rec) { try { rec.stop(); } catch (e) {} return; }
      rec = new SR(); rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
      const fin = () => { rec = null; escuchando = false; document.getElementById("hub-voice-btn")?.classList.remove("ia-escuchando", "recording"); estado("conectada", ESTADO_BD); };
      rec.onresult = (e) => { const txt = e.results[0][0].transcript; fin(); window.flamaChat.preguntar(txt); };
      rec.onerror = (e) => { fin(); if (e.error === "not-allowed") nodo("ia-error", "<span>The browser blocked the microphone. Allow access (padlock icon) and try again.</span>"); };
      rec.onend = () => { if (rec) fin(); };
      try { rec.start(); escuchando = true; estado("escuchando"); document.getElementById("hub-voice-btn")?.classList.add("ia-escuchando", "recording"); } catch (e) { fin(); }
    }
    return { responder, dictado, cargar };
  })();
  const ESTADO_BD = "AI connected";

  // Estado inicial sin abrir sesión (abrir el WebSocket ya inicia una sesión de Gemini)
  if (!DEPLOYED) {
    estado("conectada", ESTADO_BD);
    BaseDatos.cargar().catch(() => estado("error", "Database library not reachable"));
  } else
  fetch(`${BASE_HTTP}/ia/modo`).then((r) => r.json()).then((m) => {
    modoSimulado = !!m.simulado; $("ia-modo").hidden = !modoSimulado;
    estado("desconectada", modoSimulado ? "AI ready (simulated) · type a scenario" : "AI ready · type or press the mic");
  }).catch(() => estado("desconectada", "AI server offline"));
})();
