"""Construye el índice de búsqueda a partir de datos/documentos/ (PDF, TXT, MD).

    python ingestar.py                 # con embeddings de Gemini (búsqueda semántica + palabras clave)
    python ingestar.py --sin-embeddings  # solo palabras clave (no gasta cuota, útil para probar)

Hay que volver a ejecutarlo cada vez que añadáis o cambiéis documentos.
Las tablas (datos/tablas/) NO necesitan ingesta: se leen directamente.
"""
import argparse
import logging
import time

from ia_llama import config, datos
from ia_llama.rag import construir_indice

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

p = argparse.ArgumentParser()
p.add_argument("--sin-embeddings", action="store_true")
args = p.parse_args()

t0 = time.time()
indice = construir_indice(con_embeddings=not args.sin_embeddings)
indice.guardar()

fuentes = sorted({f.fuente for f in indice.fragmentos})
print(f"\nDocumentos: {len(fuentes)}  ·  fragmentos: {len(indice.fragmentos)}"
      f"  ·  embeddings: {'sí' if indice.vectores is not None else 'no'}  ·  {time.time() - t0:.1f}s")
for f in fuentes:
    print("  -", f)
tablas = datos.tablas()
print(f"\nTablas en {config.DIR_TABLAS}: {len(tablas)}")
for nombre, df in tablas.items():
    print(f"  - {nombre}: {len(df)} filas, columnas {list(map(str, df.columns))}")
