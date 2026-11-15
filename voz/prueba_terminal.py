"""Habla con la IA desde la terminal, sin la web. Usad AURICULARES: si el altavoz se cuela
por el micro, la IA se oye a sí misma y se interrumpe.

    python prueba_terminal.py            # voz (micrófono + altavoz)
    python prueba_terminal.py --texto    # escribes las preguntas y la IA responde con voz
                                         # (útil si el micro da problemas)
    python prueba_terminal.py --grabar   # guarda la conversación en grabaciones/ para analizarla
                                         # (se puede combinar: --texto --grabar)
Ctrl+C para salir.
"""
import argparse
import asyncio
import json
import sys
import threading

import sounddevice as sd

from ia_llama import config, herramientas
from ia_llama.grabadora import Grabadora
from ia_llama.sesion import SesionVoz


class Altavoz:
    """Reproduce el audio de la IA y lo vacía al instante si la interrumpes."""

    def __init__(self):
        self.buffer = bytearray()
        self.stream = sd.RawOutputStream(
            samplerate=config.FRECUENCIA_SALIDA, channels=1, dtype="int16", callback=self._callback
        )

    def _callback(self, salida, frames, _tiempo, _estado):
        n = len(salida)
        trozo = self.buffer[:n]
        del self.buffer[:n]
        salida[:len(trozo)] = trozo
        salida[len(trozo):] = b"\x00" * (n - len(trozo))

    def vaciar(self):
        self.buffer.clear()


async def main(modo_texto: bool, grabar: bool):
    herramientas.precargar()  # tablas e índice listos antes de la primera pregunta
    if not config.GEMINI_API_KEY:
        sys.exit("Falta GEMINI_API_KEY (ponla en el archivo .env)")

    grabadora = Grabadora() if grabar else None
    if grabadora:
        print(f"⏺  Grabando en {grabadora.carpeta}")
    altavoz = Altavoz()
    linea_ia = {"abierta": False}

    async def al_audio(pcm: bytes):
        altavoz.buffer.extend(pcm)
        if grabadora:
            grabadora.audio_ia(pcm)

    async def al_evento(ev: dict):
        if grabadora:
            grabadora.evento(ev)
        tipo = ev["tipo"]
        if tipo == "transcripcion_ia":
            if not linea_ia["abierta"]:
                print("\n🔥 IA: ", end="")
                linea_ia["abierta"] = True
            print(ev["texto"], end="", flush=True)
        elif tipo == "transcripcion_usuario":
            print(f"\n🎤 Tú: {ev['texto']}", end="", flush=True)
        elif tipo == "herramienta":
            print(f"\n   🔎 {ev['nombre']}({json.dumps(ev['argumentos'], ensure_ascii=False)})", flush=True)
        elif tipo == "fuentes":
            print("   📄 " + ", ".join(f"{f['fuente']} p.{f['pagina']}" for f in ev["fuentes"]), flush=True)
        elif tipo == "interrumpido":
            altavoz.vaciar()
            print("  [interrumpida]", flush=True)
        elif tipo == "turno_completo":
            linea_ia["abierta"] = False
            print(flush=True)
        elif tipo in ("listo", "en_pausa", "reconectando", "resultado_herramienta", "diagnostico"):
            pass  # conexión gestionada sola; no hace falta mostrarlo
        else:  # aviso o error
            print(f"\n⚠️  {ev.get('mensaje', tipo)}", flush=True)

    sesion = SesionVoz(al_audio, al_evento)
    tarea = asyncio.create_task(sesion.ejecutar())
    altavoz.stream.start()
    bucle = asyncio.get_running_loop()

    try:
        if modo_texto:
            print("Escribe tu pregunta y pulsa Enter (Ctrl+C para salir).")
            lineas: asyncio.Queue = asyncio.Queue()

            def leer_teclado():  # hilo "daemon": no bloquea la salida con Ctrl+C
                while True:
                    try:
                        linea = input("\n> ")
                    except EOFError:
                        return
                    bucle.call_soon_threadsafe(lineas.put_nowait, linea)

            threading.Thread(target=leer_teclado, daemon=True).start()
            while True:
                texto = await lineas.get()
                if texto.strip():
                    if grabadora:
                        grabadora.texto_usuario(texto.strip())
                    await sesion.enviar_texto(texto.strip())
        else:
            def al_micro(datos, _frames, _tiempo, _estado):
                trozo = bytes(datos)
                if grabadora:
                    grabadora.audio_microfono(trozo)
                bucle.call_soon_threadsafe(asyncio.create_task, sesion.enviar_audio(trozo))

            with sd.RawInputStream(samplerate=config.FRECUENCIA_ENTRADA, channels=1, dtype="int16",
                                   blocksize=1600, callback=al_micro):  # trozos de 100 ms
                print("🎙️  Habla cuando quieras (Ctrl+C para salir)...")
                await tarea
    finally:
        await sesion.cerrar()
        altavoz.stream.stop()
        if grabadora:
            print(f"\n💾 Conversación guardada en {grabadora.cerrar()}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--texto", action="store_true")
    p.add_argument("--grabar", action="store_true")
    a = p.parse_args()
    try:
        asyncio.run(main(a.texto, a.grabar))
    except KeyboardInterrupt:
        print("\nHasta luego 👋")
