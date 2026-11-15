"""Declaración de las herramientas que la IA puede usar y su ejecución."""
from __future__ import annotations

import json
import re
import logging
from functools import lru_cache

from . import config, datos, documentos, escenarios, graficas
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

DECLARACIONES += [
    {
        "name": "listar_documentos",
        "description": (
            "Lista los documentos disponibles: los que ha SUBIDO el usuario, las fichas de investigación "
            "del PSI y los documentos que has creado tú. Úsala cuando el usuario mencione un documento "
            "que ha subido ('el PDF que te he pasado', 'mi informe') para saber su nombre exacto."
        ),
    },
    {
        "name": "leer_documento",
        "description": (
            "Lee el texto completo de un documento por partes (para resumirlo, revisarlo o responder "
            "sobre él entero). Si partes_totales > 1, pide las siguientes partes. Para buscar un dato "
            "concreto es más rápido buscar_documentos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "nombre": {"type": "STRING", "description": "Nombre del documento, tal como sale en listar_documentos."},
                "parte": {"type": "INTEGER", "description": "Parte a leer, empezando por 1."},
            },
            "required": ["nombre"],
        },
    },
    {
        "name": "crear_documento",
        "description": (
            "Crea un documento descargable (Markdown, Word y PDF) cuando el usuario pida un informe, "
            "resumen, ficha, lista de recomendaciones o similar. Es la ÚNICA forma de crear un archivo: "
            "si no la llamas, no existe ningún documento. Antes, consulta los datos necesarios. "
            "El contenido va en Markdown (# títulos, - viñetas, **negrita**) y debe terminar con una "
            "sección '## Fuentes' con la investigación, la accesión PSI y el DOI de lo consultado."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "titulo": {"type": "STRING"},
                "contenido": {"type": "STRING", "description": "Texto completo del documento en Markdown."},
            },
            "required": ["titulo", "contenido"],
        },
    },
]

DECLARACIONES += [
    {
        "name": "evaluar_escenario",
        "description": (
            "Para preguntas de riesgo o '¿qué pasaría si...?' sobre un incendio (un material o combustible "
            "con cierto oxígeno, ventilación o presión): busca los ensayos reales del NASA PSI más parecidos "
            "(Saffire, BASS, SAME, FLEX, CFI, CFI-G) y devuelve qué pasó en ellos, qué condiciones se "
            "ensayaron y si el escenario queda fuera de lo ensayado. Rellena solo lo que diga el usuario."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "material": {"type": "STRING", "description": "Material o combustible (en español o inglés): algodón, PMMA, Nomex, silicona, heptano, metanol, propano..."},
                "oxigeno_pct": {"type": "NUMBER", "description": "Oxígeno en % (el aire normal es 21)."},
                "flujo_aire_cm_s": {"type": "NUMBER", "description": "Velocidad del aire en cm/s (ventilación)."},
                "presion_atm": {"type": "NUMBER", "description": "Presión en atmósferas (1 = nivel del mar)."},
                "tipo": {"type": "STRING", "enum": ["solido", "liquido", "gas"]},
            },
        },
    },
]

DECLARACIONES += [
    {
        "name": "crear_grafica",
        "description": (
            "Dibuja una gráfica de una tabla para mostrarla en pantalla cuando pidan verla, compararla o "
            "visualizarla ('enséñame...', 'haz una gráfica...'). Tipos: 'barras' = media de y por grupo "
            "(agrupar_por obligatorio, p. ej. Fuel); 'dispersion' = y frente a x (x obligatorio), con hasta "
            "3 grupos de color; 'histograma' = cómo se reparten los valores de y."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "tabla": {"type": "STRING"},
                "tipo": {"type": "STRING", "enum": list(graficas.TIPOS)},
                "y": {"type": "STRING", "description": "Columna numérica a dibujar."},
                "x": {"type": "STRING", "description": "Columna del eje horizontal (solo dispersión)."},
                "agrupar_por": {"type": "STRING", "description": "Columna de grupos (obligatoria en barras)."},
                "filtros": _FILTROS,
                "titulo": {"type": "STRING", "description": "Título en español (opcional)."},
            },
            "required": ["tabla", "tipo", "y"],
        },
    },
]

HERRAMIENTAS_GEMINI = [{"function_declarations": DECLARACIONES}]


@lru_cache(maxsize=1)
def indice() -> Indice:
    """Índice de búsqueda: fichas PSI y documentos base, más los documentos subidos desde la web."""
    base = Indice.cargar()
    if (config.DIR_INDICE_SUBIDOS / "fragmentos.json").exists():
        base = base.unir(Indice.cargar(config.DIR_INDICE_SUBIDOS))
    return base


def recargar_indice() -> None:
    """Tras subir un documento: la siguiente búsqueda ya lo incluye."""
    indice.cache_clear()


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
    "listar_documentos": documentos.listar,
    "leer_documento": documentos.leer,
    "crear_documento": documentos.crear,
    "evaluar_escenario": escenarios.evaluar,
    "crear_grafica": graficas.crear,
}


# ----------------------------------------------------------------------------- citas para la web

def _base_cita(nombre_fuente: str) -> dict:
    """Datos de la investigación PSI a partir de un nombre que empiece por PSI-XX (tabla o documento)."""
    base = nombre_fuente.rsplit("/", 1)[-1]
    f = datos._ficha_psi(base)
    if not f:
        return {"investigacion": None, "accesion": None, "titulo": None, "doi": None, "url": None}
    doi = f.get("doi") or None
    return {
        "investigacion": f.get("investigationAcronym") or f["accession"],
        "accesion": f["accession"],
        "titulo": f.get("title"),
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else None,
    }


def _describir_consulta(argumentos: dict) -> str:
    partes = []
    if argumentos.get("columnas"):
        partes.append("columnas: " + ", ".join(map(str, argumentos["columnas"])))
    if argumentos.get("agrupar_por"):
        partes.append(f"agrupado por {argumentos['agrupar_por']}")
    for f in argumentos.get("filtros") or []:
        partes.append(f"{f.get('columna')} {f.get('operador', '==')} {f.get('valor')}")
    if argumentos.get("ordenar_por"):
        partes.append(f"ordenado por {argumentos['ordenar_por']}" + (" (desc.)" if argumentos.get("descendente") else ""))
    return "; ".join(partes)


def citas(nombre: str, argumentos: dict | None, resultado: dict) -> list[dict]:
    """Referencias estructuradas de lo que la IA ha consultado, para mostrarlas en la web.
    Una cita por documento o tabla realmente usado (las consultas que dieron error no cuentan)."""
    argumentos = argumentos or {}
    if not isinstance(resultado, dict) or "error" in resultado:
        return []
    if nombre == "buscar_documentos":
        salida = []
        for r in resultado.get("resultados", []):
            texto = r.get("texto", "")
            if texto.startswith("[") and "]\n" in texto[:200]:
                texto = texto.split("]\n", 1)[1]  # quitar el título que se añade a cada fragmento
            salida.append({"tipo": "documento", **_base_cita(r["fuente"]), "fuente": r["fuente"],
                           "pagina": r.get("pagina"), "extracto": " ".join(texto.split())[:300]})
        return salida
    if nombre == "evaluar_escenario":
        esc = {k: v for k, v in (resultado.get("escenario") or {}).items() if v not in (None, "", [])
               and k != "terminos_buscados"}
        consulta = "escenario: " + ", ".join(f"{k}={v}" for k, v in esc.items())
        return [{"tipo": "tabla", **_base_cita(r["tabla"]), "tabla": r["tabla"], "consulta": consulta,
                 "filas": r.get("ensayos_coincidentes")} for r in resultado.get("resultados", [])]
    if nombre == "crear_grafica":
        return [{"tipo": "tabla", **_base_cita(resultado.get("tabla", "")), "tabla": resultado.get("tabla"),
                 "consulta": f"gráfica ({resultado.get('tipo')}): " + _describir_consulta(
                     {k: v for k, v in argumentos.items() if k in ("filtros",)} | {
                         "columnas": [c for c in (argumentos.get("y"), argumentos.get("x")) if c],
                         "agrupar_por": argumentos.get("agrupar_por")}),
                 "filas": (resultado.get("resumen") or {}).get("ensayos")}]
    if nombre == "leer_documento":
        doc = resultado.get("documento", "")
        return [{"tipo": "documento", **_base_cita(doc), "fuente": doc, "pagina": None,
                 "parte": resultado.get("parte"), "extracto": " ".join(resultado.get("texto", "").split())[:300]}]
    if nombre in ("consultar_tabla", "estadisticas_tabla", "describir_tabla"):
        tabla = resultado.get("tabla") or argumentos.get("tabla", "")
        cita = {"tipo": "tabla", **_base_cita(tabla), "tabla": tabla,
                "consulta": _describir_consulta(argumentos) if nombre != "describir_tabla" else "descripción de la tabla"}
        if nombre == "consultar_tabla":
            cita["filas"] = resultado.get("filas_que_cumplen")
        elif nombre == "estadisticas_tabla":
            cita["filas"] = resultado.get("filas_usadas")
        return [cita]
    return []  # listar_tablas no aporta datos que citar


_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>\\]+")
_CIFRAS = "cero uno dos tres cuatro cinco seis siete ocho nueve".split()
_LETRAS = dict(zip("abcdefghijklmnopqrstuvwxyz",
                   ["a", "be", "ce", "de", "e", "efe", "ge", "hache", "i", "jota", "ka", "ele", "eme", "ene",
                    "o", "pe", "cu", "erre", "ese", "te", "u", "uve", "uve doble", "equis", "i griega", "zeta"]))
_SIGNOS = {".": "punto", "/": "barra", "-": "guion", "_": "guion bajo", "(": "abre paréntesis",
           ")": "cierra paréntesis", ":": "dos puntos", ";": "punto y coma"}


def doi_hablado(doi: str) -> str:
    """'10.60555/9kbh-e962' -> 'diez punto seis cero cinco cinco cinco barra nueve ka be hache guion e nueve seis dos'.
    Los modelos de voz se saltan cifras al deletrear de memoria; así lo leen tal cual."""
    prefijo, _, resto = doi.partition(".")
    palabras = ["diez" if prefijo == "10" else " ".join(_CIFRAS[int(c)] for c in prefijo), "punto"]
    for c in resto.lower():
        palabras.append(_CIFRAS[int(c)] if c.isdigit() else _LETRAS.get(c) or _SIGNOS.get(c, c))
    return " ".join(palabras)


def _dois_en_voz(resultado) -> dict:
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    dois = dict.fromkeys(d.rstrip(".,;)") for d in _DOI.findall(texto))
    return {d: doi_hablado(d) for d in list(dois)[:10]}


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
    texto = json.dumps({k: v for k, v in resultado.items() if k != "datos"} if isinstance(resultado, dict)
                       else resultado, ensure_ascii=False, default=str)
    if len(texto) > 20000:
        resultado = {"aviso": "Resultado recortado por tamaño; pide menos filas o filtra más.",
                     "resultado_parcial": texto[:20000]}
    if isinstance(resultado, dict) and nombre != "crear_grafica":
        dois = _dois_en_voz({k: v for k, v in resultado.items() if k != "datos"})
        if dois:
            resultado["dois_en_voz"] = dois
    return resultado
