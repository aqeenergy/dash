"""Clasifica los errores de la API de Gemini para decidir qué hacer y qué decirle al usuario.

Basado en la experiencia en producción con la API de Gemini:
  - clave       401/403, clave no válida              -> no reintentar
  - region      ubicación no admitida                 -> no reintentar
  - modelo      404 / modelo inexistente o renombrado -> pasar al siguiente modelo
  - saturado    "overloaded", "capacity", 503         -> pasar al modelo de reserva sin esperar
  - cuota_dia   cuota diaria agotada                  -> esperar no sirve: otro modelo o mañana
  - limite      429 por minuto                        -> esperar y reintentar (backoff)
  - red         conexión caída                        -> reintentar con esperas cortas
  - otro        cualquier otra cosa                   -> reintentar con esperas cortas
"""
from __future__ import annotations

import re

MENSAJES = {
    "inactividad": "Session paused for inactivity; it will resume with your next question.",
    "clave": "The onboard AI is not available right now.",
    "region": "The onboard AI is not available right now.",
    "modelo": "Restarting the onboard AI...",
    "saturado": "The onboard AI is busy; one moment...",
    "cuota_dia": "The onboard AI has reached its usage limit for today. Please try again later.",
    "limite": "The onboard AI is busy; one moment...",
    "red": "Reconnecting the onboard AI...",
    "otro": "The onboard AI hit an error; retrying...",
}

# Esperas (segundos) para reintentar cuando el límite es por minuto o hay fallos de red
ESPERAS_LIMITE = [2, 4, 8, 12, 16, 20, 30, 40]
ESPERAS_RED = [3, 6, 12, 20]


def clasificar(error: BaseException) -> str:
    texto = f"{error} {getattr(error, 'message', '')} {getattr(error, 'status', '')}".lower()
    codigo = getattr(error, "code", None)
    # Rechazos en el saludo del WebSocket: "server rejected WebSocket connection: HTTP 404"
    respuesta = getattr(error, "response", None)
    if codigo is None and getattr(respuesta, "status_code", None):
        codigo = respuesta.status_code
    if codigo is None and (m := re.search(r"http (\d{3})", texto)):
        codigo = int(m.group(1))

    if "inactivity" in texto:  # Gemini cierra si no le llega nada (p. ej. chat solo de texto)
        return "inactividad"
    if codigo in (401, 403) or any(s in texto for s in (
            "api key not valid", "api_key_invalid", "permission_denied", "unauthenticated",
            "invalid api key", "api key expired")):
        return "clave"
    if "location" in texto and ("not supported" in texto or "failed_precondition" in texto):
        return "region"
    if codigo == 404 or any(s in texto for s in (
            "not_found", "is not found", "not found for api version", "is not supported for",
            "model not found", "unknown model")):
        return "modelo"
    if any(s in texto for s in ("per day", "perday", "daily", "requests_per_day")):
        return "cuota_dia"
    if codigo == 503 or any(s in texto for s in (
            "overloaded", "capacity", "service tier", "unavailable", "try again later")):
        return "saturado"
    if codigo == 429 or any(s in texto for s in ("resource_exhausted", "quota", "rate limit", "too many")):
        return "limite"
    if isinstance(error, OSError) or codigo in (1006, 1011, 1001) or "abnormal closure" in texto:
        return "red"
    return "otro"


def mensaje(tipo: str) -> str:
    return MENSAJES.get(tipo, MENSAJES["otro"])
