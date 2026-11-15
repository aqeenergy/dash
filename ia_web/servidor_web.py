r"""Servidor de la IA de voz y texto para la web FLAMA.

voz/ es la carpeta ia_voz_texto/ del equipo (github.com/octamartinn/NASA-SPACE-APPS), SIN modificar.
Ese servidor ya numera las respuestas ("turno") y envía las citas, gráficas y documentos creados.
Este envoltorio solo:
  * apunta sus datos a base_de_datos/ (solo lectura) y a su índice RAG de voz/indice/;
  * convierte cada cita en una referencia INTERNA: el archivo exacto de la biblioteca de texto de
    base_de_datos (ficha PSI-XX.md o la tabla .csv) que la web abre al pulsarla, sin enlaces externos;
  * añade /ia/modo y los trabajos de Theory Lab.

Arranque (desde D:\nasa_dashboard):
    voz\.venv\Scripts\python -m uvicorn ia_web.servidor_web:app --port 8001
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VOZ = RAIZ / "voz"
sys.path.insert(0, str(VOZ))
sys.path.insert(0, str(RAIZ))

# Rutas de datos ANTES de importar ia_llama.config (setdefault: el .env puede cambiarlas)
os.environ.setdefault("DIR_TABLAS", str(RAIZ / "base_de_datos"))
os.environ.setdefault("DIR_METADATOS", str(RAIZ / "base_de_datos"))
os.environ.setdefault("DIR_DOCUMENTOS", str(VOZ / "documentos"))
os.environ.setdefault("DIR_INDICE", str(VOZ / "indice"))

from ia_llama import servidor  # noqa: E402
from ia_llama.sesion import SesionVoz  # noqa: E402

from biblioteca import _slug  # noqa: E402  (same ids as the web's text library)

_LIB = RAIZ / "static" / "library"


def _en_biblioteca(nombre: str) -> str:
    return nombre if nombre and (_LIB / nombre).exists() else ""


def _cabecera(archivo: str) -> list[str]:
    """Column names of a library table (first CSV row), longest first so 'Burning rate; mm' wins over 'Burning rate'."""
    import csv
    try:
        with open(_LIB / archivo, encoding="utf-8") as f:
            return sorted((h.strip() for h in next(csv.reader(f))), key=len, reverse=True)
    except Exception:
        return []


def cita_interna(c: dict) -> dict:
    """Cita del servidor del equipo -> referencia al archivo de base_de_datos en la biblioteca de la web."""
    c = dict(c)
    c.pop("url", None)  # nada de enlaces externos: el DOI se muestra solo como identificador
    acc = c.get("accesion") or (re.search(r"PSI-\d+", str(c.get("tabla") or c.get("fuente") or "")) or [None])[0] or ""
    if c.get("tipo") == "tabla" and c.get("tabla"):
        c["archivo"] = _en_biblioteca(_slug(str(c["tabla"])) + ".csv") or _en_biblioteca(_slug(acc) + ".md")
        consulta = str(c.get("consulta") or "")
        columnas = [h for h in _cabecera(c["archivo"]) if h and h in consulta]  # real headers named in the query
        # drop a shorter header contained in a longer one already matched
        c["columnas"] = [h for i, h in enumerate(columnas) if not any(h in o for o in columnas[:i])]
    else:
        c["archivo"] = _en_biblioteca(_slug(acc) + ".md")
    return c


class SesionFlama(SesionVoz):
    async def _emitir(self, evento: dict) -> None:
        if evento.get("tipo") == "cita" and isinstance(evento.get("cita"), dict):
            evento = {**evento, "cita": cita_interna(evento["cita"])}
        await super()._emitir(evento)


SesionConCitas = SesionFlama  # nombre anterior (ia_web/servidor_simulado.py)

# El servidor del equipo crea SesionVoz por conexión: se usa la versión con referencias internas.
servidor.SesionVoz = SesionFlama
app = servidor.app  # ya trae CORS (ORIGENES_PERMITIDOS en voz/.env, "*" por defecto)

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
