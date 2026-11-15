"""Prueba de extremo a extremo SIN clave de API: sustituye Gemini por un falso que pide una
herramienta y luego responde con audio. Comprueba el puente WebSocket, las herramientas y el
orden de los eventos.

    python tests/test_simulado.py
"""
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from ia_llama import servidor  # noqa: E402


class SesionFalsa:
    def __init__(self):
        self.audio_recibido = 0
        self.cola = []
        import asyncio
        self.evento = asyncio.Event()

    async def send_realtime_input(self, audio=None, text=None, audio_stream_end=None):
        if audio is not None:
            self.audio_recibido += len(audio.data)
        if text:  # la "IA" decide consultar las tablas
            self.cola.append(NS(tool_call=NS(function_calls=[NS(id="1", name="listar_tablas", args={})]),
                                server_content=None, session_resumption_update=None, go_away=None))
            self.evento.set()

    async def send_tool_response(self, function_responses):
        assert function_responses[0].name == "listar_tablas"
        partes = [NS(inline_data=NS(data=b"\x01\x00" * 480))]
        sc = NS(interrupted=False, input_transcription=None, output_transcription=NS(text="Tengo una tabla."),
                model_turn=NS(parts=partes), turn_complete=True)
        self.cola.append(NS(tool_call=None, server_content=sc, session_resumption_update=None, go_away=None))
        self.evento.set()

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


def main():
    servidor.config.GEMINI_API_KEY = "clave-falsa"
    servidor.SesionVoz.__init__.__defaults__ = (ClienteFalso(),)  # inyecta el cliente falso
    with TestClient(servidor.app).websocket_connect("/ws/voz") as ws:
        assert json.loads(ws.receive_text())["tipo"] == "listo"
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_text(json.dumps({"tipo": "texto", "texto": "¿Qué datos tienes?"}))
        vistos = []
        while "turno_completo" not in vistos:
            m = ws.receive()
            vistos.append("AUDIO" if m.get("bytes") else json.loads(m["text"])["tipo"])
    print("Eventos recibidos:", vistos)
    assert vistos == ["herramienta", "resultado_herramienta", "transcripcion_ia", "AUDIO", "turno_completo"], vistos
    print("OK: puente WebSocket, herramientas y eventos funcionan")


if __name__ == "__main__":
    main()
