"""Pruebas de evaluar_escenario y crear_grafica (sin clave de API).

    python tests/test_escenarios_graficas.py
"""
import asyncio
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from ia_llama import config, herramientas, servidor  # noqa: E402
from ia_llama.sesion import SesionVoz  # noqa: E402

resultados = []


def comprobar(nombre, ok, detalle=""):
    resultados.append(bool(ok))
    print(("OK   " if ok else "FALLO"), nombre, ("| " + str(detalle)) if detalle != "" else "")


config.DIR_GRAFICAS = Path(tempfile.mkdtemp())

# ---- escenarios
r = herramientas.ejecutar("evaluar_escenario", {"material": "tela de algodón", "oxigeno_pct": 21, "flujo_aire_cm_s": 20})
orden = [x["investigacion"] for x in r["resultados"]]
comprobar("algodón con aire normal -> Saffire I y II primero", orden[:2] == ["PSI-98 SAFFIRE-I", "PSI-99 SAFFIRE-II"], orden)
saffire1 = r["resultados"][0]["ensayos_mas_parecidos"]
comprobar("ensayos de Saffire-I con su tiempo de combustión",
          sorted(e.get("Burn Time (s)") for e in saffire1) == [70.0, 420.0], [e.get("Burn Time (s)") for e in saffire1])
r = herramientas.ejecutar("evaluar_escenario", {"material": "PMMA", "oxigeno_pct": 30})
fuera = [f for x in r["resultados"] for f in x["fuera_de_lo_ensayado"]]
comprobar("PMMA al 30 % de O2 -> avisa de que no se ensayó", fuera and all("o2_pct=30" in f for f in fuera), fuera[:1])
r = herramientas.ejecutar("evaluar_escenario", {"material": "heptano", "oxigeno_pct": 15, "presion_atm": 1})
fl = r["resultados"][0]
comprobar("heptano 15 % O2 1 atm -> ensayos de FLEX parecidos",
          fl["investigacion"] == "PSI-69 FLEX" and abs(fl["ensayos_mas_parecidos"][0]["o2_pct"] - 15) < 1, fl["investigacion"])
r = herramientas.ejecutar("evaluar_escenario", {"material": "madera"})
comprobar("material sin ensayos -> aviso claro", not r["resultados"] and "No hay ensayos" in r["aviso"])
r = herramientas.ejecutar("evaluar_escenario", {"material": "propano", "oxigeno_pct": 40})
cod = r["resultados"][0]["ensayos_mas_parecidos"][0].get("Self -ext or flow term", "")
comprobar("códigos de CFI-G traducidos", "se apagó sola" in cod or "flujo" in cod, cod)
c = herramientas.citas("evaluar_escenario", {"material": "algodón"},
                       herramientas.ejecutar("evaluar_escenario", {"material": "algodón"}))
comprobar("citas de cada experimento del escenario", {x["accesion"] for x in c} >= {"PSI-98", "PSI-99"}, len(c))

# ---- gráficas
cliente = TestClient(servidor.app)
r = herramientas.ejecutar("crear_grafica", {"tabla": "PSI-69_Experimental table_FLEX", "tipo": "barras",
                                            "y": "Burning rate; mm", "agrupar_por": "Fuel"})
comprobar("barras: medias correctas", r["resumen"]["Heptane"]["ensayos"] == 107
          and abs(r["resumen"]["Heptane"]["media"] - 0.5448) < 0.001, r["resumen"])
img = cliente.get(r["url"])
comprobar("la gráfica se descarga como PNG", img.status_code == 200 and img.content[:4] == b"\x89PNG", len(img.content))
r = herramientas.ejecutar("crear_grafica", {"tabla": "PSI-69_Experimental table_FLEX", "tipo": "dispersion",
                                            "y": "Burn time; s", "x": "Droplet initial diameter; mm", "agrupar_por": "Fuel"})
comprobar("dispersión con datos para la web", len(r["datos"]["puntos"]) > 200, len(r["datos"]["puntos"]))
for mal, motivo in (({"tipo": "tarta", "y": "Burn time; s"}, "tipo no válido"),
                    ({"tipo": "barras", "y": "Burn time; s"}, "barras sin grupos"),
                    ({"tipo": "barras", "y": "Fuel", "agrupar_por": "Test end"}, "columna no numérica")):
    e = herramientas.ejecutar("crear_grafica", {"tabla": "PSI-69_Experimental table_FLEX", **mal})
    comprobar(f"error controlado: {motivo}", "error" in e, e.get("error", "")[:60])
comprobar("ruta maliciosa de gráfica -> 404", cliente.get("/ia/graficas/..%2F..%2Fconfig.py").status_code == 404)


# ---- la web recibe la gráfica con sus datos; Gemini solo el resumen
class SesionGrafica:
    def __init__(self):
        self.respuesta = None
        self.listo = asyncio.Event()

    async def send_realtime_input(self, **_):
        pass

    async def send_tool_response(self, function_responses):
        self.respuesta = function_responses[0].response
        self.listo.set()

    async def receive(self):
        yield NS(tool_call=NS(function_calls=[NS(id="1", name="crear_grafica", args={
            "tabla": "PSI-69_Experimental table_FLEX", "tipo": "dispersion", "y": "Burn time; s",
            "x": "Droplet initial diameter; mm", "agrupar_por": "Fuel"})]),
            server_content=None, session_resumption_update=None, go_away=None)
        await asyncio.sleep(3600)


async def prueba_evento():
    s, eventos = SesionGrafica(), []

    @asynccontextmanager
    async def conectar(model, config):
        yield s

    async def guarda(e):
        eventos.append(e)

    async def nada(_):
        pass

    ses = SesionVoz(nada, guarda, cliente=NS(aio=NS(live=NS(connect=conectar))))
    tarea = asyncio.create_task(ses.ejecutar())
    await asyncio.wait_for(s.listo.wait(), 10)
    await ses.cerrar()
    await asyncio.wait_for(tarea, 3)
    return s.respuesta, [e for e in eventos if e["tipo"] == "grafica"]


respuesta, ev = asyncio.run(prueba_evento())
comprobar("evento 'grafica' con URL y datos para la web", ev and ev[0]["url"].startswith("/ia/graficas/")
          and len(ev[0]["datos"]["puntos"]) > 200, ev and ev[0]["titulo"])
comprobar("a Gemini no se le envían los datos en bruto", "datos" not in respuesta and "resumen" in respuesta,
          sorted(respuesta))

print("\nTodas las pruebas de escenarios y gráficas pasan" if all(resultados) else "\nHAY FALLOS")
sys.exit(0 if all(resultados) else 1)
