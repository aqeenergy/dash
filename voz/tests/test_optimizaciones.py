"""Pruebas de los arreglos y optimizaciones de la revisión (sin clave de API).

    python tests/test_optimizaciones.py
"""
import asyncio
import json
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ia_llama import config, datos, herramientas, rag, servidor  # noqa: E402
from ia_llama.sesion import SesionVoz  # noqa: E402

resultados = []


def comprobar(nombre, ok, detalle=""):
    resultados.append(ok)
    print(("OK   " if ok else "FALLO"), nombre, ("| " + str(detalle)) if detalle else "")


# 1. Búsqueda en directo: si Google responde 429, se usa BM25 al momento (sin esperar minutos)
class ClienteSaturado:
    class models:
        @staticmethod
        def embed_content(**_):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")


rag._cliente_embeddings = ClienteSaturado()
config.GEMINI_API_KEY = "clave-falsa"
frag = [rag.Fragmento(0, "a.md", None, "cool flames in droplet combustion"),
        rag.Fragmento(1, "b.md", None, "large scale fire on Cygnus")]
indice = rag.Indice(frag, np.ones((2, 4), dtype=np.float32))
t = time.perf_counter()
r = indice.buscar("cool flames", 2)
dt = time.perf_counter() - t
comprobar("429 en la búsqueda -> BM25 al instante", dt < 1 and r and r[0]["fuente"] == "a.md", f"{dt * 1000:.0f} ms")

# 2. Cliente de embeddings reutilizado y consultas repetidas en caché
llamadas = []


class ClienteBueno:
    class models:
        @staticmethod
        def embed_content(**kw):
            llamadas.append(kw["contents"])
            return NS(embeddings=[NS(values=[1.0, 0, 0, 0])])


rag._cliente_embeddings = ClienteBueno()
rag._embeber_consulta.cache_clear()
indice.buscar("cool flames", 1)
indice.buscar("Cool Flames ", 1)
comprobar("consulta repetida -> una sola llamada a Google", len(llamadas) == 1, f"{len(llamadas)} llamadas")

# 3. Índice creado con otro modelo de embeddings -> aviso y solo BM25 (sin resultados sin sentido)
with tempfile.TemporaryDirectory() as d:
    indice.guardar(Path(d))
    meta = Path(d) / "meta.json"
    meta.write_text(json.dumps({"modelo": "otro-modelo", "dimension": 999}))
    cargado = rag.Indice.cargar(Path(d))
    comprobar("índice de otro modelo -> no usa sus vectores", cargado.vectores is None)

# 4. Filtro con valor no numérico en una columna casi numérica (ensayos "12-R" de BASS)
r = herramientas.ejecutar("consultar_tabla", {"tabla": "PSI-26_Experimental table_BASS",
                                              "filtros": [{"columna": "Test #", "operador": "==", "valor": "12-R"}]})
comprobar("filtro 'Test # == 12-R' en BASS", "error" not in r and r.get("filas_que_cumplen", 0) >= 1,
          r.get("error") or f"{r.get('filas_que_cumplen')} filas")
r = herramientas.ejecutar("consultar_tabla", {"tabla": "PSI-69_Experimental table_FLEX",
                                              "filtros": [{"columna": "Burn time; s", "operador": ">", "valor": "30"}]})
comprobar("filtro numérico sigue funcionando", r.get("filas_que_cumplen") == 6, r.get("filas_que_cumplen"))

# 5. Catálogo en las instrucciones
from ia_llama.prompt import INSTRUCCIONES  # noqa: E402
comprobar("catálogo de tablas en las instrucciones",
          "PSI-69_Experimental table_FLEX" in INSTRUCCIONES and "Burning rate; mm" in INSTRUCCIONES,
          f"{len(INSTRUCCIONES)} car.")


# 6. Varias consultas pedidas a la vez -> en paralelo y en el mismo orden
class SesionDosConsultas:
    def __init__(self):
        self.respuestas = None
        self.listo = asyncio.Event()

    async def send_realtime_input(self, **_):
        pass

    async def send_tool_response(self, function_responses):
        self.respuestas = function_responses
        self.listo.set()

    async def receive(self):
        llamadas_ = [NS(id="1", name="listar_tablas", args={"texto": "FLEX"}),
                     NS(id="2", name="describir_tabla", args={"tabla": "PSI-69_Experimental table_FLEX"})]
        yield NS(tool_call=NS(function_calls=llamadas_), server_content=None,
                 session_resumption_update=None, go_away=None)
        await asyncio.sleep(3600)


async def prueba_paralelo():
    s = SesionDosConsultas()

    @asynccontextmanager
    async def conectar(model, config):
        yield s

    cliente = NS(aio=NS(live=NS(connect=conectar)))

    async def nada(_):
        pass

    ses = SesionVoz(nada, nada, cliente=cliente)
    tarea = asyncio.create_task(ses.ejecutar())
    await asyncio.wait_for(s.listo.wait(), 5)
    await ses.cerrar()
    await asyncio.wait_for(tarea, 3)
    return [r.id for r in s.respuestas]


ids = asyncio.run(prueba_paralelo())
comprobar("dos consultas a la vez -> respuestas en orden", ids == ["1", "2"], ids)

# 7. El contador de conversaciones no se queda bloqueado si una sesión falla al crearse
from fastapi.testclient import TestClient  # noqa: E402

original = servidor.SesionVoz


def falla(*a, **k):
    raise RuntimeError("fallo al crear la sesión")


servidor.SesionVoz = falla
try:
    with TestClient(servidor.app).websocket_connect("/ws/voz") as ws:
        try:
            ws.receive_text()
        except Exception:
            pass
except Exception:
    pass
servidor.SesionVoz = original
comprobar("sesión que falla al crearse -> contador vuelve a 0", servidor._activas == 0, servidor._activas)

# 8. Precarga: después, la primera consulta no paga la carga de datos
datos.tablas.cache_clear()
t = time.perf_counter()
herramientas.precargar()
t_carga = time.perf_counter() - t
t = time.perf_counter()
herramientas.ejecutar("estadisticas_tabla", {"tabla": "PSI-69_Experimental table_FLEX",
                                             "columnas": ["Burning rate; mm"], "agrupar_por": "Fuel"})
t_consulta = time.perf_counter() - t
comprobar("precarga -> primera consulta rápida", t_consulta < 0.1,
          f"precarga {t_carga * 1000:.0f} ms, consulta {t_consulta * 1000:.0f} ms")

print("\nTodas las pruebas de optimización pasan" if all(resultados) else "\nHAY FALLOS")
sys.exit(0 if all(resultados) else 1)
