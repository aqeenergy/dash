"""Prueba real con Gemini Live SIN micrófono ni altavoz: envía una pregunta escrita, muestra
las herramientas que usa la IA y su respuesta, y guarda la voz en respuesta.wav.

    python prueba_rapida.py
    python prueba_rapida.py "¿Qué combustible ardió más rápido en FLEX?"
"""
import asyncio
import json
import sys
import time
import wave

from ia_llama import config, herramientas
from ia_llama.sesion import SesionVoz

PREGUNTA = " ".join(sys.argv[1:]) or "¿Qué combustible ardió más rápido en el experimento FLEX? Dame la cifra."


async def main() -> None:
    herramientas.precargar()  # tablas e índice listos antes de la primera pregunta
    if not config.GEMINI_API_KEY:
        sys.exit("❌ Falta GEMINI_API_KEY en ia_voz_texto/.env")
    print(f"Modelos: {', '.join(config.MODELOS_LIVE)}\nPregunta: {PREGUNTA}\n")
    audio = bytearray()
    fin = asyncio.Event()
    t0 = time.time()
    primera_voz = None

    async def al_audio(pcm: bytes) -> None:
        nonlocal primera_voz
        if primera_voz is None:
            primera_voz = time.time() - t0
        audio.extend(pcm)

    async def al_evento(ev: dict) -> None:
        t = ev["tipo"]
        if t == "listo":
            print(f"✅ Conectado con Gemini Live ({ev['modelo']})")
            await sesion.enviar_texto(PREGUNTA)
        elif t == "herramienta":
            print(f"🔎 {ev['nombre']}({json.dumps(ev['argumentos'], ensure_ascii=False)})")
        elif t == "fuentes":
            print("📄 " + ", ".join(f["fuente"] for f in ev["fuentes"]))
        elif t == "transcripcion_ia":
            print(ev["texto"], end="", flush=True)
        elif t == "turno_completo":
            fin.set()
        elif t in ("aviso", "reconectando"):
            print(f"⚠️  {ev.get('mensaje', 'reconectando...')}")
        elif t == "error":
            print(f"\n❌ {ev['mensaje']}")
            fin.set()

    sesion = SesionVoz(al_audio, al_evento)
    tarea = asyncio.create_task(sesion.ejecutar())
    try:
        await asyncio.wait_for(fin.wait(), timeout=90)
    except asyncio.TimeoutError:
        print("\n❌ Sin respuesta en 90 s")
    await sesion.cerrar()
    tarea.cancel()

    print("\n")
    if audio:
        with wave.open("respuesta.wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(config.FRECUENCIA_SALIDA)
            w.writeframes(bytes(audio))
        dur = len(audio) / 2 / config.FRECUENCIA_SALIDA
        print(f"✅ Voz: {dur:.1f} s guardados en respuesta.wav (primera voz a los {primera_voz:.1f} s)")
    else:
        print("❌ No llegó audio")


if __name__ == "__main__":
    asyncio.run(main())
