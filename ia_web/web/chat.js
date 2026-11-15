// Chat de la IA de voz y texto (pantalla inicial de FLAMA).
// Protocolo: ia_web/servidor_web.py (voz/ + citas). Audio: referencia del README de voz/.
(function () {
  "use strict";
  const CFG = window.FLAMA_IA || { puerto: 8001 };
  const host = (() => { try { return window.parent.location.hostname || "localhost"; } catch (e) { return location.hostname || "localhost"; } })();
  const BASE_HTTP = `http://${host}:${CFG.puerto}`;
  const URL_WS = `ws://${host}:${CFG.puerto}/ws/voz`;
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
      mostrarError(`Cannot reach the AI at ${URL_WS}. Start the server: <code>voz\\.venv\\Scripts\\python -m uvicorn ia_web.servidor_web:app --port ${CFG.puerto}</code>`, true);
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
      enviar({ tipo: "texto", texto });
    },
    alternarMicro() { escuchando ? pararMicro(false) : empezarMicro(); },
    get escuchando() { return escuchando; },
  };

  $("ia-silencio").addEventListener("click", () => {
    silenciada = !silenciada;
    $("ia-silencio").setAttribute("aria-pressed", String(silenciada));
    $("ia-silencio-txt").textContent = silenciada ? "Voice muted · text only" : "Voice on";
    if (silenciada) vaciarAudio();
  });
  $("ia-reconectar").addEventListener("click", reconectar);
  $("ia-limpiar").addEventListener("click", () => {
    lista.innerHTML = ""; turnos.clear(); turnoActual = null; burbujaUsuario = null; $("ia-limpiar").hidden = true;
    reconectar();  // nueva sesión = nueva conversación
  });
  lista.addEventListener("click", (e) => {
    const a = e.target.closest(".ia-cita-abrir");
    if (a) {
      let columnas = [];
      try { columnas = JSON.parse(a.dataset.columnas || "[]"); } catch (err) {}
      window.dispatchEvent(new CustomEvent("flama:abrir-archivo", { detail: { archivo: a.dataset.archivo, columnas, extracto: a.dataset.extracto || "" } }));
    }
  });

  // Estado inicial sin abrir sesión (abrir el WebSocket ya inicia una sesión de Gemini)
  fetch(`${BASE_HTTP}/ia/modo`).then((r) => r.json()).then((m) => {
    modoSimulado = !!m.simulado; $("ia-modo").hidden = !modoSimulado;
    estado("desconectada", modoSimulado ? "AI ready (simulated) · type a scenario" : "AI ready · type or press the mic");
  }).catch(() => estado("desconectada", "AI server offline"));
})();
