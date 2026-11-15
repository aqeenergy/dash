"""Graba una conversación para analizarla después.

Crea grabaciones/AAAAMMDD-HHMMSS/ con:
    conversacion.md   cronología legible: lo que dijiste, las consultas de la IA con su resultado,
                      lo que respondió y cuánto tardó en empezar a hablar
    eventos.jsonl     todos los eventos con su instante (para análisis automático)
    microfono.wav     tu audio (16 kHz)
    ia.wav            la voz de la IA (24 kHz), colocada en el momento en que sonó
    conversacion.wav  las dos voces mezcladas, para escuchar o compartir la conversación entera
"""
from __future__ import annotations

import json
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config


class Grabadora:
    def __init__(self, directorio: Path | None = None):
        base = directorio or (config.RAIZ / "grabaciones")
        self.carpeta = base / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.t0 = time.monotonic()
        self._eventos = open(self.carpeta / "eventos.jsonl", "w", encoding="utf-8")
        self._md = open(self.carpeta / "conversacion.md", "w", encoding="utf-8")
        self._mic = self._wav("microfono.wav", config.FRECUENCIA_ENTRADA)
        self._ia = self._wav("ia.wav", config.FRECUENCIA_SALIDA)
        self._muestras_ia = 0  # posición actual de ia.wav, para alinearla con el tiempo real
        self._turno_ia = ""
        self._turno_usuario = ""
        self._fin_usuario: float | None = None  # último fragmento transcrito de la persona
        self._primera_voz: float | None = None
        self._md.write(f"# Conversación {self.carpeta.name}\n\n"
                       f"Modelos: {', '.join(config.MODELOS_LIVE)}\n\n")

    def _wav(self, nombre: str, frecuencia: int):
        w = wave.open(str(self.carpeta / nombre), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(frecuencia)
        return w

    def _t(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def _linea(self, texto: str) -> None:
        self._md.write(texto + "\n")
        self._md.flush()

    # ---------------------------------------------------------------- entradas
    def audio_microfono(self, pcm: bytes) -> None:
        self._mic.writeframes(pcm)

    def audio_ia(self, pcm: bytes) -> None:
        if self._primera_voz is None:
            self._primera_voz = self._t()
        # Si la IA estuvo callada, rellenar con silencio hasta "ahora" para que ia.wav siga el reloj real
        ahora = int((time.monotonic() - self.t0) * config.FRECUENCIA_SALIDA)
        if ahora > self._muestras_ia:
            self._ia.writeframes(b"\x00\x00" * (ahora - self._muestras_ia))
            self._muestras_ia = ahora
        self._ia.writeframes(pcm)
        self._muestras_ia += len(pcm) // 2

    def texto_usuario(self, texto: str) -> None:
        self._registrar({"tipo": "texto_escrito", "texto": texto})
        self._linea(f"\n**[{self._t():.1f} s] ⌨️ Tú (escrito):** {texto}")
        self._fin_usuario = self._t()
        self._primera_voz = None

    def evento(self, ev: dict) -> None:
        self._registrar(ev)
        tipo = ev["tipo"]
        if tipo == "transcripcion_usuario":
            self._volcar_ia()
            self._turno_usuario += ev["texto"]
            self._fin_usuario = self._t()
            self._primera_voz = None  # la latencia se mide desde la última palabra de la persona
        elif tipo == "herramienta":
            self._volcar_usuario()
            self._linea(f"- [{self._t():.1f} s] 🔎 `{ev['nombre']}({json.dumps(ev['argumentos'], ensure_ascii=False)})`")
        elif tipo == "resultado_herramienta":
            self._linea(f"  - resultado: `{ev['resumen']}`")
        elif tipo == "transcripcion_ia":
            self._volcar_usuario()
            self._turno_ia += ev["texto"]
        elif tipo == "interrumpido":
            self._linea(f"- [{self._t():.1f} s] ✋ interrumpida")
            self._volcar_ia()
        elif tipo == "turno_completo":
            self._volcar_usuario()
            self._volcar_ia()
        elif tipo == "diagnostico":
            detalle = ", ".join(f"{k}={v}" for k, v in ev.items() if k != "tipo")
            self._linea(f"- [{self._t():.1f} s] 🩺 diagnóstico: {detalle}")
        elif tipo in ("aviso", "error"):
            self._linea(f"- [{self._t():.1f} s] ⚠️ {tipo}: {ev.get('mensaje', '')}")

    # ---------------------------------------------------------------- interno
    def _registrar(self, ev: dict) -> None:
        self._eventos.write(json.dumps({"t": self._t(), **ev}, ensure_ascii=False, default=str) + "\n")
        self._eventos.flush()

    def _volcar_usuario(self) -> None:
        if self._turno_usuario.strip():
            self._linea(f"\n**[{self._t():.1f} s] 🎤 Tú:** {self._turno_usuario.strip()}")
            self._turno_usuario = ""

    def _volcar_ia(self) -> None:
        if self._turno_ia.strip():
            latencia = ""
            if self._fin_usuario is not None and self._primera_voz is not None:
                latencia = f" _(empezó a hablar {self._primera_voz - self._fin_usuario:.1f} s después)_"
            self._linea(f"\n**[{self._t():.1f} s] 🔥 IA:**{latencia} {self._turno_ia.strip()}")
            self._turno_ia = ""
            self._primera_voz = None

    def cerrar(self) -> Path:
        self._volcar_usuario()
        self._volcar_ia()
        self._linea(f"\n---\nDuración total: {self._t():.0f} s")
        for f in (self._mic, self._ia):
            f.close()
        self._eventos.close()
        self._md.close()
        try:
            self._mezclar()
        except Exception as e:  # la mezcla es un extra: nunca debe impedir guardar lo demás
            print(f"(no se pudo crear conversacion.wav: {e})")
        return self.carpeta

    def _mezclar(self) -> None:
        """conversacion.wav = micro (pasado a 24 kHz) + voz de la IA, normalizado."""
        def leer(nombre):
            with wave.open(str(self.carpeta / nombre)) as w:
                return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32), w.getframerate()

        mic, r_mic = leer("microfono.wav")
        ia, r = leer("ia.wav")
        if len(mic):
            mic = np.interp(np.arange(int(len(mic) * r / r_mic)) * r_mic / r, np.arange(len(mic)), mic)
        n = max(len(mic), len(ia))
        mezcla = np.pad(ia, (0, n - len(ia))) + np.pad(mic, (0, n - len(mic))) * 1.6
        if n:
            mezcla *= 30000 / max(1.0, float(np.max(np.abs(mezcla))))
        with wave.open(str(self.carpeta / "conversacion.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(r)
            w.writeframes(mezcla.astype(np.int16).tobytes())
