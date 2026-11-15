"""Pruebas del verificador de acciones y del cierre limpio de la sesión (sin clave de API).

    python tests/test_verificador.py
"""
import asyncio
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ia_llama import config  # noqa: E402
from ia_llama.sesion import SesionVoz  # noqa: E402

resultados = []


def comprobar(nombre, ok, detalle=""):
    resultados.append(ok)
    print(("OK   " if ok else "FALLO"), nombre, ("| " + str(detalle)) if detalle else "")


def _mensaje(texto=None, fin=True, llamada=None):
    sc = None
    if texto is not None:
        sc = NS(interrupted=False, input_transcription=None, output_transcription=NS(text=texto),
                model_turn=None, turn_complete=fin, generation_complete=fin)
    return NS(tool_call=NS(function_calls=[llamada]) if llamada else None, server_content=sc,
              session_resumption_update=None, go_away=None)


class GeminiFalso:
    """Simula una IA que dice haber creado un informe sin llamar a la herramienta (si mentirosa=True)."""

    def __init__(self, mentirosa):
        self.mentirosa = mentirosa
        self.textos = []
        self.cola = asyncio.Queue()

    async def send_realtime_input(self, audio=None, text=None, audio_stream_end=None):
        if not text:
            return
        self.textos.append(text)
        llamada = NS(id="1", name="crear_documento",
                     args={"titulo": "Informe Saffire", "contenido": "# Informe\n\nTexto.\n\n## Fuentes\n- PSI-98"})
        if self.mentirosa and len(self.textos) == 1:
            await self.cola.put(_mensaje("De acuerdo, he creado un informe breve con los resultados de Saffire."))
        else:
            await self.cola.put(_mensaje(llamada=llamada))

    async def send_tool_response(self, function_responses):
        await self.cola.put(_mensaje("Ya está: tienes el informe para descargar."))

    async def receive(self):
        while True:
            yield await self.cola.get()


class Cliente:
    def __init__(self, gemini):
        self.gemini = gemini
        self.aio = NS(live=NS(connect=self._connect))

    @asynccontextmanager
    async def _connect(self, model, config):
        yield self.gemini


async def conversar(mentirosa):
    gemini = GeminiFalso(mentirosa)
    eventos = []
    hecho = asyncio.Event()

    async def al_evento(ev):
        eventos.append(ev)
        if ev["tipo"] == "listo":
            await sesion.enviar_texto("Crea un informe breve de Saffire")
        if ev["tipo"] == "documento_creado":
            hecho.set()

    async def al_audio(_):
        pass

    sesion = SesionVoz(al_audio, al_evento, cliente=Cliente(gemini))
    tarea = asyncio.create_task(sesion.ejecutar())
    try:
        await asyncio.wait_for(hecho.wait(), 5)
    except asyncio.TimeoutError:
        pass
    await asyncio.sleep(0.2)
    await sesion.cerrar()
    await asyncio.wait_for(tarea, 5)
    return gemini, eventos


async def main():
    with tempfile.TemporaryDirectory() as d:
        config.DIR_GENERADOS = Path(d)

        # 1. La IA dice "he creado un informe" sin llamar a crear_documento -> se le pide que lo haga
        gemini, eventos = await conversar(mentirosa=True)
        tipos = [e["tipo"] for e in eventos]
        diag = [e for e in eventos if e.get("suceso") == "accion_no_realizada"]
        comprobar("detecta la afirmación falsa", len(diag) == 1 and diag[0]["herramienta"] == "crear_documento", diag)
        comprobar("le envía el aviso privado", len(gemini.textos) == 2 and "crear_documento" in gemini.textos[1],
                  gemini.textos[1:] or "sin aviso")
        comprobar("al final el documento existe", "documento_creado" in tipos)
        comprobar("el aviso llega antes de su turno_completo", tipos.index("diagnostico") < tipos.index("turno_completo"))

        # 2. Si la IA sí llama a la herramienta, no hay aviso
        gemini, eventos = await conversar(mentirosa=False)
        comprobar("sin afirmación falsa no hay aviso",
                  not any(e.get("suceso") == "accion_no_realizada" for e in eventos) and len(gemini.textos) == 1)

        # 3. Desactivable
        config.VERIFICAR_ACCIONES = False
        gemini, eventos = await conversar(mentirosa=True)
        comprobar("VERIFICAR_ACCIONES=0 lo desactiva", len(gemini.textos) == 1)
        config.VERIFICAR_ACCIONES = True

    # 4. Cancelar la sesión desde fuera no deja tareas huérfanas (antes: "Task exception was never retrieved")
    gemini = GeminiFalso(mentirosa=False)

    async def nada(_):
        pass

    antes = len(asyncio.all_tasks())
    sesion = SesionVoz(nada, nada, cliente=Cliente(gemini))
    tarea = asyncio.create_task(sesion.ejecutar())
    await asyncio.sleep(0.2)
    tarea.cancel()
    await asyncio.gather(tarea, return_exceptions=True)
    await asyncio.sleep(0.1)
    comprobar("cancelar no deja tareas vivas", len(asyncio.all_tasks()) == antes, len(asyncio.all_tasks()) - antes)


asyncio.run(main())
print(f"\n{sum(resultados)}/{len(resultados)} pruebas correctas")
sys.exit(0 if all(resultados) else 1)
