"""Pruebas de subir y crear documentos (sin clave de API).

    python tests/test_documentos.py
"""
import asyncio
import io
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


tmp = Path(tempfile.mkdtemp())
config.DIR_SUBIDOS, config.DIR_INDICE_SUBIDOS, config.DIR_GENERADOS = tmp / "sub", tmp / "isub", tmp / "gen"
config.GEMINI_API_KEY = ""  # sin clave: los subidos se indexan para búsqueda por palabras
herramientas.recargar_indice()
cliente = TestClient(servidor.app)

# --- documentos de prueba (contenido inventado)
from docx import Document  # noqa: E402

d = Document()
d.add_heading("Ensayo de materiales del equipo", 1)
d.add_paragraph("La espuma de grafeno ignífuga resistió 42 segundos antes de inflamarse en la prueba.")
buf = io.BytesIO(); d.save(buf); docx_bytes = buf.getvalue()

from fpdf import FPDF  # noqa: E402

pdf = FPDF(); pdf.add_page(); pdf.set_font("Helvetica", size=12)
pdf.multi_cell(0, 8, "Protocolo interno: el panel de policarbonato se retira tras 3 alarmas de humo.")
pdf_bytes = bytes(pdf.output())

# 1. Subir
r = cliente.post("/ia/documentos", files={"archivo": ("Ensayo materiales.docx", docx_bytes)})
comprobar("subir un Word", r.status_code == 200 and r.json()["fragmentos"] >= 1, r.json())
r = cliente.post("/ia/documentos", files={"archivo": ("protocolo.pdf", pdf_bytes)})
comprobar("subir un PDF", r.status_code == 200, r.json())
nombre_docx = "subidos/Ensayo_materiales.docx"

# 2. La IA lo encuentra, lo lista y lo lee
r = herramientas.ejecutar("buscar_documentos", {"consulta": "espuma de grafeno ignífuga"})
comprobar("buscar_documentos encuentra el Word subido",
          r.get("resultados") and r["resultados"][0]["fuente"] == nombre_docx, r.get("resultados", [{}])[0].get("fuente"))
r = herramientas.ejecutar("listar_documentos", {})
comprobar("listar_documentos muestra los subidos",
          len(r["subidos_por_el_usuario"]) == 2 and r["documentos_base"], [x["nombre"] for x in r["subidos_por_el_usuario"]])
r = herramientas.ejecutar("leer_documento", {"nombre": "protocolo.pdf"})
comprobar("leer_documento lee el PDF entero", "3 alarmas de humo" in r.get("texto", ""), r.get("partes_totales"))
r2 = herramientas.ejecutar("leer_documento", {"nombre": "PSI-69_FLEX"})
comprobar("leer_documento lee también una ficha PSI", "Flame Extinguishment" in r2.get("texto", ""), r2.get("documento"))
c = herramientas.citas("leer_documento", {"nombre": "protocolo.pdf"}, r)
comprobar("cita del documento leído", c and c[0]["tipo"] == "documento" and c[0]["fuente"] == "protocolo.pdf", c and c[0]["fuente"])

# 3. Rechazos
comprobar("rechaza formatos no admitidos",
          cliente.post("/ia/documentos", files={"archivo": ("virus.exe", b"MZ...")}).status_code == 400)
comprobar("rechaza archivos vacíos",
          cliente.post("/ia/documentos", files={"archivo": ("vacio.txt", b"")}).status_code == 400)
config.MAX_MB_SUBIDA = 0.001
comprobar("rechaza archivos demasiado grandes",
          cliente.post("/ia/documentos", files={"archivo": ("grande.txt", b"x" * 5000)}).status_code == 400)
config.MAX_MB_SUBIDA = 20
r = cliente.post("/ia/documentos", files={"archivo": ("escaneado.pdf", bytes(FPDF().output()))})
comprobar("PDF sin texto -> mensaje claro", r.status_code == 400 and "texto" in r.json()["detail"], r.json()["detail"])
r = herramientas.ejecutar("leer_documento", {"nombre": "../../ia_llama/config.py"})
comprobar("no se pueden leer archivos fuera de las carpetas de documentos", "error" in r)

# 4. Crear un documento
contenido = """## Resumen
La tasa de combustión media del **heptano** fue 0,54 mm²/s frente a 0,47 del metanol (CO₂ como supresor).

## Recomendaciones
- Ventilar con flujo controlado
- Revisar materiales — especialmente PMMA
1. Primer paso
2. Segundo paso

## Fuentes
- FLEX · PSI-69 · DOI 10.60555/mbq8-0451"""
r = herramientas.ejecutar("crear_documento", {"titulo": "Informe FLEX: combustión de gotas", "contenido": contenido})
formatos = sorted(a["formato"] for a in r.get("archivos", []))
comprobar("crear_documento genera MD, Word y PDF", formatos == ["docx", "md", "pdf"], formatos)
pdf_url = next(a["url"] for a in r["archivos"] if a["formato"] == "pdf")
docx_url = next(a["url"] for a in r["archivos"] if a["formato"] == "docx")
rp = cliente.get(pdf_url)
comprobar("se descarga el PDF", rp.status_code == 200 and rp.content[:4] == b"%PDF", f"{len(rp.content)} bytes")
rd = cliente.get(docx_url)
textos = [p.text for p in Document(io.BytesIO(rd.content)).paragraphs]
comprobar("el Word tiene título, apartados y viñetas",
          "Informe FLEX: combustión de gotas" in textos and "Recomendaciones" in textos
          and "Ventilar con flujo controlado" in textos, textos[:4])
comprobar("descarga con ruta maliciosa -> 404", cliente.get("/ia/generados/..%2F..%2Fconfig.py").status_code == 404)
comprobar("crear con contenido vacío -> error", "error" in herramientas.ejecutar("crear_documento", {"titulo": "x", "contenido": ""}))


# 5. La sesión avisa a la web con los enlaces
class SesionCrea:
    def __init__(self):
        self.listo = asyncio.Event()

    async def send_realtime_input(self, **_):
        pass

    async def send_tool_response(self, function_responses):
        self.listo.set()

    async def receive(self):
        yield NS(tool_call=NS(function_calls=[NS(id="1", name="crear_documento",
                                                 args={"titulo": "Prueba", "contenido": "## A\n- uno\n- dos tres cuatro"})]),
                 server_content=None, session_resumption_update=None, go_away=None)
        await asyncio.sleep(3600)


async def prueba_evento():
    s, eventos = SesionCrea(), []

    @asynccontextmanager
    async def conectar(model, config):
        yield s

    async def guarda(e):
        eventos.append(e)

    async def nada(_):
        pass

    ses = SesionVoz(nada, guarda, cliente=NS(aio=NS(live=NS(connect=conectar))))
    tarea = asyncio.create_task(ses.ejecutar())
    await asyncio.wait_for(s.listo.wait(), 5)
    await ses.cerrar()
    await asyncio.wait_for(tarea, 3)
    return [e for e in eventos if e["tipo"] == "documento_creado"]


ev = asyncio.run(prueba_evento())
comprobar("evento documento_creado con enlaces", ev and len(ev[0]["archivos"]) == 3 and ev[0]["turno"] == 1,
          ev and [a["url"] for a in ev[0]["archivos"]])

print("\nTodas las pruebas de documentos pasan" if all(resultados) else "\nHAY FALLOS")
sys.exit(0 if all(resultados) else 1)
