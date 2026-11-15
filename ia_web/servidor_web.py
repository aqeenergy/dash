"""Servidor de la IA de voz y texto para la web FLAMA, con CITAS.

Envuelve la IA de voz/ SIN modificarla:
  * Datos: las tablas y fichas PSI se leen de base_de_datos/ (solo lectura) y el índice RAG de
    voz/indice/ (ya construido sobre voz/documentos_psi/).
  * Protocolo: añade a los eventos de voz/ la numeración de respuestas ("turno") y el evento
        {"tipo": "cita", "turno": N, "id": K, "cita": {...}}
    para cada dato consultado (ver ia_web/citas.py). turno_completo e interrumpido llevan el
    mismo número de turno que sus citas.
  * Instrucciones: añade a las de voz/ una regla para relacionar el escenario del astronauta
    con la investigación PSI más cercana, sin inventar.

Arranque (desde D:\\nasa_dashboard):
    voz\\.venv\\Scripts\\python -m uvicorn ia_web.servidor_web:app --port 8001
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VOZ = RAIZ / "voz"
sys.path.insert(0, str(VOZ))

# Rutas de datos ANTES de importar ia_llama.config (setdefault: el .env puede cambiarlas)
os.environ.setdefault("DIR_TABLAS", str(RAIZ / "base_de_datos"))
os.environ.setdefault("DIR_METADATOS", str(RAIZ / "base_de_datos"))
os.environ.setdefault("DIR_DOCUMENTOS", str(VOZ / "documentos_psi"))
os.environ.setdefault("DIR_INDICE", str(VOZ / "indice"))

from fastapi import HTTPException as _HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from google.genai import types  # noqa: E402

from ia_llama import herramientas, servidor, sesion as sesion_mod  # noqa: E402
from ia_llama.sesion import SesionVoz  # noqa: E402

from ia_web.citas import citas_de, clave  # noqa: E402

REGLA_ESCENARIOS = """

ESCENARIOS OPERATIVOS (FLAMA)
- Cuando el astronauta plantee un escenario (un fallo, un material que arde, una atmósfera, una gravedad),
  identifica primero la investigación del NASA PSI más cercana a ese escenario consultando tus herramientas
  (documentos o tablas) y nómbrala con su acrónimo y su accesión (por ejemplo "FLEX, PSI-69").
- Basa la respuesta en lo que devuelvan las herramientas. Si ninguna investigación se parece al escenario,
  dilo con claridad y no rellenes con datos inventados.
- Las recomendaciones operativas (aislar, cortar ventilación, evacuar...) las da también el asistente Flammy
  de la web: no hace falta que las repitas si no las respaldan los datos consultados.

GRÁFICAS
- Si piden ver, visualizar o comparar datos de forma gráfica ("show me a chart..."), usa crear_grafica
  (barras para comparar medias entre grupos, dispersión para la relación entre dos columnas, histograma
  para cómo se reparten los valores). Pon el título en el idioma de la pregunta.
- La gráfica aparece en la pantalla: di que la muestras en pantalla y lo más importante que se ve en UNA
  frase; no leas las cifras. NUNCA digas que no puedes hacer gráficas.

ESCENARIOS DE RIESGO
- Si preguntan "qué pasaría si arde X...", "¿es peligroso Y con tanto oxígeno?" o describen una situación
  concreta, llama SIEMPRE a evaluar_escenario con lo que hayan dicho (material, oxígeno, ventilación,
  presión), aunque creas que ese material no está en los datos.
- Responde en 3 o 4 frases como mucho: qué pasó en el ensayo más parecido (cifra y experimento), qué factor
  aumenta o reduce el riesgo y, si el escenario cae fuera de lo ensayado, dilo sin extrapolar. Añade en
  pocas palabras que es una comparación con experimentos, no una evaluación certificada.
- Si el material no aparece en los datos, empieza diciéndolo ("there are no tests with wood in my sources")
  y ofrece materiales parecidos que sí estén.
- Lo marcado como "TIERRA (1 g, ensayo de referencia)" se midió en tierra: no digas que pasó en microgravedad.

DOCUMENTOS
- Si te piden CREAR un documento (informe, resumen, ficha, recomendaciones...): 1) consulta los datos
  necesarios (una o dos herramientas), 2) SIN hablar todavía, llama a crear_documento con el texto completo
  en Markdown, en el idioma de la pregunta, terminado en "## Sources" (investigación, accesión PSI y DOI),
  3) cuando recibas su resultado, di que ya está y en una frase qué contiene; la web muestra los enlaces.
- crear_documento es la ÚNICA forma de crear un archivo y crear_grafica la única de mostrar una gráfica.
  NUNCA digas que lo has hecho si no has llamado a la herramienta y recibido su resultado.

IDENTIDAD
- Eres Llama, la IA de a bordo del sistema FLAMA (una simulación de sistema embebido para naves). Si te
  preguntan qué modelo, empresa o servicio hay detrás, di que eres la IA de a bordo de FLAMA y no nombres
  ningún modelo ni empresa.

IDIOMA (recordatorio final, prioritario)
- La web de FLAMA está en inglés y la mayoría de las preguntas llegarán en inglés: responde SIEMPRE en el
  idioma de la última pregunta (en inglés si te preguntan en inglés), aunque estas instrucciones estén en español.
- No termines con preguntas de seguimiento.
"""
sesion_mod.INSTRUCCIONES = sesion_mod.INSTRUCCIONES + REGLA_ESCENARIOS

_ABREN = {"transcripcion_ia", "herramienta", "resultado_herramienta", "cita", "fuentes", "grafica", "documento_creado"}
_CIERRAN = {"turno_completo", "interrumpido"}


class SesionConCitas(SesionVoz):
    """SesionVoz + numeración de respuestas + eventos 'cita'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._turno = 1
        self._abierto = False        # ha llegado contenido de la respuesta en curso
        self._ultimo_cierre = None   # número del último turno cerrado
        self._citas_turno: set = set()
        self._n_cita = 0

    async def _emitir(self, evento: dict) -> None:
        tipo = evento.get("tipo")
        # FLAMA simula un sistema embebido: la web no muestra avisos internos (modelo de reserva,
        # límites, reconexiones) ni qué modelo hay detrás; los errores llegan con texto neutro.
        if tipo == "aviso":
            return
        if tipo == "listo":
            evento = {k: v for k, v in evento.items() if k != "modelo"}
        if tipo in _ABREN:
            self._abierto = True
            evento.setdefault("turno", self._turno)
        elif tipo in _CIERRAN:
            if not self._abierto and self._ultimo_cierre is not None:
                # p. ej. 'interrumpido' seguido de 'turno_completo' de la misma respuesta
                evento["turno"] = self._ultimo_cierre
            else:
                evento["turno"] = self._turno
                self._ultimo_cierre = self._turno
                self._turno += 1
                self._abierto = False
                self._citas_turno, self._n_cita = set(), 0
        await super()._emitir(evento)

    async def _atender_herramientas_(self, sesion, llamadas) -> None:
        async def una(fc) -> types.FunctionResponse:
            argumentos = dict(fc.args or {})
            await self._emitir({"tipo": "herramienta", "nombre": fc.name, "argumentos": argumentos})
            resultado = await asyncio.to_thread(herramientas.ejecutar, fc.name, argumentos)
            if fc.name == "crear_grafica" and isinstance(resultado, dict) and resultado.get("url"):
                await self._emitir({"tipo": "grafica", "turno": self._turno, "titulo": resultado.get("titulo"),
                                    "url": resultado["url"]})
                # a Gemini solo le hace falta el resumen, no todos los puntos dibujados
                resultado = {k: v for k, v in resultado.items() if k != "datos"}
                resultado["mostrada_en_pantalla"] = True
            if fc.name == "crear_documento" and isinstance(resultado, dict) and resultado.get("archivos"):
                await self._emitir({"tipo": "documento_creado", "turno": self._turno,
                                    "titulo": resultado.get("titulo"), "archivos": resultado["archivos"]})
            resumen = json.dumps(resultado, ensure_ascii=False, default=str)
            await self._emitir({"tipo": "resultado_herramienta", "nombre": fc.name,
                                "resumen": resumen[:600] + ("…" if len(resumen) > 600 else "")})
            if fc.name == "buscar_documentos" and resultado.get("resultados"):
                fuentes = [{"fuente": r["fuente"], "pagina": r["pagina"]} for r in resultado["resultados"]]
                await self._emitir({"tipo": "fuentes", "fuentes": fuentes})
            for cita in citas_de(fc.name, argumentos, resultado):
                k = clave(cita)
                if k in self._citas_turno:
                    continue
                self._citas_turno.add(k)
                self._n_cita += 1
                await self._emitir({"tipo": "cita", "turno": self._turno, "id": self._n_cita, "cita": cita})
            return types.FunctionResponse(id=fc.id, name=fc.name, response=resultado)

        respuestas = await asyncio.gather(*(una(fc) for fc in llamadas))
        await sesion.send_tool_response(function_responses=list(respuestas))


# El servidor original crea SesionVoz por conexión: se sustituye por la versión con citas.
servidor.SesionVoz = SesionConCitas
app = servidor.app
app.add_middleware(
    CORSMiddleware,
    # local development + the public Streamlit Community Cloud app (+ extra origins via FLAMA_CORS_ORIGINS)
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://[a-z0-9-]+\.streamlit\.app"
    + "".join("|" + __import__("re").escape(o.strip()) for o in os.getenv("FLAMA_CORS_ORIGINS", "").split(",") if o.strip()),
    allow_methods=["GET", "POST"], allow_headers=["*"],
)

MODO_SIMULADO = False  # servidor_simulado.py lo pone a True

from fastapi.responses import FileResponse as _FileResponse  # noqa: E402

from ia_llama import documentos as _documentos, graficas as _graficas  # noqa: E402


@app.get("/ia/graficas/{nombre}")
def descargar_grafica(nombre: str):
    try:
        return _FileResponse(_graficas.ruta(nombre), media_type="image/png")
    except _graficas.ErrorGrafica as e:
        raise _HTTPException(404, str(e))


@app.get("/ia/generados/{nombre}")
def descargar_generado(nombre: str):
    try:
        return _FileResponse(_documentos.ruta_generado(nombre), filename=nombre)
    except _documentos.ErrorDocumento as e:
        raise _HTTPException(404, str(e))


@app.get("/ia/modo")
def modo() -> dict:
    """La web lo usa para mostrar si la IA es real o simulada."""
    return {"simulado": MODO_SIMULADO}


# ---------------------------------------------------------------------------
# Theory Lab: topic synthesis jobs (a run takes minutes, so it is a background job)
#   POST /ia/teorias            {"tema": "soot"}  -> {"job": "...", "estado": "en_curso"}
#   GET  /ia/teorias/{job}                        -> {"estado": "en_curso" | "listo" | "error", "resultado": {...}}
# ---------------------------------------------------------------------------
import threading as _threading  # noqa: E402
import uuid as _uuid  # noqa: E402

from fastapi import Body as _Body, Request as _Request  # noqa: E402

_JOBS: dict = {}
_JOBS_LOCK = _threading.Lock()

# Each synthesis spends many Gemini calls of the shared quota: limit per visitor and per day.
import time as _time  # noqa: E402

_LIM_IP_HORA = int(os.getenv("TEORIAS_POR_IP_HORA", "3"))
_LIM_DIA = int(os.getenv("TEORIAS_POR_DIA", "20"))
_USO: dict = {}          # ip -> [timestamps]
_USO_DIA: list = []      # timestamps (all visitors)


def _ip(req) -> str:
    fwd = req.headers.get("x-forwarded-for", "")   # Render / proxies
    return (fwd.split(",")[0].strip() if fwd else "") or (req.client.host if req.client else "?")


def _cupo(ip: str) -> str | None:
    """None if this visitor may start a synthesis now; otherwise the reason (and records the use when allowed)."""
    ahora = _time.time()
    _USO_DIA[:] = [t for t in _USO_DIA if ahora - t < 86400]
    mias = [t for t in _USO.get(ip, []) if ahora - t < 3600]
    if len(_USO_DIA) >= _LIM_DIA:
        return "Daily limit of AI syntheses reached; the stored theories are still available."
    if len(mias) >= _LIM_IP_HORA:
        return f"Limit of {_LIM_IP_HORA} AI syntheses per hour reached; try again later."
    _USO[ip] = mias + [ahora]
    _USO_DIA.append(ahora)
    return None


def _job(job_id: str, tema: str) -> None:
    from ia_web import teorias

    try:
        data = teorias.run(tema=tema, k=8, workers=4)
        teorias.save(data)
        with _JOBS_LOCK:
            _JOBS[job_id].update(estado="listo", resultado=data)
    except Exception as e:  # reported to the web, never crashes the voice server
        with _JOBS_LOCK:
            _JOBS[job_id].update(estado="error", mensaje=str(e)[:300])


@app.post("/ia/teorias")
def crear_teorias(req: _Request, cuerpo: dict = _Body(...)) -> dict:
    tema = " ".join(str(cuerpo.get("tema") or "").split())[:80]
    if len(tema) < 2:
        raise _HTTPException(400, "tema vacío")
    with _JOBS_LOCK:
        activos = [j for j in _JOBS.values() if j["estado"] == "en_curso"]
        if len(activos) >= 2:
            raise _HTTPException(429, "Ya hay dos síntesis en curso; espera a que terminen.")
        motivo = _cupo(_ip(req))
        if motivo:
            raise _HTTPException(429, motivo)
        job_id = _uuid.uuid4().hex[:12]
        _JOBS[job_id] = {"estado": "en_curso", "tema": tema}
    _threading.Thread(target=_job, args=(job_id, tema), daemon=True).start()
    return {"job": job_id, "estado": "en_curso", "tema": tema}


@app.get("/ia/teorias/{job_id}")
def estado_teorias(job_id: str) -> dict:
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            raise _HTTPException(404, "job desconocido")
        return dict(j)
