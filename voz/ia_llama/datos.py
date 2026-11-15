"""Acceso a las tablas de datos de experimentos (CSV / Excel) para las herramientas de la IA.

Por defecto lee las tablas del NASA PSI descargadas en datos_psi/. La descripción de cada tabla
sale de la ficha de metadatos de su investigación (PSI-XX.json: título, DOI, objetivo).
Si queréis afinarla, poned junto a la tabla un .md con el mismo nombre explicando el
experimento y las unidades de cada columna: tiene prioridad sobre la ficha.
"""
from __future__ import annotations

import json
import logging
import math
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)

EXTENSIONES = {".csv", ".tsv", ".xlsx", ".xls"}
# Ficheros con cabeceras caóticas que confunden más que ayudan (patrones separados por comas)
EXCLUIR = [x.strip().lower() for x in
           os.getenv("EXCLUIR_TABLAS", "Analyzed Data,As Run_Test Matrix").split(",") if x.strip()]
OPERADORES = ["==", "!=", ">", ">=", "<", "<=", "contiene"]


def _clave(texto: str) -> str:
    """Normaliza nombres para que 'Presión (kPa)' y 'presion_kpa' se encuentren igual."""
    t = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in t if c.isalnum())


def _leer(ruta: Path) -> pd.DataFrame:
    suf = ruta.suffix.lower()
    if suf in {".xlsx", ".xls"}:
        df = pd.read_excel(ruta)
    else:
        sep = "\t" if suf == ".tsv" else None  # None = detectar separador (coma, punto y coma...)
        for codificacion in ("utf-8-sig", "cp1252", "latin-1"):  # muchos CSV de NASA vienen de Excel
            try:
                df = pd.read_csv(ruta, sep=sep, engine="python", encoding=codificacion)
                break
            except UnicodeDecodeError:
                continue
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    df = df.dropna(how="all").dropna(axis=1, how="all")
    # CSV "a la española" (3,1 en vez de 3.1): convertir esas columnas a número
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            convertida = pd.to_numeric(df[c].astype(str).str.strip().str.replace(",", ".", regex=False),
                                       errors="coerce")
            if df[c].notna().any() and convertida[df[c].notna()].notna().all():
                df[c] = convertida
    return df


@lru_cache(maxsize=1)
def tablas() -> dict[str, pd.DataFrame]:
    resultado = {}
    if not config.DIR_TABLAS.exists():
        return resultado
    for ruta in sorted(config.DIR_TABLAS.rglob("*")):
        if any(x in ruta.name.lower() for x in EXCLUIR):
            continue
        if ruta.suffix.lower() in EXTENSIONES and not ruta.name.startswith("."):
            try:
                resultado[ruta.stem] = _leer(ruta)
            except Exception as e:
                log.warning("No se pudo leer la tabla %s: %s", ruta.name, e)
    return resultado


def recargar() -> None:
    tablas.cache_clear()


@lru_cache(maxsize=None)
def _ficha_psi(nombre: str) -> dict:
    """Ficha de metadatos PSI de la investigación a la que pertenece la tabla (por su prefijo PSI-XX)."""
    accesion = nombre.split("_")[0]
    ruta = config.DIR_METADATOS / f"{accesion}.json"
    if not accesion.startswith("PSI-") or not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _investigacion(nombre: str) -> str | None:
    f = _ficha_psi(nombre)
    if not f:
        return None
    acr = f.get("investigationAcronym") or f["accession"]
    return f"{f['accession']} · {acr}: {f.get('title', '')}"


# Notas del equipo sobre cada tabla (unidades, grupos, referencias): voz/notas_tablas/<tabla>.md
DIR_NOTAS = config.RAIZ / "notas_tablas"


@lru_cache(maxsize=None)
def _nota_texto(nombre: str) -> str | None:
    for carpeta in (DIR_NOTAS, config.DIR_TABLAS):
        if not carpeta.exists():
            continue
        for ruta in carpeta.rglob("*"):
            if ruta.stem == nombre and ruta.suffix.lower() in {".md", ".txt"}:
                return ruta.read_text(encoding="utf-8", errors="ignore")
    return None


def _nota_propia(nombre: str, completa: bool = False) -> str | None:
    """Nota del equipo sobre la tabla. El primer párrafo es el resumen (va al catálogo de las
    instrucciones); la nota completa va en describir_tabla."""
    texto = _nota_texto(nombre)
    if not texto:
        return None
    if not completa:
        texto = texto.strip().split("\n\n")[0]
    return " ".join(texto.split())[:4000 if completa else 600]


def _descripcion(nombre: str) -> str | None:
    nota = _nota_propia(nombre, completa=True)
    f = _ficha_psi(nombre)
    if nota:
        cab = ""
        if f:
            cab = f"{_investigacion(nombre)}. "
            if f.get("doi"):
                cab += f"DOI DEL EXPERIMENTO (registro PSI): {f['doi']}. "
        return cab + nota
    f = _ficha_psi(nombre)
    if not f:
        return None
    doi = f"DOI https://doi.org/{f['doi']}. " if f.get("doi") else ""
    objetivo = (f.get("objective") or "").strip()
    return f"{_investigacion(nombre)}. {doi}Objetivo: {objetivo[:900]}"


def _buscar_tabla(nombre: str) -> tuple[str, pd.DataFrame]:
    ts = tablas()
    if nombre in ts:
        return nombre, ts[nombre]
    for n, df in ts.items():
        if _clave(n) == _clave(nombre):
            return n, df
    raise KeyError(f"No existe la tabla '{nombre}'. Tablas disponibles: {list(ts)}")


def _buscar_columna(df: pd.DataFrame, nombre: str) -> str:
    if nombre in df.columns:
        return nombre
    for c in df.columns:
        if _clave(c) == _clave(nombre):
            return c
    raise KeyError(f"No existe la columna '{nombre}'. Columnas: {list(map(str, df.columns))}")


def _limpio(valor):
    """Convierte valores de pandas/numpy a tipos JSON sencillos y redondeados."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    if hasattr(valor, "item"):
        valor = valor.item()
    if isinstance(valor, float):
        return float(f"{valor:.4g}")
    if isinstance(valor, (int, bool, str)):
        return valor
    return str(valor)


def _como_numero(serie: pd.Series, minimo: float = 0.5) -> tuple[pd.Series, int] | None:
    """Columna 'casi numérica' (p. ej. con algún '–', '~6' o '#DIV/0!'): la convierte a número
    ignorando esos valores. Devuelve (serie, nº de valores ignorados) o None si no es numérica."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie, 0
    texto = serie.dropna().astype(str).str.strip()
    if texto.empty:
        return None
    # Número al principio de la celda, aunque lleve unidades o signos: "145 s", "~6", "≈0,5 mm"
    extraido = texto.str.extract(r"^[~≈<>]?\s*(-?\d+(?:[.,]\d+)?)\s*[a-zA-Z/%°²³µ ]*$")[0]
    num = pd.to_numeric(extraido.str.replace(",", ".", regex=False), errors="coerce")
    if num.notna().mean() < minimo:
        return None
    return num.reindex(serie.index), int(num.isna().sum())


def _aplicar_filtros(df: pd.DataFrame, filtros: list[dict] | None) -> pd.DataFrame:
    for f in filtros or []:
        col = _buscar_columna(df, f["columna"])
        op = f.get("operador", "==")
        valor = f.get("valor")
        serie = df[col]
        if op == "contiene":
            df = df[serie.astype(str).str.contains(str(valor), case=False, na=False)]
            continue
        if op not in OPERADORES:
            raise ValueError(f"Operador '{op}' no válido. Usa uno de {OPERADORES}")
        numerica = _como_numero(serie)
        try:
            valor_num = float(str(valor).replace(",", "."))
        except (TypeError, ValueError):
            valor_num = None  # p. ej. un ensayo "12-R": se compara como texto
        if numerica is not None and valor_num is not None:
            serie, valor = numerica[0], valor_num
        elif op in {"==", "!="}:
            serie, valor = serie.astype(str).str.lower(), str(valor).lower()
        mascara = {
            "==": serie == valor, "!=": serie != valor, ">": serie > valor,
            ">=": serie >= valor, "<": serie < valor, "<=": serie <= valor,
        }[op]
        df = df[mascara]
    return df


# ----------------------------------------------------------------------------- funciones expuestas a la IA

def listar_tablas(texto: str | None = None) -> dict:
    """Listado compacto: nombre, investigación, filas y nombres de columnas."""
    salida = []
    for nombre, df in tablas().items():
        inv = _investigacion(nombre) or ""
        if texto and _clave(texto) not in _clave(nombre + inv):
            continue
        salida.append({
            "tabla": nombre,
            "investigacion": inv or None,
            "filas": len(df),
            "columnas": [str(c) for c in df.columns],
        })
    if not salida:
        return {"aviso": "No hay tablas que coincidan." if texto else "No hay tablas de datos cargadas.",
                "todas": list(tablas()) if texto else []}
    return {"tablas": salida}


def catalogo_compacto() -> str:
    """Catálogo de tablas para las instrucciones de la IA: así no necesita llamar a listar_tablas
    en cada pregunta y se ahorra un viaje de ida y vuelta a Gemini."""
    lineas = []
    for nombre, df in tablas().items():
        f = _ficha_psi(nombre)
        inv = f"{f['accession']} {f.get('investigationAcronym') or ''}".strip() if f else ""
        columnas = " | ".join(str(c) for c in df.columns)
        lineas.append(f"- {nombre} ({inv}, {len(df)} filas): {columnas}")
        nota = _nota_propia(nombre)
        if nota:
            lineas.append(f"  NOTA sobre esta tabla: {nota}")
    return "\n".join(lineas)


def describir_tabla(tabla: str) -> dict:
    """Detalle de una tabla: descripción del experimento, tipo y rango de cada columna."""
    nombre, df = _buscar_tabla(tabla)
    columnas = []
    for c in df.columns:
        s = df[c]
        r = _como_numero(s)
        info = {"nombre": str(c), "tipo": "numérica" if r is not None else "texto"}
        if r is not None and r[0].notna().any():
            info["min"], info["max"] = _limpio(r[0].min()), _limpio(r[0].max())
        else:
            valores = s.dropna().astype(str).unique()
            info["valores_distintos"] = len(valores)
            info["ejemplos"] = list(valores[:5])
        columnas.append(info)
    return {
        "tabla": nombre,
        "filas": len(df),
        "descripcion": _descripcion(nombre),
        "columnas": columnas,
    }


def consultar_tabla(
    tabla: str,
    filtros: list[dict] | None = None,
    columnas: list[str] | None = None,
    ordenar_por: str | None = None,
    descendente: bool = False,
    limite: int = 10,
) -> dict:
    nombre, df = _buscar_tabla(tabla)
    df = _aplicar_filtros(df, filtros)
    total = len(df)
    if ordenar_por:
        df = df.sort_values(_buscar_columna(df, ordenar_por), ascending=not descendente)
    if columnas:
        df = df[[_buscar_columna(df, c) for c in columnas]]
    limite = max(1, min(int(limite or 10), config.MAX_FILAS))
    filas = [{str(k): _limpio(v) for k, v in fila.items()} for fila in df.head(limite).to_dict("records")]
    salida = {"tabla": nombre, "filas_que_cumplen": total, "mostrando": len(filas), "filas": filas}
    if ordenar_por:
        salida["nota"] = ("Son ensayos individuales ordenados, no medias. Para responder qué grupo es más "
                          "rápido/alto en general, usa estadisticas_tabla con agrupar_por y da la media.")
    return salida


def estadisticas_tabla(
    tabla: str,
    columnas: list[str],
    agrupar_por: str | None = None,
    filtros: list[dict] | None = None,
) -> dict:
    nombre, df = _buscar_tabla(tabla)
    df = _aplicar_filtros(df, filtros)
    cols = [_buscar_columna(df, c) for c in columnas]
    df = df.copy()
    ignorados, no_num = {}, []
    for c in cols:
        r = _como_numero(df[c])
        if r is None:
            no_num.append(c)
        else:
            df[c] = r[0]
            if r[1]:
                ignorados[c] = r[1]
    if no_num:
        raise ValueError(f"Estas columnas no son numéricas: {no_num}")
    metricas = ["count", "mean", "std", "min", "median", "max"]
    if agrupar_por:
        g = _buscar_columna(df, agrupar_por)
        res = df.groupby(g)[cols].agg(metricas)
        grupos = df[g].nunique()
        res = res.head(config.MAX_FILAS)
        datos = {
            str(k): {f"{c}_{m}": _limpio(v) for (c, m), v in fila.items()}
            for k, fila in res.iterrows()
        }
        salida = {"tabla": nombre, "agrupado_por": str(g), "grupos": grupos, "estadisticas": datos}
    else:
        res = df[cols].agg(metricas)
        datos = {str(c): {m: _limpio(res.loc[m, c]) for m in metricas} for c in cols}
        salida = {"tabla": nombre, "filas_usadas": len(df), "estadisticas": datos}
    if ignorados:
        salida["valores_no_numericos_ignorados"] = ignorados
    return salida
