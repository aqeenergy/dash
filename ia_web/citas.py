"""Citas: qué datos consultó la IA para cada respuesta.

Convierte cada llamada a herramienta (nombre, argumentos, resultado) en las citas del protocolo
de la web:

    {"tipo": "tabla",     "investigacion", "accesion", "titulo", "doi", "url",
                          "tabla", "consulta", "filas"}
    {"tipo": "documento", "investigacion", "accesion", "titulo", "doi", "url",
                          "fuente", "pagina", "extracto"}

Las citas dicen QUÉ se consultó para una respuesta, no qué frase sale de qué fuente.
Solo lee: las fichas PSI-XX.json de base_de_datos (vía ia_llama.datos) y el resultado de la
herramienta. Nunca inventa campos: si una ficha no tiene DOI, la cita sale sin DOI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from ia_llama import datos

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from biblioteca import _slug  # noqa: E402  (same file ids as the web's text library)


def _archivo_tabla(tabla: str) -> str:
    """Id of the table in the text library (static/library/<slug>.csv)."""
    return _slug(tabla) + ".csv"


def _archivo_ficha(accesion: str) -> str:
    return _slug(accesion) + ".md" if accesion else ""

_SIN_CITA = {"listar_tablas"}  # el catálogo no es un dato consultado


def _ficha(accesion_o_tabla: str) -> dict:
    ficha = datos._ficha_psi(accesion_o_tabla) or {}
    acc = ficha.get("accession") or (re.match(r"PSI-\d+", accesion_o_tabla or "") or [None])[0] or ""
    doi = str(ficha.get("doi") or "")
    return {
        "investigacion": ficha.get("investigationAcronym") or acc or "",
        "accesion": acc,
        "titulo": ficha.get("title") or "",
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else "",
    }


def _filtros_texto(filtros) -> str:
    partes = []
    for f in filtros or []:
        if isinstance(f, dict) and f.get("columna"):
            partes.append(f"{f['columna']} {f.get('operador', '==')} {f.get('valor', '')}")
    return " y ".join(partes)


def _cita_tabla(nombre: str, argumentos: dict, resultado: dict) -> dict | None:
    tabla = str(resultado.get("tabla") or argumentos.get("tabla") or "")
    if not tabla:
        return None
    filtros = _filtros_texto(argumentos.get("filtros"))
    if nombre == "estadisticas_tabla":
        cols = ", ".join(map(str, argumentos.get("columnas") or []))
        consulta = f"Estadísticas de {cols}" if cols else "Estadísticas"
        if resultado.get("agrupado_por"):
            consulta += f" agrupadas por {resultado['agrupado_por']}"
        estad = resultado.get("estadisticas") or {}
        if resultado.get("agrupado_por"):
            # nº de ensayos = suma de 'count' de la primera columna en cada grupo
            filas = 0
            for grupo in estad.values():
                cuenta = next((v for k, v in grupo.items() if k.endswith("_count")), 0)
                filas += int(cuenta or 0)
        else:
            filas = int(resultado.get("filas_usadas") or 0)
    elif nombre == "consultar_tabla":
        consulta = "Ensayos concretos"
        if argumentos.get("ordenar_por"):
            consulta += f" ordenados por {argumentos['ordenar_por']}"
        filas = int(resultado.get("filas_que_cumplen") or 0)
    else:  # describir_tabla
        consulta = "Descripción de la tabla: columnas, tipos y rangos"
        filas = int(resultado.get("filas") or 0)
    if filtros:
        consulta += f" (filtro: {filtros})"
    columnas = [str(c) for c in (argumentos.get("columnas") or [])]
    for extra in (resultado.get("agrupado_por"), argumentos.get("ordenar_por")):
        if extra and str(extra) not in columnas:
            columnas.append(str(extra))
    columnas += [str(f["columna"]) for f in argumentos.get("filtros") or [] if isinstance(f, dict) and f.get("columna")]
    return {"tipo": "tabla", **_ficha(tabla), "tabla": tabla, "consulta": consulta, "filas": filas,
            "archivo": _archivo_tabla(tabla), "columnas": list(dict.fromkeys(columnas))}


def _citas_documentos(resultado: dict) -> list[dict]:
    salida = []
    for r in resultado.get("resultados") or []:
        fuente = str(r.get("fuente") or "")
        m = re.search(r"PSI-\d+", fuente)
        base = _ficha(m.group(0)) if m else {"investigacion": fuente.rsplit("/", 1)[-1], "accesion": "",
                                              "titulo": "", "doi": "", "url": ""}
        pagina = r.get("pagina")
        salida.append({
            "tipo": "documento", **base,
            "fuente": fuente,
            "pagina": None if pagina in (None, "None", "") else pagina,
            "extracto": " ".join(str(r.get("texto") or "").split())[:700],
            "archivo": _archivo_ficha(base["accesion"]),
        })
    return salida


def citas_de(nombre: str, argumentos: dict | None, resultado: dict | None) -> list[dict]:
    """Citas para una llamada a herramienta. Lista vacía si no hubo datos consultados."""
    argumentos, resultado = argumentos or {}, resultado or {}
    if nombre in _SIN_CITA or not isinstance(resultado, dict) or "error" in resultado:
        return []
    if nombre == "buscar_documentos":
        return _citas_documentos(resultado)
    if nombre in {"consultar_tabla", "estadisticas_tabla", "describir_tabla"}:
        c = _cita_tabla(nombre, argumentos, resultado)
        return [c] if c else []
    if nombre == "crear_grafica" and resultado.get("tabla"):
        tabla = str(resultado["tabla"])
        cols = [str(c) for c in (argumentos.get("y"), argumentos.get("x"), argumentos.get("agrupar_por")) if c]
        filtros = _filtros_texto(argumentos.get("filtros"))
        consulta = f"Chart ({resultado.get('tipo')}): " + ", ".join(cols) + (f" (filter: {filtros})" if filtros else "")
        res = resultado.get("resumen") or {}
        filas = res.get("ensayos") if isinstance(res.get("ensayos"), int) else sum(
            int(v.get("ensayos") or 0) for v in res.values() if isinstance(v, dict))
        return [{"tipo": "tabla", **_ficha(tabla), "tabla": tabla, "consulta": consulta, "filas": filas,
                 "archivo": _archivo_tabla(tabla), "columnas": cols}]
    if nombre == "evaluar_escenario":
        esc = {k: v for k, v in (resultado.get("escenario") or {}).items()
               if v not in (None, "", []) and k != "terminos_buscados"}
        consulta = "Closest tests to the scenario: " + ", ".join(f"{k}={v}" for k, v in esc.items())
        salida = []
        for r in resultado.get("resultados") or []:
            tabla = str(r.get("tabla") or "")
            if tabla:
                salida.append({"tipo": "tabla", **_ficha(tabla), "tabla": tabla, "consulta": consulta,
                               "filas": int(r.get("ensayos_coincidentes") or 0), "archivo": _archivo_tabla(tabla),
                               "columnas": []})
        return salida
    return []


def clave(cita: dict) -> tuple:
    """Para no repetir la misma cita dentro de una respuesta."""
    if cita["tipo"] == "tabla":
        return ("tabla", cita["tabla"], cita["consulta"])
    return ("documento", cita["fuente"], cita.get("pagina"), cita["extracto"][:80])
