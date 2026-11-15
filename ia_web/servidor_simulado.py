"""Servidor de la IA en MODO SIMULADO: mismo WebSocket y mismas citas, sin clave ni cuota.

Sustituye Gemini Live por un "modelo" falso que:
  * ante una pregunta escrita, ejecuta las herramientas REALES sobre base_de_datos/ (FLEX ->
    estadísticas por combustible; cualquier otra -> búsqueda en los documentos PSI);
  * responde con un texto construido SOLO a partir de lo que devolvieron esas herramientas.
No genera voz (no hay audio) ni entiende el micrófono. Sirve para probar la web y la demo.

    voz\\.venv\\Scripts\\python -m uvicorn ia_web.servidor_simulado:app --port 8001
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

from ia_web import servidor_web  # noqa: F401  (configura rutas y protocolo de citas)
from ia_web.servidor_web import SesionConCitas, servidor

servidor.config.GEMINI_API_KEY = servidor.config.GEMINI_API_KEY or "modo-simulado"

TABLA_FLEX = "PSI-69_Experimental table_FLEX"


def _sc(texto=None, fin=False, entrada=None):
    return NS(tool_call=None, session_resumption_update=None, go_away=None,
              server_content=NS(interrupted=False, model_turn=None, generation_complete=fin, turn_complete=fin,
                                input_transcription=NS(text=entrada) if entrada else None,
                                output_transcription=NS(text=texto) if texto else None))


def _num(x):
    return f"{x:g}".replace(".", ",") if isinstance(x, (int, float)) else str(x)


def _redactar(pregunta: str, nombre: str, r: dict) -> str:
    """Texto de la 'IA' a partir del resultado real de la herramienta (nada más)."""
    if "error" in r:
        return f"(Modo simulado) La consulta falló: {r['error']}"
    if nombre == "estadisticas_tabla" and r.get("agrupado_por"):
        filas = []
        for grupo, est in r["estadisticas"].items():
            media = next((v for k, v in est.items() if k.endswith("_mean")), None)
            n = next((v for k, v in est.items() if k.endswith("_count")), None)
            if media is not None:
                filas.append((grupo, media, n))
        if not filas:
            return "(Modo simulado) La tabla no tiene valores numéricos para comparar."
        filas.sort(key=lambda x: -x[1])
        partes = "; ".join(f"{g}: media {_num(m)} en {int(n or 0)} ensayos" for g, m, n in filas)
        col = r.get("agrupado_por")
        return (f"(Modo simulado) En la tabla de FLEX, agrupando por {col}: {partes}. "
                f"Con la media más alta de tasa de combustión está {filas[0][0]}.")
    if nombre == "buscar_documentos":
        res = r.get("resultados") or []
        if not res:
            return "(Modo simulado) No tengo datos sobre eso en mis fuentes."
        fuentes = ", ".join(dict.fromkeys(x["fuente"].rsplit("/", 1)[-1].removesuffix(".md") for x in res[:3]))
        return (f"(Modo simulado) Lo más cercano a tu escenario en los documentos del PSI está en: {fuentes}. "
                "Abre las citas para leer los fragmentos consultados.")
    return "(Modo simulado) Consulta hecha; revisa la cita."


class SesionFalsa:
    def __init__(self):
        self.cola, self.evento, self.pregunta = [], asyncio.Event(), ""

    def _poner(self, msg):
        self.cola.append(msg)
        self.evento.set()

    async def send_realtime_input(self, audio=None, text=None, audio_stream_end=None):
        if audio_stream_end:
            self._poner(_sc("(Modo simulado) El modo simulado no entiende la voz: escribe la pregunta.", fin=True))
        if not text or text.startswith("(Sigue"):
            return
        self.pregunta = text
        if "flex" in text.lower():
            fc = NS(id="1", name="estadisticas_tabla",
                    args={"tabla": TABLA_FLEX, "columnas": ["Burning rate; mm"], "agrupar_por": "Fuel"})
        else:
            fc = NS(id="1", name="buscar_documentos", args={"consulta": text, "num_resultados": 3})
        self._poner(NS(tool_call=NS(function_calls=[fc]), server_content=None,
                       session_resumption_update=None, go_away=None))

    async def send_tool_response(self, function_responses):
        fr = function_responses[0]
        texto = _redactar(self.pregunta, fr.name, fr.response or {})
        palabras = texto.split(" ")
        for i in range(0, len(palabras), 6):  # llega a trozos, como la transcripción real
            self._poner(_sc(" ".join(palabras[i:i + 6]) + (" " if i + 6 < len(palabras) else "")))
            await asyncio.sleep(0.04)
        self._poner(_sc(fin=True))

    async def receive(self):
        while True:
            await self.evento.wait()
            self.evento.clear()
            while self.cola:
                yield self.cola.pop(0)


class ClienteFalso:
    def __init__(self):
        self.aio = NS(live=NS(connect=self._connect))

    @asynccontextmanager
    async def _connect(self, model, config):
        yield SesionFalsa()


class SesionSimulada(SesionConCitas):
    def __init__(self, al_audio, al_evento, cliente=None):
        super().__init__(al_audio, al_evento, cliente or ClienteFalso())

    async def _emitir(self, evento):
        if evento.get("tipo") == "listo":
            evento["modelo"] = "simulado (sin Gemini)"
        await super()._emitir(evento)


servidor.SesionVoz = SesionSimulada
servidor_web.MODO_SIMULADO = True
app = servidor_web.app
