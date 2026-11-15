"""Sesión de voz en tiempo real con Gemini Live.

No depende de ningún framework web: recibe audio/texto por métodos y entrega audio/eventos
mediante dos funciones (callbacks) que le pasa quien la use (el servidor WebSocket, la prueba
por terminal, etc.).

    sesion = SesionVoz(al_audio=reproducir, al_evento=mostrar)
    tarea = asyncio.create_task(sesion.ejecutar())
    await sesion.enviar_audio(pcm_16khz)   # bytes PCM 16 bits mono 16 kHz
    await sesion.enviar_texto("¿Qué es una llama fría?")
    await sesion.cerrar()

Eventos que emite (diccionarios):
    {"tipo": "listo", "modelo": "..."}                  conectado con Gemini (y con qué modelo)
    {"tipo": "transcripcion_usuario", "texto": "..."}   lo que ha entendido de la persona
    {"tipo": "transcripcion_ia", "texto": "..."}        lo que está diciendo la IA (por trozos)
    {"tipo": "herramienta", "nombre": "...", "argumentos": {...}}  la IA está consultando datos
    {"tipo": "resultado_herramienta", "nombre": "...", "resumen": "..."}  qué devolvió (recortado)
    {"tipo": "fuentes", "fuentes": [{"fuente": ..., "pagina": ...}]}  documentos usados
    {"tipo": "interrumpido"}       la persona habló encima: hay que VACIAR el audio pendiente
    {"tipo": "turno_completo"}     la IA terminó de hablar
    {"tipo": "aviso", "mensaje": "..."}   algo pasa pero se está resolviendo solo (límite, modelo de reserva...)
    {"tipo": "reconectando"}
    {"tipo": "diagnostico", ...}         información técnica (p. ej. una respuesta atascada); la web puede ignorarlo
    {"tipo": "en_pausa"}                  Gemini cerró por inactividad; se reanuda sola con la siguiente entrada
    {"tipo": "error", "mensaje": "..."}   la sesión ha terminado: hay que volver a conectar
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

from google import genai
from google.genai import types

from . import config, errores, herramientas
from .prompt import INSTRUCCIONES

log = logging.getLogger(__name__)

_FIN = object()


def configuracion_live(handle_reanudacion: str | None = None) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=INSTRUCCIONES,
        tools=herramientas.HERRAMIENTAS_GEMINI,
        speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": config.VOZ}}},
        input_audio_transcription={},
        output_audio_transcription={},
        # Ventana deslizante: evita que la sesión se corte al llenarse el contexto
        context_window_compression={"sliding_window": {}},
        # Permite reconectar sin perder la conversación si Google cierra la conexión
        session_resumption=types.SessionResumptionConfig(handle=handle_reanudacion),
    )


class SesionVoz:
    def __init__(
        self,
        al_audio: Callable[[bytes], Awaitable[None]],
        al_evento: Callable[[dict], Awaitable[None]],
        cliente: genai.Client | None = None,
    ):
        self._al_audio = al_audio
        self._al_evento = al_evento
        # La API Live solo existe en v1beta; el SDK usa v1 por defecto (-> HTTP 404 en el WebSocket)
        self._cliente = cliente or genai.Client(
            api_key=config.GEMINI_API_KEY, http_options={"api_version": config.VERSION_API_LIVE}
        )
        self._entrada: asyncio.Queue = asyncio.Queue()
        self._handle: str | None = None
        self._cerrando = False
        self._pendiente = None  # entrada que llegó mientras la sesión estaba en pausa
        # Vigilante de respuestas atascadas
        self._respondiendo = False      # la IA está a mitad de una respuesta
        self._en_herramienta = False    # ejecutando una consulta (no cuenta como atasco)
        self._ultimo_rx = time.monotonic()
        self._ultimo_tipo = ""
        self._toques = 0
        self._fin_audio_previsto = 0.0  # cuándo terminaría de sonar el audio recibido

    # ------------------------------------------------------------------ API pública
    async def enviar_audio(self, pcm16_16khz: bytes) -> None:
        await self._entrada.put(("audio", pcm16_16khz))

    async def enviar_texto(self, texto: str) -> None:
        await self._entrada.put(("texto", texto))

    async def fin_audio(self) -> None:
        """Llamar cuando el micrófono se pausa más de ~1 s (por ejemplo, al soltar el botón)."""
        await self._entrada.put(("fin_audio", None))

    async def cerrar(self) -> None:
        self._cerrando = True
        await self._entrada.put((_FIN, None))

    async def ejecutar(self) -> None:
        """Mantiene la sesión viva hasta que se llame a cerrar(): reconecta si se corta, pasa a un
        modelo de reserva si el principal no existe, está saturado o sin cuota, y espera si se
        alcanza el límite por minuto. Los avisos para el usuario llegan como eventos 'aviso'."""
        modelos = config.MODELOS_LIVE
        i = 0  # modelo actual
        t_reserva = None  # cuándo se pasó a un modelo de reserva
        fallidos_seguidos = intentos_limite = intentos_red = 0
        conectado_en = None
        fin = time.monotonic() + config.MAX_MINUTOS_SESION * 60

        while not self._cerrando:
            if i and t_reserva and time.monotonic() - t_reserva > config.MINUTOS_VOLVER_AL_PRINCIPAL * 60:
                i, t_reserva, self._handle = 0, None, None  # volver a probar el principal
            modelo = modelos[i]
            try:
                async with self._cliente.aio.live.connect(
                    model=modelo, config=configuracion_live(self._handle)
                ) as sesion:
                    fallidos_seguidos = 0
                    conectado_en = time.monotonic()
                    await self._emitir({"tipo": "listo", "modelo": modelo})
                    restante = fin - time.monotonic()
                    if not await self._bucle(sesion, timeout=max(restante, 1)):
                        await self._emitir({"tipo": "error", "mensaje":
                            f"The session lasted more than {config.MAX_MINUTOS_SESION} minutes. Please reconnect."})
                        self._cerrando = True
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._cerrando:
                    break
                # Los contadores solo se reinician si la conexión aguantó un rato: así un error que se
                # repite en cada conexión no provoca un bucle infinito de reconexiones.
                if conectado_en and time.monotonic() - conectado_en > 30:
                    intentos_limite = intentos_red = 0
                conectado_en = None
                tipo = errores.clasificar(e)
                nivel = logging.DEBUG if tipo == "inactividad" else logging.WARNING  # la pausa es normal
                log.log(nivel, "Gemini (%s) falló [%s]: %s", modelo, tipo, e)

                if tipo == "inactividad":
                    # No reconectar en bucle: esperar a la siguiente pregunta o audio y reanudar
                    # la conversación con el handle de reanudación.
                    await self._emitir({"tipo": "en_pausa"})
                    siguiente = await self._entrada.get()
                    if siguiente[0] is _FIN:
                        break
                    self._pendiente = siguiente
                    continue

                if tipo in ("clave", "region"):
                    await self._emitir({"tipo": "error", "mensaje": errores.mensaje(tipo)})
                    break

                if tipo in ("modelo", "saturado", "cuota_dia"):
                    fallidos_seguidos += 1
                    if fallidos_seguidos >= len(modelos):  # ya se han probado todos
                        if tipo == "saturado":
                            await self._emitir({"tipo": "aviso", "mensaje":
                                "All of Google's models are busy; retrying in 30 s."})
                            await asyncio.sleep(30)
                            i, fallidos_seguidos, self._handle = 0, 0, None
                            continue
                        await self._emitir({"tipo": "error", "mensaje": errores.mensaje(tipo)})
                        break
                    i = (i + 1) % len(modelos)
                    t_reserva, self._handle = time.monotonic(), None  # el handle es de cada modelo
                    await self._emitir({"tipo": "aviso", "mensaje": errores.mensaje(tipo)})
                    continue

                if tipo == "limite":
                    if intentos_limite >= len(errores.ESPERAS_LIMITE):
                        await self._emitir({"tipo": "error", "mensaje":
                            "Gemini rate limit reached. Please try again in a minute."})
                        break
                    espera = errores.ESPERAS_LIMITE[intentos_limite]
                    intentos_limite += 1
                    await self._emitir({"tipo": "aviso", "mensaje": errores.mensaje(tipo)})
                    await asyncio.sleep(espera)
                    continue

                # red u otro: reconectar (con el handle se recupera la conversación)
                if intentos_red >= len(errores.ESPERAS_RED):
                    await self._emitir({"tipo": "error", "mensaje": f"Could not keep the connection: {e}"})
                    break
                espera = errores.ESPERAS_RED[intentos_red]
                intentos_red += 1
                await self._emitir({"tipo": "reconectando"})
                await asyncio.sleep(espera)

    # ------------------------------------------------------------------ interno
    async def _emitir(self, evento: dict) -> None:
        try:
            await self._al_evento(evento)
        except Exception:  # un fallo del cliente no debe tumbar la sesión
            log.exception("Error entregando evento %s", evento.get("tipo"))

    async def _bucle(self, sesion, timeout: float) -> bool:
        """Devuelve False si se agotó el tiempo máximo de sesión."""
        self._respondiendo, self._toques, self._ultimo_rx = False, 0, time.monotonic()
        self._fin_audio_previsto = 0.0
        enviar = asyncio.create_task(self._enviar(sesion))
        recibir = asyncio.create_task(self._recibir(sesion))
        vigilar = asyncio.create_task(self._vigilar(sesion))
        hechas, pendientes = await asyncio.wait(
            {enviar, recibir, vigilar}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pendientes:
            t.cancel()
        for t in hechas:  # propaga errores de conexión para que ejecutar() reconecte
            if not t.cancelled() and t.exception():
                raise t.exception()
        return bool(hechas)

    async def _vigilar(self, sesion) -> None:
        """Si la IA se queda callada a mitad de respuesta (Gemini deja de enviar cualquier cosa),
        le da un toque; si no reacciona tras dos toques, fuerza una reconexión con la conversación."""
        while True:
            await asyncio.sleep(min(1.0, config.SEGUNDOS_ATASCO / 3))
            if not self._respondiendo or self._en_herramienta:
                continue
            # El plazo cuenta desde lo último recibido o desde que terminaría de sonar el audio
            # ya recibido (Gemini lo envía más rápido de lo que suena y avisa del fin al acabar).
            parado = time.monotonic() - max(self._ultimo_rx, self._fin_audio_previsto)
            if parado < config.SEGUNDOS_ATASCO:
                continue
            diagnostico = {"tipo": "diagnostico", "suceso": "respuesta_atascada",
                           "segundos_sin_datos": round(parado, 1), "ultimo_mensaje": self._ultimo_tipo,
                           "toque": self._toques + 1}
            log.info("Respuesta atascada: %s", diagnostico)
            await self._emitir(diagnostico)
            if self._toques >= 2:
                raise ConnectionError("respuesta atascada: Gemini no responde a los toques")
            self._toques += 1
            self._ultimo_rx = time.monotonic()
            await self._emitir({"tipo": "aviso", "mensaje": "The answer got stuck; restarting it..."})
            await sesion.send_realtime_input(text=config.TEXTO_TOQUE)

    async def _enviar(self, sesion) -> None:
        while True:
            if self._pendiente is not None:
                (tipo, dato), self._pendiente = self._pendiente, None
            else:
                tipo, dato = await self._entrada.get()
            if tipo is _FIN:
                return
            if tipo == "audio":
                await sesion.send_realtime_input(
                    audio=types.Blob(data=dato, mime_type=f"audio/pcm;rate={config.FRECUENCIA_ENTRADA}")
                )
            elif tipo == "fin_audio":
                await sesion.send_realtime_input(audio_stream_end=True)
            elif tipo == "texto":
                await sesion.send_realtime_input(text=dato)

    async def _recibir(self, sesion) -> None:
        while True:  # receive() termina en cada fin de turno, por eso se vuelve a llamar
            async for msg in sesion.receive():
                await self._procesar(sesion, msg)

    async def _procesar(self, sesion, msg: types.LiveServerMessage) -> None:
        self._ultimo_rx = time.monotonic()
        campos = getattr(type(msg), "model_fields", None) or vars(msg)
        self._ultimo_tipo = ",".join(k for k in campos
                                     if k != "usage_metadata" and getattr(msg, k, None) is not None) or "?"
        if msg.session_resumption_update and msg.session_resumption_update.new_handle:
            self._handle = msg.session_resumption_update.new_handle

        if msg.go_away:
            log.info("Gemini avisa de que cerrará la conexión pronto; se reconectará solo")

        if msg.tool_call and msg.tool_call.function_calls:
            await self._atender_herramientas(sesion, msg.tool_call.function_calls)

        sc = msg.server_content
        if sc is None:
            return
        if sc.model_turn or sc.output_transcription:
            self._respondiendo = True
        if getattr(sc, "generation_complete", False):
            # Gemini ya generó toda la respuesta: el audio llega más rápido de lo que suena y el
            # "turno completo" puede tardar en llegar. Eso no es un atasco.
            self._respondiendo = False
        if sc.interrupted:
            self._respondiendo = False
            await self._emitir({"tipo": "interrumpido"})
        if sc.input_transcription and sc.input_transcription.text:
            await self._emitir({"tipo": "transcripcion_usuario", "texto": sc.input_transcription.text})
        if sc.output_transcription and sc.output_transcription.text:
            await self._emitir({"tipo": "transcripcion_ia", "texto": sc.output_transcription.text})
        if sc.model_turn:
            for parte in sc.model_turn.parts or []:
                if parte.inline_data and parte.inline_data.data:
                    ahora = time.monotonic()
                    self._fin_audio_previsto = (max(self._fin_audio_previsto, ahora)
                                                + len(parte.inline_data.data) / 2 / config.FRECUENCIA_SALIDA)
                    try:
                        await self._al_audio(parte.inline_data.data)
                    except Exception:
                        log.exception("Error entregando audio")
        if sc.turn_complete:
            self._respondiendo, self._toques = False, 0
            await self._emitir({"tipo": "turno_completo"})

    async def _atender_herramientas(self, sesion, llamadas) -> None:
        self._respondiendo, self._en_herramienta = True, True
        try:
            await self._atender_herramientas_(sesion, llamadas)
        finally:
            self._en_herramienta = False
            self._ultimo_rx = time.monotonic()  # el plazo cuenta desde que Gemini tiene el resultado

    async def _atender_herramientas_(self, sesion, llamadas) -> None:
        async def una(fc) -> types.FunctionResponse:
            argumentos = dict(fc.args or {})
            await self._emitir({"tipo": "herramienta", "nombre": fc.name, "argumentos": argumentos})
            # En un hilo aparte: pandas o los embeddings no deben bloquear el audio
            resultado = await asyncio.to_thread(herramientas.ejecutar, fc.name, argumentos)
            resumen = json.dumps(resultado, ensure_ascii=False, default=str)
            await self._emitir({"tipo": "resultado_herramienta", "nombre": fc.name,
                                "resumen": resumen[:600] + ("…" if len(resumen) > 600 else "")})
            if fc.name == "buscar_documentos" and resultado.get("resultados"):
                fuentes = [{"fuente": r["fuente"], "pagina": r["pagina"]} for r in resultado["resultados"]]
                await self._emitir({"tipo": "fuentes", "fuentes": fuentes})
            return types.FunctionResponse(id=fc.id, name=fc.name, response=resultado)

        # Si Gemini pide varias consultas a la vez, se ejecutan en paralelo (mismo orden en la respuesta)
        respuestas = await asyncio.gather(*(una(fc) for fc in llamadas))
        await sesion.send_tool_response(function_responses=list(respuestas))
