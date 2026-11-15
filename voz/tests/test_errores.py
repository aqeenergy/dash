"""Prueba, sin clave, cómo reacciona la sesión a los errores típicos de Gemini.

    python tests/test_errores.py
"""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import errors  # noqa: E402

from ia_llama import config, errores, servidor  # noqa: E402
from ia_llama.sesion import SesionVoz  # noqa: E402

errores.ESPERAS_LIMITE = [0.01] * 8
errores.ESPERAS_RED = [0.01] * 4
config.MODELOS_LIVE = ["principal", "reserva"]


class SesionVacia:
    async def send_realtime_input(self, **_):
        pass

    async def receive(self):
        await asyncio.sleep(3600)
        yield  # pragma: no cover


class Cliente:
    """Devuelve los errores de `guion` en orden; cuando se acaban, conecta bien."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.modelos = []
        self.aio = type("A", (), {"live": type("L", (), {"connect": self._connect})()})()

    @asynccontextmanager
    async def _connect(self, model, config):
        self.modelos.append(model)
        if self.guion:
            raise self.guion.pop(0)
        yield SesionVacia()


def api(code, texto):
    return errors.APIError(code, {"error": {"code": code, "message": texto, "status": ""}})


async def escenario(guion):
    eventos = []
    cliente = Cliente(guion)

    async def al_evento(e):
        eventos.append(e)

    async def nada(_):
        pass

    sesion = SesionVoz(nada, al_evento, cliente=cliente)
    tarea = asyncio.create_task(sesion.ejecutar())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if any(e["tipo"] in ("listo", "error") for e in eventos):
            break
    await sesion.cerrar()
    await asyncio.wait_for(tarea, 2)
    return [(e["tipo"], e.get("modelo") or e.get("mensaje", "")[:45]) for e in eventos], cliente.modelos


def comprobar(nombre, obtenido, esperado_tipos, esperado_modelos):
    eventos, modelos = obtenido
    tipos = [t for t, _ in eventos]
    ok = tipos == esperado_tipos and modelos == esperado_modelos
    print(("OK   " if ok else "FALLO"), nombre, "|", eventos, "|", modelos)
    assert ok


async def main():
    comprobar("modelo renombrado -> reserva",
              await escenario([api(1008, "models/principal is not found for API version v1beta")]),
              ["aviso", "listo"], ["principal", "reserva"])
    comprobar("clave mala -> error sin reintentar",
              await escenario([api(1007, "API key not valid. Please pass a valid API key.")]),
              ["error"], ["principal"])
    comprobar("429 por minuto -> espera y reintenta el mismo",
              await escenario([api(429, "RESOURCE_EXHAUSTED quota"), api(429, "RESOURCE_EXHAUSTED quota")]),
              ["aviso", "aviso", "listo"], ["principal"] * 3)
    comprobar("saturado -> reserva sin esperar",
              await escenario([api(1011, "The model is overloaded. Please try again later.")]),
              ["aviso", "listo"], ["principal", "reserva"])
    comprobar("cuota diaria en todos -> error claro",
              await escenario([api(429, "Quota exceeded: GenerateRequestsPerDay")] * 2),
              ["aviso", "error"], ["principal", "reserva"])
    comprobar("conexión caída -> reconecta",
              await escenario([api(1006, "Abnormal closure.")]),
              ["reconectando", "listo"], ["principal", "principal"])

    # Inactividad: no reconecta hasta que llega la siguiente pregunta, y entonces la envía
    eventos, enviados = [], []

    class SesionQueGuarda(SesionVacia):
        async def send_realtime_input(self, **kw):
            enviados.append(kw.get("text"))

    class ClienteInactivo(Cliente):
        @asynccontextmanager
        async def _connect(self, model, config):
            self.modelos.append(model)
            if self.guion:
                raise self.guion.pop(0)
            yield SesionQueGuarda()

    cli = ClienteInactivo([api(1008, "Session closed due to client inactivity.")])

    async def al_ev(e):
        eventos.append(e["tipo"])

    async def nada(_):
        pass

    ses = SesionVoz(nada, al_ev, cliente=cli)
    tarea = asyncio.create_task(ses.ejecutar())
    await asyncio.sleep(0.3)
    conexiones_en_pausa = len(cli.modelos)
    await ses.enviar_texto("segunda pregunta")
    await asyncio.sleep(0.3)
    await ses.cerrar()
    await asyncio.wait_for(tarea, 2)
    ok = (eventos == ["en_pausa", "listo"] and conexiones_en_pausa == 1
          and len(cli.modelos) == 2 and enviados == ["segunda pregunta"])
    print("OK   " if ok else "FALLO", "inactividad -> pausa y reanuda con la pregunta |", eventos, enviados)
    assert ok

    # Respuesta atascada: Gemini empieza a responder y se calla; el toque la reactiva
    config.SEGUNDOS_ATASCO = 0.4
    from types import SimpleNamespace as NS

    def parcial(texto, fin=False, generado=False):
        sc = NS(interrupted=False, input_transcription=None, output_transcription=NS(text=texto),
                model_turn=None, turn_complete=fin, generation_complete=generado)
        return NS(tool_call=None, server_content=sc, session_resumption_update=None, go_away=None)

    class SesionAtascada:
        def __init__(self, responde_al_toque):
            self.cola, self.toques, self.responde = [parcial("De media, la combustión")], [], responde_al_toque
            self.ev = asyncio.Event(); self.ev.set()

        async def send_realtime_input(self, text=None, **_):
            if text:
                self.toques.append(text)
                if self.responde:
                    self.cola.append(parcial(" de una gota fue de 13,5 s.", fin=True)); self.ev.set()

        async def receive(self):
            while True:
                await self.ev.wait(); self.ev.clear()
                while self.cola:
                    yield self.cola.pop(0)

    for responde, esperado in ((True, "toque"), (False, "reconexion")):
        sesiones = []

        class ClienteAtasco(Cliente):
            @asynccontextmanager
            async def _connect(self, model, config):
                self.modelos.append(model)
                sesiones.append(SesionAtascada(responde))
                yield sesiones[-1]

        evs = []

        async def guarda(e):
            evs.append(e["tipo"])

        cli = ClienteAtasco([])
        ses = SesionVoz(nada, guarda, cliente=cli)
        tarea = asyncio.create_task(ses.ejecutar())
        await asyncio.sleep(3.5 if not responde else 1.5)
        await ses.cerrar()
        await asyncio.wait_for(tarea, 3)
        if esperado == "toque":
            ok = "turno_completo" in evs and sesiones[0].toques and len(cli.modelos) == 1
        else:
            ok = len(sesiones[0].toques) == 2 and "reconectando" in evs and len(cli.modelos) >= 2
        print("OK   " if ok else "FALLO", f"respuesta atascada -> {esperado} |",
              [e for e in evs if e != "transcripcion_ia"], "| toques:", len(sesiones[0].toques))
        assert ok
    # Respuesta ya generada (generation_complete) cuyo "turno completo" tarda: NO es un atasco
    class SesionLenta(SesionAtascada):
        def __init__(self):
            super().__init__(False)
            self.cola = [parcial("Respuesta completa.", generado=True)]

        async def receive(self):
            async for m in super().receive():
                yield m
                await asyncio.sleep(1.5)          # el turno completo llega mucho después
                yield parcial("", fin=True)

    lentas, evs = [], []

    class ClienteLento(Cliente):
        @asynccontextmanager
        async def _connect(self, model, config):
            self.modelos.append(model)
            lentas.append(SesionLenta())
            yield lentas[-1]

    async def guarda2(e):
        evs.append(e["tipo"])

    ses = SesionVoz(nada, guarda2, cliente=ClienteLento([]))
    tarea = asyncio.create_task(ses.ejecutar())
    await asyncio.sleep(2.2)
    await ses.cerrar()
    await asyncio.wait_for(tarea, 3)
    ok = "turno_completo" in evs and not lentas[0].toques and "diagnostico" not in evs
    print("OK   " if ok else "FALLO", "respuesta ya generada con turno lento -> sin toque |",
          [e for e in evs if e != "transcripcion_ia"])
    assert ok
    # Sin generation_complete, pero con audio largo aún sonando: tampoco es un atasco
    def con_audio(segundos):
        sc = NS(interrupted=False, input_transcription=None, output_transcription=NS(text="Hola."),
                model_turn=NS(parts=[NS(inline_data=NS(data=b"\x00\x00" * int(24000 * segundos)))]),
                turn_complete=False, generation_complete=False)
        return NS(tool_call=None, server_content=sc, session_resumption_update=None, go_away=None)

    class SesionAudioLargo(SesionAtascada):
        def __init__(self):
            super().__init__(False)
            self.cola = [con_audio(1.2)]

        async def receive(self):
            async for m in super().receive():
                yield m
                await asyncio.sleep(1.3)          # Gemini avisa del fin cuando acaba de sonar
                yield parcial("", fin=True)

    largas, evs3 = [], []

    class ClienteAudio(Cliente):
        @asynccontextmanager
        async def _connect(self, model, config):
            self.modelos.append(model)
            largas.append(SesionAudioLargo())
            yield largas[-1]

    async def guarda3(e):
        evs3.append(e["tipo"])

    async def nada_audio(_):
        pass

    ses = SesionVoz(nada_audio, guarda3, cliente=ClienteAudio([]))
    tarea = asyncio.create_task(ses.ejecutar())
    await asyncio.sleep(2.0)
    await ses.cerrar()
    await asyncio.wait_for(tarea, 3)
    ok = "turno_completo" in evs3 and not largas[0].toques
    print("OK   " if ok else "FALLO", "audio largo sin generation_complete -> sin toque |",
          [e for e in evs3 if e != "transcripcion_ia"])
    assert ok
    config.SEGUNDOS_ATASCO = 10

    # Servidor lleno
    from fastapi.testclient import TestClient
    config.GEMINI_API_KEY = "clave-falsa"
    config.MAX_SESIONES_SIMULTANEAS = 0
    with TestClient(servidor.app).websocket_connect("/ws/voz") as ws:
        ev = json.loads(ws.receive_text())
    print("OK   " if "demasiadas" in ev["mensaje"] else "FALLO", "servidor lleno ->", ev)
    assert "demasiadas" in ev["mensaje"]
    print("\nTodas las pruebas de errores pasan")


if __name__ == "__main__":
    asyncio.run(main())
