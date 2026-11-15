"""Banco de pruebas con Gemini real: hace preguntas con respuesta conocida y comprueba si la IA acierta.

    python evaluar.py                 # todas las preguntas (unos 8-10 minutos)
    python evaluar.py flex saffire    # solo las que contengan esas palabras en su id
    python evaluar.py --rapido        # sin las preguntas que crean archivos (documento y gráfica)
    python evaluar.py ensayo --repetir 3   # cada pregunta 3 veces (la IA no responde siempre igual)

Cada pregunta se hace en una conversación nueva. Se comprueba:
  - texto:        lo que dice la IA (acepta cifras escritas con números o con letras)
  - herramientas: que haya usado la consulta adecuada
  - citas:        que haya consultado el experimento correcto (accesión PSI de las citas)
  - eventos:      que la web reciba la gráfica o el documento creado
El informe completo se guarda en evaluaciones/AAAAMMDD-HHMMSS.json (no se sube a GitHub).
"""
import asyncio
import json
import re
import sys
import time
import unicodedata
from datetime import datetime

from ia_llama import config, herramientas
from ia_llama.sesion import SesionVoz

# id, pregunta, comprobaciones. En "texto", cada elemento es una alternativa (regex) que debe aparecer;
# si hay varios elementos, deben aparecer todos.
PREGUNTAS = [
    ("flex_ensayos", "¿Cuántos ensayos hay en el experimento FLEX?",
     {"texto": [r"274|doscientos setenta y cuatro"], "citas": ["PSI-69"]}),
    ("flex_combustibles", "¿Qué combustibles se usaron en FLEX?",
     {"texto": [r"heptano|heptane", r"metanol|methanol"]}),
    ("flex_mas_rapido", "¿Qué combustible ardió más rápido en el experimento FLEX? Dame la cifra.",
     {"texto": [r"heptano|heptane", r"0[,.]5[45]|cincuenta y (cuatro|cinco)"],
      "herramientas": ["estadisticas_tabla"], "citas": ["PSI-69"]}),
    ("flex_metanol_duracion", "En FLEX, ¿cuánto duró de media la combustión de una gota de metanol?",
     {"texto": [r"13[,.]5|trece coma cinco|trece y medio|13 y medio|13[,.]51"], "citas": ["PSI-69"]}),
    ("flex_extinciones", "¿En cuántos ensayos de FLEX la llama se apagó antes de consumir la gota?",
     {"texto": [r"186|ciento ochenta y seis"], "citas": ["PSI-69"]}),
    ("saffire_lugar", "¿Dónde se hicieron los experimentos Saffire?",
     {"texto": [r"cygnus"]}),
    ("saffire_material_mas_tiempo", "En Saffire dos, ¿qué material ardió durante más tiempo?",
     {"texto": [r"pmma|metacrilato|plexiglas"], "citas": ["PSI-99"]}),
    ("spice_doi", "Dame el DOI del experimento SPICE.",
     {"texto": [r"60555|seis cero cinco cinco cinco", r"9kbh|9 ?k ?b ?h|nueve.{0,6}k.{0,6}b.{0,6}h",
                r"e962|e ?9 ?6 ?2|nueve seis dos"], "citas": ["PSI-107"]}),
    ("llama_fria", "¿Qué es una llama fría y en qué experimento se estudió?",
     {"texto": [r"cfi|cool flame|llamas? fr[ií]as?"]}),
    ("trampa_marte", "¿Qué resultados dio el experimento de combustión en Marte?",
     {"texto": [r"no (tengo|hay|dispongo|encuentro|existe|aparece|consta|conozco)|no se (ha|han) (realizado|hecho|llevado)|ningun"]}),
    ("trampa_ensayo_500", "¿A qué temperatura exacta se apagó la llama en el ensayo 500 de FLEX?",
     {"texto": [r"274|doscientos setenta y cuatro|no (existe|hay ningun|aparece|consta|figura|llega)|solo (hay|tiene)"
                r"|no (tengo|hay|dispongo de|encuentro) (datos|informacion|registros?|constancia) (de|del|sobre|de ningun)( un| ese| el)? ensayo"]}),
    ("seguridad_emergencia", "Hay humo saliendo de un panel de la estación, ¿qué hago?",
     {"texto": [r"procedimiento|tripulaci|control de mision|protocolo"]}),
    ("fisica_general", "¿Por qué una llama es redonda en microgravedad?",
     {"texto": [r"flotabilidad|convecci|difusi"]}),
    ("ingles", "What was the FLEX experiment about?",
     {"ingles": True}),
    ("escenario_algodon", "¿Qué pasaría si ardiera una tela de algodón con aire normal y una ventilación de 20 centímetros por segundo?",
     {"herramientas": ["evaluar_escenario"], "citas": ["PSI-98|PSI-99"]}),
    ("grafica", "Enséñame una gráfica de la tasa de combustión media de cada combustible en FLEX.",
     {"herramientas": ["crear_grafica"], "eventos": ["grafica"], "crea_archivos": True}),
    ("documento", "Crea un informe breve con los resultados principales de los experimentos Saffire.",
     {"herramientas": ["crear_documento"], "eventos": ["documento_creado"], "crea_archivos": True}),
]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


async def preguntar(pregunta: str, limite: float = 120) -> dict:
    eventos, herramientas_usadas, citas, llamadas = [], [], [], []
    texto = []
    correcciones = 0  # veces que el verificador tuvo que pedirle a la IA que hiciera lo que dijo
    fin = asyncio.Event()
    t0 = time.monotonic()
    primera_voz = None

    async def al_audio(_):
        nonlocal primera_voz
        if primera_voz is None:
            primera_voz = time.monotonic() - t0

    turnos = 0

    async def al_evento(ev):
        nonlocal correcciones, turnos
        tipo = ev["tipo"]
        eventos.append(tipo)
        if tipo == "listo":
            await sesion.enviar_texto(pregunta)
        elif tipo == "transcripcion_ia":
            texto.append(ev["texto"])
        elif tipo == "herramienta":
            herramientas_usadas.append(ev["nombre"])
            llamadas.append({"nombre": ev["nombre"], "argumentos": ev.get("argumentos")})
        elif tipo == "resultado_herramienta":
            for ll in llamadas:
                if ll["nombre"] == ev["nombre"] and "resultado" not in ll:
                    ll["resultado"] = ev.get("resumen")
                    break
        elif tipo == "cita":
            citas.append(ev["cita"].get("accesion") or ev["cita"].get("fuente"))
        elif tipo == "diagnostico" and ev.get("suceso") == "accion_no_realizada":
            correcciones += 1  # habrá un turno más: la IA rectifica
        elif tipo == "turno_completo":
            turnos += 1
            if turnos > correcciones:  # tras cada corrección se espera la respuesta rectificada
                fin.set()
        elif tipo == "error":
            fin.set()

    sesion = SesionVoz(al_audio, al_evento)
    tarea = asyncio.create_task(sesion.ejecutar())
    try:
        await asyncio.wait_for(fin.wait(), limite)
        agotado = False
    except asyncio.TimeoutError:
        agotado = True
    await sesion.cerrar()
    try:  # cierre limpio; si se resiste, se cancela
        await asyncio.wait_for(tarea, 5)
    except (asyncio.TimeoutError, Exception):
        tarea.cancel()
    return {"respuesta": "".join(texto).strip(), "herramientas": herramientas_usadas, "citas": citas,
            "correcciones": correcciones, "llamadas": llamadas,
            "eventos": sorted(set(eventos)), "primera_voz_s": round(primera_voz, 1) if primera_voz else None,
            "tiempo_total_s": round(time.monotonic() - t0, 1), "sin_respuesta": agotado}


def comprobar(r: dict, esperado: dict) -> list[str]:
    fallos = []
    if r["sin_respuesta"]:
        fallos.append("no terminó de responder a tiempo")
    texto = _norm(r["respuesta"])
    for patron in esperado.get("texto", []):
        if not re.search(_norm(patron), texto):
            fallos.append(f"el texto no contiene /{patron}/")
    if esperado.get("ingles"):
        palabras = re.findall(r"[a-z]+", texto)
        ingles = sum(w in {"the", "was", "were", "is", "of", "and", "to", "how", "in", "it"} for w in palabras)
        espanol = sum(w in {"el", "la", "los", "las", "de", "que", "y", "en", "fue", "se", "como"} for w in palabras)
        if ingles <= espanol:
            fallos.append(f"respondió en español a una pregunta en inglés ({ingles} palabras inglesas, {espanol} españolas)")
    for h in esperado.get("herramientas", []):
        if h not in r["herramientas"]:
            fallos.append(f"no usó {h} (usó: {', '.join(r['herramientas']) or 'ninguna'})")
    for patron in esperado.get("citas", []):
        if not any(c and re.search(patron, c) for c in r["citas"]):
            fallos.append(f"no consultó {patron} (citas: {', '.join(map(str, r['citas'])) or 'ninguna'})")
    for ev in esperado.get("eventos", []):
        if ev not in r["eventos"]:
            fallos.append(f"la web no recibió el evento '{ev}'")
    return fallos


async def main(filtros: list[str], rapido: bool, repetir: int = 1) -> None:
    if not config.GEMINI_API_KEY:
        sys.exit("❌ Falta GEMINI_API_KEY en ia_voz_texto/.env")
    herramientas.precargar()
    seleccion = [p for p in PREGUNTAS if (not filtros or any(f in p[0] for f in filtros))
                 and not (rapido and p[2].get("crea_archivos"))] * max(1, repetir)
    print(f"Modelo: {config.MODELOS_LIVE[0]} · {len(seleccion)} preguntas\n")
    informe, aciertos = [], 0
    for i, (ident, pregunta, esperado) in enumerate(seleccion, 1):
        print(f"[{i}/{len(seleccion)}] {ident}: {pregunta}")
        r = await preguntar(pregunta)
        fallos = comprobar(r, esperado)
        aciertos += not fallos
        estado = "✅" if not fallos else "❌"
        print(f"   {estado} {r['primera_voz_s'] or '-'} s · herramientas: {', '.join(r['herramientas']) or 'ninguna'}"
              + (" · ⚠️ el verificador tuvo que corregirla" if r["correcciones"] else ""))
        print(f"   «{r['respuesta'][:220]}{'…' if len(r['respuesta']) > 220 else ''}»")
        for f in fallos:
            print(f"   → {f}")
        if fallos:  # qué consultó y qué le devolvieron, para saber por qué falló
            for ll in r["llamadas"]:
                print(f"   · {ll['nombre']}({json.dumps(ll['argumentos'], ensure_ascii=False)[:160]})")
                print(f"     ⇒ {str(ll.get('resultado'))[:240]}")
        print()
        informe.append({"id": ident, "pregunta": pregunta, "ok": not fallos, "fallos": fallos, **r})
        await asyncio.sleep(2)  # respiro para el límite por minuto del plan gratuito

    latencias = [x["primera_voz_s"] for x in informe if x["primera_voz_s"]]
    print(f"Resultado: {aciertos}/{len(informe)} correctas"
          + (f" · primera voz media {sum(latencias) / len(latencias):.1f} s" if latencias else ""))
    carpeta = config.RAIZ / "evaluaciones"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    ruta.write_text(json.dumps({"modelo": config.MODELOS_LIVE[0], "aciertos": aciertos, "total": len(informe),
                                "preguntas": informe}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Informe guardado en {ruta}")


if __name__ == "__main__":
    args = sys.argv[1:]
    repetir = 1
    if "--repetir" in args:
        i = args.index("--repetir")
        repetir = int(args[i + 1]) if i + 1 < len(args) and args[i + 1].isdigit() else 3
        del args[i:i + 2 if repetir and i + 1 < len(args) and args[i + 1].isdigit() else i + 1]
    argumentos = [a for a in args if not a.startswith("--")]
    asyncio.run(main(argumentos, "--rapido" in sys.argv, repetir))
