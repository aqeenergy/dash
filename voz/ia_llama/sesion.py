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
    {"tipo": "grafica", "turno": n, "titulo": "...", "url": "/ia/graficas/...png", "datos": {...}}
    {"tipo": "documento_creado", "turno": n, "titulo": "...", "archivos": [{"formato", "nombre", "url"}]}
    {"tipo": "cita", "turno": n, "id": k, "cita": {...}}  referencia de lo consultado para la respuesta n
        cita = {tipo: "tabla"|"documento", investigacion, accesion, titulo, doi, url,
                tabla, consulta, filas  |  fuente, pagina, extracto}
    {"tipo": "interrumpido", "turno": n}   la persona habló encima: hay que VACIAR el audio pendiente
    {"tipo": "turno_completo", "turno": n}   la IA terminó la respuesta n (las citas de n ya han llegado)
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
import re
import time
import unicodedata
from typing import Awaitable, Callable

from google import genai
from google.genai import types

from . import config, errores, herramientas
from .prompt import INSTRUCCIONES

log = logging.getLogger(__name__)

_FIN = object()


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


# Frases con las que la IA afirma haber hecho algo que exige una herramienta (sin tildes, en minúsculas)
_AFIRMACIONES = {
    "crear_documento": re.compile(
        r"\b(he|te he|ya he|acabo de|hemos) (creado|preparado|generado|redactado|elaborado|hecho|escrito)\b"
        r"[^.?!]{0,60}\b(informe|documento|resumen|pdf|word|archivo|ficha|report)"
        r"|\b(informe|documento)\b[^.?!]{0,40}\b(esta|ya esta) (listo|creado|disponible)"
        r"|\bi('ve| have) (created|prepared|generated|written)\b[^.?!]{0,60}\b(report|document|summary)"),
    "crear_grafica": re.compile(
        r"\bte la (muestro|enseno)\b|\baqui tienes (la|una) grafica"
        r"|\b(he|te he|ya he) (creado|generado|hecho|preparado|dibujado) (una|la|esta) grafica"),
}

# Aviso privado a la IA cuando afirma algo que no ha hecho
_CORRECCION = {
    "crear_documento": ("(Aviso interno, no lo menciones: has dicho que has creado el documento, pero no has "
                        "llamado a crear_documento, así que no existe. Llama ahora a crear_documento con el texto "
                        "completo en Markdown y después confirma en una frase que ya está.)"),
    "crear_grafica": ("(Aviso interno, no lo menciones: has dicho que muestras una gráfica, pero no has llamado "
                      "a crear_grafica, así que no se ve nada. Llama ahora a crear_grafica y después comenta "
                      "en una frase lo que se ve.)"),
}


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
        # Citas: cada respuesta de la IA es un "turno" numerado; sus citas llevan ese número
        self._turno = 1
        self._num_cita = 0
        self._citas_turno: set = set()
        # Verificador de acciones: lo que la IA ha dicho y las herramientas que ha usado en esta pregunta
        self._dicho: list[str] = []
        self._usadas: set[str] = set()
        self._corregido = False
        self._nueva_pregunta = True

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
                            f"La sesión ha durado más de {config.MAX_MINUTOS_SESION} minutos. Vuelve a conectar."})
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
                                "Todos los modelos de Google están saturados; reintento en 30 s."})
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
                            "Límite de uso de Gemini alcanzado. Prueba de nuevo en un minuto."})
                        break
                    espera = errores.ESPERAS_LIMITE[intentos_limite]
                    intentos_limite += 1
                    await self._emitir({"tipo": "aviso", "mensaje": errores.mensaje(tipo)})
                    await asyncio.sleep(espera)
                    continue

                # red u otro: reconectar (con el handle se recupera la conversación)
                if intentos_red >= len(errores.ESPERAS_RED):
                    await self._emitir({"tipo": "error", "mensaje": f"No se pudo mantener la conexión: {e}"})
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
        tareas = {enviar, recibir, vigilar}
        try:
            hechas, _ = await asyncio.wait(tareas, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Aunque nos cancelen desde fuera, ninguna tarea queda huérfana ni con errores sin recoger
            for t in tareas:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
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
            await self._emitir({"tipo": "aviso", "mensaje": "La respuesta se ha quedado parada; reactivándola..."})
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
                self._empezar_pregunta()
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
            await self._emitir({"tipo": "interrumpido", "turno": self._turno})
            self._nuevo_turno()
        if sc.input_transcription and sc.input_transcription.text:
            if self._nueva_pregunta:
                self._empezar_pregunta()
            await self._emitir({"tipo": "transcripcion_usuario", "texto": sc.input_transcription.text})
        if sc.output_transcription and sc.output_transcription.text:
            self._dicho.append(sc.output_transcription.text)
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
            falta = self._accion_no_hecha()
            if falta:
                self._corregido = True
                log.info("La IA dijo que usó %s sin llamarla; se le pide que lo haga", falta)
                await self._emitir({"tipo": "diagnostico", "suceso": "accion_no_realizada", "herramienta": falta})
            else:
                self._nueva_pregunta = True
            await self._emitir({"tipo": "turno_completo", "turno": self._turno})
            self._nuevo_turno()
            if falta:
                await sesion.send_realtime_input(text=_CORRECCION[falta])

    def _empezar_pregunta(self) -> None:
        self._dicho, self._usadas = [], set()
        self._corregido, self._nueva_pregunta = False, False

    def _accion_no_hecha(self) -> str | None:
        """Si la IA ha dicho que ha creado un documento o una gráfica sin llamar a la herramienta,
        devuelve el nombre de esa herramienta (una sola corrección por pregunta)."""
        if not config.VERIFICAR_ACCIONES or self._corregido:
            return None
        texto = _normalizar(" ".join(self._dicho))
        for herramienta, patron in _AFIRMACIONES.items():
            if herramienta not in self._usadas and patron.search(texto):
                return herramienta
        return None

    def _nuevo_turno(self) -> None:
        self._turno += 1
        self._citas_turno = set()

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
            self._usadas.add(fc.name)
            await self._emitir({"tipo": "herramienta", "nombre": fc.name, "argumentos": argumentos})
            # En un hilo aparte: pandas o los embeddings no deben bloquear el audio
            resultado = await asyncio.to_thread(herramientas.ejecutar, fc.name, argumentos)
            if fc.name == "crear_grafica" and resultado.get("url"):
                # los datos en bruto van solo a la web (para dibujarla interactiva o como tabla), no a Gemini
                await self._emitir({"tipo": "grafica", "turno": self._turno, "titulo": resultado.get("titulo"),
                                    "url": resultado["url"], "datos": resultado.pop("datos", None)})
            resumen = json.dumps(resultado, ensure_ascii=False, default=str)
            await self._emitir({"tipo": "resultado_herramienta", "nombre": fc.name,
                                "resumen": resumen[:600] + ("…" if len(resumen) > 600 else "")})
            if fc.name == "buscar_documentos" and resultado.get("resultados"):
                fuentes = [{"fuente": r["fuente"], "pagina": r["pagina"]} for r in resultado["resultados"]]
                await self._emitir({"tipo": "fuentes", "fuentes": fuentes})
            if fc.name == "crear_documento" and resultado.get("archivos"):
                await self._emitir({"tipo": "documento_creado", "turno": self._turno,
                                    "titulo": resultado.get("titulo"), "archivos": resultado["archivos"]})
            for cita in herramientas.citas(fc.name, argumentos, resultado):
                clave = (cita.get("tipo"), cita.get("tabla") or cita.get("fuente"), cita.get("consulta"), cita.get("pagina"))
                if clave in self._citas_turno:
                    continue  # la misma fuente dos veces en una respuesta: una sola cita
                self._citas_turno.add(clave)
                self._num_cita += 1
                await self._emitir({"tipo": "cita", "turno": self._turno, "id": self._num_cita, "cita": cita})
            return types.FunctionResponse(id=fc.id, name=fc.name, response=resultado)

        # Si Gemini pide varias consultas a la vez, se ejecutan en paralelo (mismo orden en la respuesta)
        respuestas = await asyncio.gather(*(una(fc) for fc in llamadas))
        await sesion.send_tool_response(function_responses=list(respuestas))
