"""Gráficas de los datos del PSI para la web: la IA pide una gráfica y el servidor genera un PNG
(GET /ia/graficas/<archivo>) y además los datos en bruto, para que la web pueda dibujarla interactiva
o enseñarlos como tabla.

Tipos:
  barras      media de una columna por grupo (p. ej. tasa de combustión por combustible), con nº de ensayos
  dispersion  una columna frente a otra, con hasta 3 grupos de color
  histograma  cómo se reparten los valores de una columna (hasta 3 grupos)
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin pantalla: solo se generan archivos
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config, datos  # noqa: E402
from .escenarios import NOMBRES_CLAROS  # noqa: E402

# La web de FLAMA está en inglés: etiquetas de los ejes en inglés
ETIQUETAS_EN = {
    "Burning rate; mm": "Burning-rate constant K (mm²/s)",
    "O initial ambient composition; mole fraction": "Initial O2 (mole fraction)",
    "N initial ambient composition; mole fraction": "Initial N2 (mole fraction)",
    "CO initial ambient composition; mole fraction": "Initial CO2 (mole fraction)",
    "He initial ambient composition; mole fraction": "Initial He (mole fraction)",
    "?-g Burn Length": "Burn length in MICROGRAVITY",
    "?-g Spread Length": "Spread rate in MICROGRAVITY",
    "1-g Burn Length": "Burn length on EARTH (1 g reference test)",
    "1-g Spread Rate": "Spread rate on EARTH (1 g reference test)",
}

# Paleta de referencia validada (modo claro): fondo, textos y 3 colores categóricos en orden fijo
FONDO, TEXTO, TEXTO_2, REJILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
MAX_GRUPOS_COLOR = 3
MAX_BARRAS = 12
TIPOS = ("barras", "dispersion", "histograma")


class ErrorGrafica(ValueError):
    pass


def _etiqueta(columna: str) -> str:
    # En las gráficas, sin las mayúsculas que solo sirven para avisar a la IA
    return (ETIQUETAS_EN.get(columna, columna).replace("?-g", "µg")
            .replace("MICROGRAVITY", "microgravity").replace("EARTH", "Earth"))


def _num(v: float) -> str:
    """Número con coma decimal y 3 cifras significativas: 0.5448 -> '0,545'."""
    return f"{v:.3g}".replace(".", ",")


_COMA = FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))


def _estilo(ax, titulo: str, subtitulo: str) -> None:
    ax.yaxis.set_major_formatter(_COMA)  # el eje X numérico se formatea en cada tipo de gráfica
    ax.set_facecolor(FONDO)
    ax.figure.set_facecolor(FONDO)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(REJILLA)
    ax.tick_params(colors=TEXTO_2, labelsize=9, length=0)
    ax.grid(axis="y", color=REJILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.figure.text(0.012, 0.975, titulo, fontsize=13, fontweight="bold", color=TEXTO, va="top")
    ax.figure.text(0.012, 0.915, subtitulo, fontsize=9, color=TEXTO_2, va="top")


def _numerica(df: pd.DataFrame, columna: str) -> pd.Series:
    r = datos._como_numero(df[columna])
    if r is None:
        raise ErrorGrafica(f"La columna '{columna}' no es numérica")
    return r[0]


def crear(tabla: str, tipo: str, y: str, x: str | None = None, agrupar_por: str | None = None,
          filtros: list[dict] | None = None, titulo: str | None = None) -> dict:
    tipo = (tipo or "").lower().strip()
    if tipo not in TIPOS:
        raise ErrorGrafica(f"Tipo '{tipo}' no válido. Usa: {', '.join(TIPOS)}")
    nombre, df = datos._buscar_tabla(tabla)
    df = datos._aplicar_filtros(df, filtros).copy()
    col_y = datos._buscar_columna(df, y)
    df["_y"] = _numerica(df, col_y)
    col_x = datos._buscar_columna(df, x) if x else None
    col_g = datos._buscar_columna(df, agrupar_por) if agrupar_por else None
    if tipo == "barras" and not col_g:
        col_g, col_x = col_x, None  # en barras, la "x" es el grupo
    if tipo == "barras" and not col_g:
        raise ErrorGrafica("Para barras hace falta agrupar_por (la columna de los grupos, p. ej. Fuel)")
    df = df[df["_y"].notna()]
    if df.empty:
        raise ErrorGrafica("No hay valores numéricos que dibujar con esos filtros")

    f = datos._ficha_psi(nombre)
    fuente = f"{f['accession']} {f.get('investigationAcronym') or ''} · NASA PSI".strip() if f else "NASA PSI"
    # Figure() y no pyplot: pyplot tiene estado global y falla si dos personas piden una gráfica a la vez
    fig = Figure(figsize=(8, 4.6), dpi=150)
    ax = fig.subplots()
    fig.subplots_adjust(left=0.1, right=0.97, top=0.82, bottom=0.16)
    datos_web: dict = {"tipo": tipo, "eje_y": _etiqueta(col_y)}

    if tipo == "barras":
        g = df.groupby(df[col_g].astype(str).str.strip())["_y"].agg(["mean", "count", "std"])
        g = g.sort_values("mean", ascending=False).head(MAX_BARRAS)
        posiciones = np.arange(len(g))
        ax.bar(posiciones, g["mean"], width=0.6, color=SERIES[0], edgecolor=FONDO, linewidth=2)
        ax.errorbar(posiciones, g["mean"], yerr=g["std"].fillna(0), fmt="none", ecolor=TEXTO_2,
                    elinewidth=1, capsize=3)
        for p, media, n, sd in zip(posiciones, g["mean"], g["count"], g["std"].fillna(0)):
            # la cifra va por encima de la barra de error, para que no se pisen
            ax.annotate(f"{_num(media)}  (n={int(n)})", (p, media + sd), xytext=(0, 5), textcoords="offset points",
                        ha="center", va="bottom", fontsize=9, color=TEXTO)
        ax.set_xticks(posiciones, [str(i)[:18] for i in g.index])
        ax.set_ylabel(f"Mean {_etiqueta(col_y)}", color=TEXTO_2, fontsize=9)
        ax.margins(y=0.2)
        subt = f"Mean by {col_g} (error bar = standard deviation) · {int(g['count'].sum())} tests · {fuente}"
        resumen = {str(k): {"media": datos._limpio(v["mean"]), "ensayos": int(v["count"])} for k, v in g.iterrows()}
        datos_web["filas"] = [{"grupo": str(k), "media": datos._limpio(v["mean"]), "ensayos": int(v["count"]),
                               "desviacion": datos._limpio(v["std"])} for k, v in g.iterrows()]
        titulo = titulo or f"{_etiqueta(col_y)} by {col_g}"
    else:
        grupos = [(None, df)]
        if col_g:
            valores = df[col_g].astype(str).str.strip()
            distintos = valores.value_counts()
            if len(distintos) > MAX_GRUPOS_COLOR:
                raise ErrorGrafica(f"'{col_g}' tiene {len(distintos)} grupos y solo caben {MAX_GRUPOS_COLOR} colores: "
                                   "filtra la tabla o usa una gráfica de barras")
            grupos = [(v, df[valores == v]) for v in distintos.index]
        if tipo == "dispersion":
            if not col_x:
                raise ErrorGrafica("Para dispersión hace falta x (la columna del eje horizontal)")
            df["_x"] = _numerica(df, col_x)
            datos_web["eje_x"] = _etiqueta(col_x)
            datos_web["puntos"] = []
            for i, (nombre_g, sub) in enumerate(grupos):
                sub = df.loc[sub.index]
                ax.scatter(sub["_x"], sub["_y"], s=22, color=SERIES[i], edgecolor=FONDO, linewidth=0.8,
                           label=nombre_g, zorder=3)
                datos_web["puntos"] += [{"x": datos._limpio(a), "y": datos._limpio(b), "grupo": nombre_g}
                                        for a, b in zip(sub["_x"], sub["_y"]) if pd.notna(a)][:500]
            ax.set_xlabel(_etiqueta(col_x), color=TEXTO_2, fontsize=9)
            ax.set_ylabel(_etiqueta(col_y), color=TEXTO_2, fontsize=9)
            ax.xaxis.set_major_formatter(_COMA)
            titulo = titulo or f"{_etiqueta(col_y)} frente a {_etiqueta(col_x)}"
        else:  # histograma
            bordes = np.histogram_bin_edges(df["_y"], bins="auto")[:41]
            datos_web["bordes"] = [datos._limpio(b) for b in bordes]
            datos_web["series"] = {}
            for i, (nombre_g, sub) in enumerate(grupos):
                cuentas, _ = np.histogram(sub["_y"], bins=bordes)
                ax.hist(sub["_y"], bins=bordes, histtype="stepfilled" if len(grupos) == 1 else "step",
                        color=SERIES[i], linewidth=2,
                        edgecolor=FONDO if len(grupos) == 1 else SERIES[i], label=nombre_g)
                datos_web["series"][str(nombre_g or col_y)] = [int(c) for c in cuentas]
            ax.set_xlabel(_etiqueta(col_y), color=TEXTO_2, fontsize=9)
            ax.set_ylabel("Number of tests", color=TEXTO_2, fontsize=9)
            ax.xaxis.set_major_formatter(_COMA)
            titulo = titulo or f"Distribución de {_etiqueta(col_y)}"
        if col_g:
            ley = ax.legend(title=col_g, frameon=False, fontsize=8.5, title_fontsize=8.5, labelcolor=TEXTO)
            ley.get_title().set_color(TEXTO_2)
        subt = f"{len(df)} tests · {fuente}"
        resumen = {"ensayos": int(len(df)),
                   "grupos": {str(n or "todos"): {"ensayos": int(len(s)), "media": datos._limpio(s["_y"].mean()),
                                                  "min": datos._limpio(s["_y"].min()), "max": datos._limpio(s["_y"].max())}
                              for n, s in grupos}}

    _estilo(ax, titulo[:90], subt[:140])
    config.DIR_GRAFICAS.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{datetime.now():%Y%m%d-%H%M%S}_{tipo}_{nombre}")[:90]
    archivo = config.DIR_GRAFICAS / f"{base}.png"
    n = 2
    while archivo.exists():
        archivo = config.DIR_GRAFICAS / f"{base}_{n}.png"
        n += 1
    fig.savefig(archivo, facecolor=FONDO)
    return {"tabla": nombre, "titulo": titulo, "tipo": tipo, "url": f"/ia/graficas/{archivo.name}",
            "resumen": resumen, "datos": datos_web}


def ruta(nombre: str):
    r = (config.DIR_GRAFICAS / Path(nombre).name).resolve()
    if not r.is_relative_to(config.DIR_GRAFICAS.resolve()) or not r.is_file():
        raise ErrorGrafica("No existe esa gráfica")
    return r
