"""Declaración de las herramientas que la IA puede usar y su ejecución."""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from . import config, datos
from .rag import Indice

log = logging.getLogger(__name__)

_FILTROS = {
    "type": "ARRAY",
    "description": "Condiciones que deben cumplir las filas (todas a la vez).",
    "items": {
        "type": "OBJECT",
        "properties": {
            "columna": {"type": "STRING"},
            "operador": {"type": "STRING", "enum": datos.OPERADORES},
            "valor": {"type": "STRING", "description": "Valor a comparar (los números también como texto)."},
        },
        "required": ["columna", "operador", "valor"],
    },
}

DECLARACIONES = [
    {
        "name": "buscar_documentos",
        "description": (
            "Busca en los papers, informes y documentación de experimentos de combustión en "
            "microgravedad. Úsala para resultados, conclusiones, explicaciones y contexto de experimentos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "consulta": {
                    "type": "STRING",
                    "description": "Qué buscar, con palabras clave concretas (en inglés suele funcionar mejor "
                                   "si los documentos están en inglés).",
                },
                "num_resultados": {"type": "INTEGER", "description": f"Entre 1 y {config.MAX_FRAGMENTOS}."},
            },
            "required": ["consulta"],
        },
    },
    {
        "name": "listar_tablas",
        "description": (
            "Lista las tablas de datos de experimentos del NASA PSI (nombre, investigación, filas y "
            "columnas). Opcionalmente filtra por un texto, p. ej. 'FLEX', 'BASS', 'Saffire', 'PSI-69'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {"texto": {"type": "STRING", "description": "Filtro opcional por nombre o investigación."}},
        },
    },
    {
        "name": "describir_tabla",
        "description": (
            "Describe una tabla: experimento, DOI, objetivo, y tipo, rango o valores de ejemplo de cada "
            "columna. Úsala antes de filtrar para conocer los nombres exactos y las unidades."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {"tabla": {"type": "STRING"}},
            "required": ["tabla"],
        },
    },
    {
        "name": "consultar_tabla",
        "description": (
            "Devuelve ensayos concretos (filas) de una tabla, con filtros, columnas y orden. Úsala para "
            "datos de ensayos concretos ('¿qué pasó en el ensayo 12?', '¿qué ensayos usaron helio?'). "
            "NO la uses para comparar grupos ni para decir qué arde más rápido o dura más en general: "
            "para eso usa estadisticas_tabla con agrupar_por."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tabla": {"type": "STRING"},
                "filtros": _FILTROS,
                "columnas": {"type": "ARRAY", "items": {"type": "STRING"},
                             "description": "Columnas a devolver (vacío = todas)."},
                "ordenar_por": {"type": "STRING"},
                "descendente": {"type": "BOOLEAN"},
                "limite": {"type": "INTEGER", "description": f"Máximo de filas (hasta {config.MAX_FILAS})."},
            },
            "required": ["tabla"],
        },
    },
    {
        "name": "estadisticas_tabla",
        "description": (
            "Calcula estadísticas (número de ensayos, media, desviación, mínimo, mediana, máximo) de "
            "columnas numéricas, opcionalmente agrupando por otra columna y con filtros. Es la herramienta "
            "para CUALQUIER comparación ('¿qué combustible arde más rápido?', '¿qué material ardió más "
            "tiempo?'): una sola llamada con agrupar_por da la media de cada grupo y cuántos ensayos hay."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tabla": {"type": "STRING"},
                "columnas": {"type": "ARRAY", "items": {"type": "STRING"}},
                "agrupar_por": {"type": "STRING"},
                "filtros": _FILTROS,
            },
            "required": ["tabla", "columnas"],
        },
    },
]

HERRAMIENTAS_GEMINI = [{"function_declarations": DECLARACIONES}]


@lru_cache(maxsize=1)
def indice() -> Indice:
    return Indice.cargar()


def precargar() -> None:
    """Carga tablas, fichas e índice por adelantado para que la primera pregunta no espere."""
    datos.tablas()
    datos.catalogo_compacto()
    indice()


def _buscar_documentos(consulta: str, num_resultados: int = 4) -> dict:
    k = max(1, min(int(num_resultados or 4), config.MAX_FRAGMENTOS))
    resultados = indice().buscar(consulta, k)
    if not resultados:
        return {"resultados": [], "aviso": "No se encontró nada relevante en los documentos."}
    return {"resultados": resultados}


FUNCIONES = {
    "buscar_documentos": _buscar_documentos,
    "listar_tablas": datos.listar_tablas,
    "describir_tabla": datos.describir_tabla,
    "consultar_tabla": datos.consultar_tabla,
    "estadisticas_tabla": datos.estadisticas_tabla,
}


def ejecutar(nombre: str, argumentos: dict | None) -> dict:
    """Ejecuta una herramienta. Nunca lanza excepciones: los errores se devuelven a la IA
    para que pueda corregirse (por ejemplo, si se equivocó de nombre de columna)."""
    funcion = FUNCIONES.get(nombre)
    if funcion is None:
        return {"error": f"Herramienta desconocida: {nombre}"}
    try:
        resultado = funcion(**(argumentos or {}))
    except Exception as e:
        log.info("Error en %s(%s): %s", nombre, argumentos, e)
        mensaje = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        return {"error": mensaje}
    # Red de seguridad: que una respuesta enorme no sature el contexto del modelo
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(texto) > 20000:
        return {"aviso": "Resultado recortado por tamaño; pide menos filas o filtra más.",
                "resultado_parcial": texto[:20000]}
    return resultado
