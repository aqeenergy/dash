"""Prueba las herramientas SIN hablar con Gemini Live: así comprobáis que los datos se leen bien.

    python prueba_herramientas.py "cool flames heptane"
"""
import json
import sys

from ia_llama import herramientas

consulta = " ".join(sys.argv[1:]) or "flame extinction microgravity"


def mostrar(titulo, resultado):
    print(f"\n=== {titulo} ===")
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str)[:3000])


mostrar(f"buscar_documentos('{consulta}')", herramientas.ejecutar("buscar_documentos", {"consulta": consulta}))
lista = herramientas.ejecutar("listar_tablas", {})
mostrar("listar_tablas()", lista)

for t in lista.get("tablas", [])[:1]:
    mostrar(f"consultar_tabla('{t['tabla']}')",
            herramientas.ejecutar("consultar_tabla", {"tabla": t["tabla"], "limite": 3}))
    numericas = [c["nombre"] for c in t["columnas"] if c["tipo"] == "numérica"][:2]
    if numericas:
        mostrar(f"estadisticas_tabla('{t['tabla']}', {numericas})",
                herramientas.ejecutar("estadisticas_tabla", {"tabla": t["tabla"], "columnas": numericas}))
