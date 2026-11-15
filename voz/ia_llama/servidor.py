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

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect

from . import config, datos, herramientas
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
        return "Too many people are talking to the AI right now. Please try again in a minute."
    if len(historial) >= config.MAX_SESIONES_IP_HORA:
        return "You have reached the maximum number of conversations per hour. Please try again later."
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
    }


@router.websocket("/ws/voz")
async def ws_voz(ws: WebSocket) -> None:
    global _activas
    await ws.accept()
    motivo = "The AI server has no GEMINI_API_KEY configured." if not config.GEMINI_API_KEY else _motivo_rechazo(_ip(ws))
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
app.include_router(router)
