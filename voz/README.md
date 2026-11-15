# 🔥 IA de voz (carpeta `voz/`)

Asistente de voz en tiempo real, experta en combustión en microgravedad y seguridad contra incendios.
NASA Space Apps Challenge 2026, sede de Sevilla.

- **Voz:** Gemini Live API (`gemini-3.1-flash-live-preview`, plan gratuito). Se le puede interrumpir mientras habla.
- **Conocimiento:** los datos reales del NASA PSI que ya están en el repositorio (`datos_psi/`):
  - RAG sobre las 24 fichas de investigación (objetivos, enfoque, hipótesis, publicaciones, DOI),
    convertidas a Markdown en `voz/documentos/psi/`, más los PDF que añadáis a `voz/documentos/`.
  - Herramientas que consultan las 23 tablas experimentales (FLEX, BASS, Saffire, ACME, SAME, SPICE...):
    `listar_tablas`, `describir_tabla`, `consultar_tabla` y `estadisticas_tabla`.
- **Coste:** 0 € para desarrollar y probar (plan gratuito de Google AI Studio). Para una web pública
  con usuarios en la UE, las condiciones de Google exigen el plan de pago: ver la sección 4.

```
navegador (web)  ⇄  WebSocket /ws/voz  ⇄  servidor Python (este repo)  ⇄  Gemini Live
                    audio PCM + JSON        herramientas: documentos y tablas
```

La clave de API y los datos se quedan en el servidor; el navegador solo envía y recibe audio.

---

## 1. Puesta en marcha (unos 10 minutos)

Todo se ejecuta desde la carpeta `voz/`:

```bash
cd voz
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.ejemplo .env        # y pegad la clave de https://aistudio.google.com/apikey
```

1. (Ya hecho y subido) `python preparar_documentos.py` convierte las fichas `datos_psi/.../metadatos/PSI-*.json`
   en documentos para el RAG. Solo hay que repetirlo si se actualizan las fichas.
2. Construid el índice: `python ingestar.py` (debe decir `embeddings: sí`). Repetidlo si añadís PDFs a `voz/documentos/`.
   Conviene subir la carpeta `voz/indice/` al repositorio: así el servidor desplegado no tiene que regenerarla.
3. Comprobad los datos sin gastar cuota de voz: `python prueba_herramientas.py "limiting oxygen index"`
4. Hablad con la IA desde la terminal, con auriculares: `python prueba_terminal.py`
   (o `python prueba_terminal.py --texto` para escribir las preguntas).
   Con `--grabar` se guarda cada conversación en `voz/grabaciones/AAAAMMDD-HHMMSS/`: `conversacion.md`
   (cronología con consultas, resultados y latencias), `eventos.jsonl`, `microfono.wav`, `ia.wav` y
   `conversacion.wav` (las dos voces mezcladas y sincronizadas, para escuchar o compartir).
   Esa carpeta no se sube a GitHub.

Para comprobar que el código funciona sin clave: `python tests/test_simulado.py`, `python tests/test_errores.py`
y `python tests/test_optimizaciones.py`.

## 2. Integración con la web (para quien hace la web)

**Si la web es FastAPI:**

```python
from ia_llama.servidor import router
app.include_router(router)      # añade  ws://HOST/ws/voz  y  GET /ia/salud
```

**Si es otro framework (Flask, Django, Streamlit...):** levantad la IA como servicio aparte y
conectad el navegador a ese puerto:

```bash
uvicorn ia_llama.servidor:app --host 0.0.0.0 --port 8001
```

`GET /ia/salud` dice si la clave está configurada, cuántos fragmentos hay indexados y qué tablas se han cargado.

### Protocolo del WebSocket `/ws/voz`

| Dirección | Tipo | Contenido |
|---|---|---|
| web → IA | binario | Micro: PCM 16 bits, mono, **16 kHz**, little-endian (trozos de 20-100 ms) |
| web → IA | JSON | `{"tipo":"texto","texto":"..."}`: pregunta escrita |
| web → IA | JSON | `{"tipo":"fin_audio"}`: el micro se ha pausado más de 1 s |
| IA → web | binario | Voz de la IA: PCM 16 bits, mono, **24 kHz**, little-endian |
| IA → web | JSON | `listo` (`modelo`): conectada con Gemini |
| IA → web | JSON | `transcripcion_usuario` / `transcripcion_ia`: subtítulos (`texto`) |
| IA → web | JSON | `herramienta`: está consultando datos (`nombre`, `argumentos`); útil para mostrar "🔎 buscando..." |
| IA → web | JSON | `resultado_herramienta` (`nombre`, `resumen`): qué devolvió la consulta, recortado (para depurar; la web puede ignorarlo) |
| IA → web | JSON | `fuentes`: documentos usados (`fuente`, `pagina`) |
| IA → web | JSON | `interrumpido`: la persona habló encima; **hay que vaciar el audio pendiente** |
| IA → web | JSON | `aviso` (`mensaje`): algo pasa pero se resuelve solo (límite por minuto, modelo de reserva...). Mostradlo |
| IA → web | JSON | `diagnostico`: información técnica (p. ej. respuesta atascada). Queda en las grabaciones; la web puede ignorarlo |
| IA → web | JSON | `en_pausa`: Gemini cerró por inactividad (p. ej. nadie habla ni escribe); se reanuda sola, con la misma conversación, en cuanto llega audio o texto |
| IA → web | JSON | `turno_completo`, `reconectando`, `error` (`mensaje`): con `error` la sesión termina y hay que reconectar |

### Referencia JavaScript: micro a 16 kHz y altavoz a 24 kHz

Esto es solo la parte de audio; la interfaz es vuestra.

```js
const ws = new WebSocket(`ws://${location.hostname}:8001/ws/voz`);
ws.binaryType = "arraybuffer";

// --- Micro → PCM16 a 16 kHz
const ctxMic = new AudioContext({ sampleRate: 16000 });
await ctxMic.audioWorklet.addModule(URL.createObjectURL(new Blob([`
  class Pcm extends AudioWorkletProcessor {
    constructor() { super(); this.buf = new Int16Array(640); this.n = 0; } // 640 muestras = 40 ms
    process([entrada]) {
      const c = entrada[0]; if (!c) return true;
      for (let i = 0; i < c.length; i++) {
        this.buf[this.n++] = Math.max(-1, Math.min(1, c[i])) * 0x7fff;
        if (this.n === this.buf.length) {           // envía trozos de 40 ms, no de 8 ms:
          this.port.postMessage(this.buf.buffer, [this.buf.buffer]);  // 25 mensajes/s en vez de 125
          this.buf = new Int16Array(640); this.n = 0;
        }
      }
      return true;
    }
  }
  registerProcessor("pcm", Pcm);`], { type: "application/javascript" })));
const micro = await navigator.mediaDevices.getUserMedia({
  audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
const nodoMic = new AudioWorkletNode(ctxMic, "pcm");
nodoMic.port.onmessage = (e) => ws.readyState === 1 && ws.send(e.data);
ctxMic.createMediaStreamSource(micro).connect(nodoMic);

// --- Altavoz: PCM16 a 24 kHz, en cola y sin huecos
const ctxOut = new AudioContext({ sampleRate: 24000 });
let siguiente = 0, fuentes = [];
ws.onmessage = (e) => {
  if (e.data instanceof ArrayBuffer) {
    const i16 = new Int16Array(e.data), f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 0x8000;
    const buf = ctxOut.createBuffer(1, f32.length, 24000); buf.copyToChannel(f32, 0);
    const src = ctxOut.createBufferSource(); src.buffer = buf; src.connect(ctxOut.destination);
    siguiente = Math.max(siguiente, ctxOut.currentTime); src.start(siguiente);
    siguiente += buf.duration; fuentes.push(src);
    src.onended = () => (fuentes = fuentes.filter((s) => s !== src));
    return;
  }
  const ev = JSON.parse(e.data);
  if (ev.tipo === "interrumpido") { fuentes.forEach((s) => s.stop()); fuentes = []; siguiente = 0; }
  // ev.tipo === "transcripcion_ia" → subtítulos, "herramienta" → indicador, "fuentes" → referencias...
};
```

⚠️ Usad **Chrome** (o Edge): Firefox no permite conectar el micro a un `AudioContext` de 16 kHz.

⚠️ Los navegadores solo dan acceso al micro en `https://` o en `localhost`. Para la demo desde otro
dispositivo hace falta HTTPS (por ejemplo, con un túnel: `cloudflared tunnel --url http://localhost:8001`).

## 3. Qué tocar durante el hackathon

| Quiero... | Archivo |
|---|---|
| Cambiar la personalidad, el tono o las reglas de la IA | `ia_llama/prompt.py` |
| Cambiar la voz, el modelo o el nombre | `.env` (`VOZ`, `MODELO_LIVE`, `NOMBRE_ASISTENTE`) |
| Añadir una herramienta nueva | `ia_llama/herramientas.py`: declaración en `DECLARACIONES` y función en `FUNCIONES` |
| Ajustar el troceado de documentos | `.env` (`TAM_FRAGMENTO`, `SOLAPE_FRAGMENTO`) y volver a ejecutar `ingestar.py` |
| Explicar mejor una tabla (unidades, columnas) | Un `.md` con el mismo nombre junto a la tabla, en `datos_psi/.../tablas/PSI-XX/`; tiene prioridad sobre la ficha |
| Que la IA no lleve el catálogo de tablas en sus instrucciones | `.env` → `CATALOGO_EN_PROMPT=no` (más lento: tendrá que consultar `listar_tablas`) |
| Excluir tablas con cabeceras caóticas | `.env` (`EXCLUIR_TABLAS`, por defecto `Analyzed Data,As Run_Test Matrix`) |

## 4. Límites, errores y condiciones de uso

### Cómo reacciona a los errores de Gemini (`ia_llama/errores.py`)

| Error | Qué hace |
|---|---|
| Clave no válida (401/403) o región no admitida | Avisa con un `error` claro y no reintenta |
| Modelo inexistente o renombrado (404) | Pasa al siguiente modelo de `MODELO_LIVE` |
| Modelo saturado ("overloaded", "capacity", 503) | Pasa al modelo de reserva sin esperar; a los 10 min vuelve a probar el principal |
| Cuota diaria agotada | Prueba el siguiente modelo (las cuotas son por modelo); si se agotan todos, `error` |
| Límite por minuto (429) | Espera 2, 4, 8, 12, 16, 20, 30 y 40 s, avisando con `aviso` |
| Conexión caída | Reconecta (3, 6, 12, 20 s) recuperando la conversación |
| Respuesta atascada a mitad de frase (Gemini deja de enviar nada durante `SEGUNDOS_ATASCO`, 10 s) | Le da un toque (`TEXTO_TOQUE`) para que termine; si tras dos toques sigue parada, reconecta recuperando la conversación. Deja un evento `diagnostico` |
| Un error que se repite en cada conexión | Como mucho 4 reintentos y después `error`: nunca reconecta en bucle |

Para que nadie agote la cuota de todos: máximo `MAX_SESIONES_SIMULTANEAS` (3) a la vez,
`MAX_SESIONES_IP_HORA` (30) por IP y hora, y `MAX_MINUTOS_SESION` (15) por conversación.
Pruebas sin clave: `python tests/test_errores.py`.

### ⚠️ Condiciones de uso en la UE

Las condiciones de la Gemini API (actualizadas el 28-04-2026) dicen que, para ofrecer una app con Gemini
a usuarios del Espacio Económico Europeo, Suiza o el Reino Unido, solo se pueden usar los **servicios de pago**.
El plan gratuito vale para desarrollar y probar, pero una web pública para el jurado o los visitantes en España
necesita la facturación activada en AI Studio (con un presupuesto y alertas, el coste de una demo es muy bajo).
La alternativa sin este requisito es el plan B local (Ollama). Revisad los términos vigentes: https://ai.google.dev/gemini-api/terms

### Problemas típicos

- Google no publica los límites gratuitos: se ven en <https://aistudio.google.com/rate-limit>. Los límites
  son por proyecto, no por clave.
- Las peticiones del plan gratuito pueden usarse para mejorar productos de Google. Con datos públicos de la NASA no hay problema.
- **La IA se interrumpe sola:** el altavoz se cuela por el micro. Usad auriculares o `echoCancellation: true`.
- **Error 429 / RESOURCE_EXHAUSTED:** habéis llegado al límite. `ingestar.py` espera y reintenta solo. Durante la demo,
  la búsqueda cae automáticamente a palabras clave si fallan los embeddings.
- **"No encuentra nada en los documentos":** las fichas PSI están en inglés y la búsqueda funciona mejor con términos en inglés.
  El prompt ya se lo indica a la IA. Comprobadlo con `prueba_herramientas.py`.
- **Columnas "casi numéricas"** (con algún `–`, `~6` o `#DIV/0!`): para filtros y estadísticas se convierten a número
  ignorando esos valores, y la respuesta dice cuántos se ignoraron.
- **Conexión cortada en sesiones largas:** la sesión reconecta sola con *session resumption* y comprime el contexto
  con ventana deslizante.
