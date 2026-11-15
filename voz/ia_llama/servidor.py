"""Puente WebSocket navegador <-> Gemini Live, con FastAPI.

La clave de API y las herramientas se quedan en el servidor; el navegador solo envía y recibe audio.

Integración en una app FastAPI existente:
    from ia_llama.servidor import router
    app.include_router(router)          # expone  ws://.../ws/voz  y  GET /ia/salud

O como servicio independiente:
    uvicorn ia_llama.servidor:app --port 8001

Protocolo del WebSocket /ws/voz
  Navegador -> servidor
    * mensaje BINARIO: audio del micro, PCM 16 bits mono little-endian a 16 kHz (trozos de ~20-100 ms)
    * mensaje de TEXTO (JSON):
        {"tipo": "texto", "texto": "pregunta escrita"}
        {"tipo": "fin_audio"}            el micro se ha pausado
  Servidor -> navegador
    * mensaje BINARIO: audio de la IA, PCM 16 bits mono little-endian a 24 kHz
    * mensaje de TEXTO (JSON): los eventos documentados en sesion.py
      (listo, transcripcion_usuario, transcripcion_ia, herramienta, fuentes, interrumpido,
       turno_completo, aviso, reconectando, error)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config, datos, documentos, graficas, herramientas
from .sesion import SesionVoz

log = logging.getLogger(__name__)
router = APIRouter()

MAX_CARACTERES_TEXTO = 2000  # una pregunta escrita no necesita más

# Tablas, fichas e índice cargados al arrancar: la primera pregunta no tiene que esperarlos
try:
    herramientas.precargar()
except Exception as e:  # sin datos el servidor arranca igual y /ia/salud lo mostrará
    log.warning("No se pudieron precargar los datos: %s", e)

# Protección de la cuota compartida: sesiones a la vez y sesiones por IP en la última hora
_activas = 0
_por_ip: dict[str, deque] = defaultdict(deque)


def _ip(ws: WebSocket) -> str:
    reenviada = ws.headers.get("x-forwarded-for")  # detrás de un proxy (Render, Cloudflare...)
    return reenviada.split(",")[0].strip() if reenviada else (ws.client.host if ws.client else "?")


def _motivo_rechazo(ip: str) -> str | None:
    ahora = time.time()
    historial = _por_ip[ip]
    while historial and ahora - historial[0] > 3600:
        historial.popleft()
    if _activas >= config.MAX_SESIONES_SIMULTANEAS:
        return "Hay demasiadas personas hablando con la IA ahora mismo. Prueba en un par de minutos."
    if len(historial) >= config.MAX_SESIONES_IP_HORA:
        return "Has alcanzado el máximo de conversaciones por hora. Prueba más tarde."
    historial.append(ahora)
    return None


@router.get("/ia/salud")
def salud() -> dict:
    """Comprobación rápida de que todo está cargado."""
    return {
        "clave_configurada": bool(config.GEMINI_API_KEY),
        "modelos": config.MODELOS_LIVE,
        "sesiones_activas": _activas,
        "fragmentos_indexados": len(herramientas.indice().fragmentos),
        "busqueda_semantica": herramientas.indice().vectores is not None,
        "tablas": list(datos.tablas()),
        "documentos_subidos": len(documentos.listar()["subidos_por_el_usuario"]),
    }


@router.post("/ia/documentos")
async def subir_documento(request: Request, archivo: UploadFile = File(...)) -> dict:
    """Sube un PDF, DOCX, TXT o MD para que la IA pueda buscar en él, leerlo y citarlo."""
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "?")
    if _subidas_excedidas(ip):
        raise HTTPException(429, "Demasiadas subidas en la última hora. Prueba más tarde.")
    limite = int(config.MAX_MB_SUBIDA * 1024 * 1024)
    contenido = await archivo.read(limite + 1)
    try:
        return await asyncio.to_thread(documentos.subir, archivo.filename or "", contenido)
    except documentos.ErrorDocumento as e:
        raise HTTPException(400, str(e)) from e


@router.get("/ia/documentos")
def listar_documentos() -> dict:
    return documentos.listar()


@router.get("/ia/generados/{nombre}")
def descargar_generado(nombre: str) -> FileResponse:
    try:
        ruta = documentos.ruta_generado(nombre)
    except documentos.ErrorDocumento as e:
        raise HTTPException(404, str(e)) from e
    return FileResponse(ruta, filename=ruta.name)


@router.get("/ia/graficas/{nombre}")
def descargar_grafica(nombre: str) -> FileResponse:
    try:
        return FileResponse(graficas.ruta(nombre), media_type="image/png")
    except graficas.ErrorGrafica as e:
        raise HTTPException(404, str(e)) from e


_subidas_ip: dict[str, deque] = defaultdict(deque)


def _subidas_excedidas(ip: str) -> bool:
    ahora, historial = time.time(), _subidas_ip[ip]
    while historial and ahora - historial[0] > 3600:
        historial.popleft()
    if len(historial) >= config.MAX_SUBIDAS_IP_HORA:
        return True
    historial.append(ahora)
    return False


@router.websocket("/ws/voz")
async def ws_voz(ws: WebSocket) -> None:
    global _activas
    await ws.accept()
    motivo = "Falta GEMINI_API_KEY en el servidor" if not config.GEMINI_API_KEY else _motivo_rechazo(_ip(ws))
    if motivo:
        await ws.send_text(json.dumps({"tipo": "error", "mensaje": motivo}, ensure_ascii=False))
        await ws.close()
        return
    candado = asyncio.Lock()  # Starlette no permite dos envíos simultáneos por el mismo socket

    async def al_audio(pcm: bytes) -> None:
        async with candado:
            await ws.send_bytes(pcm)

    async def al_evento(evento: dict) -> None:
        async with candado:
            await ws.send_text(json.dumps(evento, ensure_ascii=False, default=str))

    _activas += 1
    sesion = tarea = None
    try:
        sesion = SesionVoz(al_audio, al_evento)
        tarea = asyncio.create_task(sesion.ejecutar())
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await sesion.enviar_audio(msg["bytes"])
            elif msg.get("text"):
                try:
                    datos_msg = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if datos_msg.get("tipo") == "texto" and datos_msg.get("texto"):
                    await sesion.enviar_texto(str(datos_msg["texto"])[:MAX_CARACTERES_TEXTO])
                elif datos_msg.get("tipo") == "fin_audio":
                    await sesion.fin_audio()
    except WebSocketDisconnect:
        pass
    finally:
        _activas -= 1  # siempre, aunque la sesión fallara al crearse
        if sesion is not None:
            await sesion.cerrar()
        if tarea is not None:
            try:
                await asyncio.wait_for(tarea, timeout=5)
            except (asyncio.TimeoutError, Exception):
                tarea.cancel()


app = FastAPI(title="IA Llama en caída libre")
# La web (Streamlit u otra) suele estar en otro puerto: permitir que suba y descargue documentos
app.add_middleware(CORSMiddleware, allow_origins=config.ORIGENES_PERMITIDOS, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
