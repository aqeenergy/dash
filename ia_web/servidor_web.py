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
"""
sesion_mod.INSTRUCCIONES = sesion_mod.INSTRUCCIONES + REGLA_ESCENARIOS

_ABREN = {"transcripcion_ia", "herramienta", "resultado_herramienta", "cita", "fuentes"}
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

from fastapi import Body as _Body, HTTPException as _HTTPException  # noqa: E402

_JOBS: dict = {}
_JOBS_LOCK = _threading.Lock()


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
def crear_teorias(cuerpo: dict = _Body(...)) -> dict:
    tema = " ".join(str(cuerpo.get("tema") or "").split())[:80]
    if len(tema) < 2:
        raise _HTTPException(400, "tema vacío")
    with _JOBS_LOCK:
        activos = [j for j in _JOBS.values() if j["estado"] == "en_curso"]
        if len(activos) >= 2:
            raise _HTTPException(429, "Ya hay dos síntesis en curso; espera a que terminen.")
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
