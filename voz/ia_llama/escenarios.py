"""Evaluación de escenarios: busca los ensayos del NASA PSI más parecidos a un escenario de incendio
(material o combustible, oxígeno, flujo de aire, presión) y devuelve qué pasó en ellos.

No es un modelo de predicción ni una evaluación certificada: compara con ensayos reales en
microgravedad y avisa cuando el escenario cae fuera de las condiciones ensayadas.

Cada experimento mide cosas distintas y con nombres de columna distintos, así que en lugar de
adivinar las columnas, aquí se describen a mano las tablas útiles para un escenario de incendio.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from . import datos

# Qué columna es cada cosa en cada experimento. o2_fraccion: el O2 viene como fracción (0,21) y no
# en % (21). presion_a_atm: factor para pasar la presión de la tabla a atmósferas.
EXPERIMENTOS = [
    # ---- sólidos: telas, plásticos, materiales de la nave
    {"tabla": "PSI-98_Experimental table_SAFFIRE-1", "tipo": "solido", "id": "Sample Number", "id_valido": r"^S\d+$",
     "material": "Material", "o2": "Percent O2", "flujo": "Air Flow (cm/s)",
     "resultados": ["Burn Time (s)", "Flow Direction", "Sample Thickness (cm)"]},
    {"tabla": "PSI-99_Experimental table_SAFFIRE-2", "tipo": "solido", "id": "Sample Number", "id_valido": r"^\d+-\d+$",
     "material": "Material", "rellenar_material": True, "o2": "Percent O2 (Note 1)", "flujo": "Air Flow (cm/s)",
     "resultados": ["Burn Time (s)", "Flow Direction", "Samle Thickness", "?-g Burn Length", "?-g Spread Length",
                    "1-g Burn Length", "1-g Spread Rate"]},
    {"tabla": "PSI-100_Experimental table_SAFFIRE-3", "tipo": "solido", "id": "Sample Number", "id_valido": r"^S\d+$",
     "material": "Material", "flujo": "Air Flow", "resultados": ["Sample Thickness"]},
    {"tabla": "PSI-26_Experimental table_BASS", "tipo": "solido", "material": "Fuel Sample Material", "resultados": []},
    {"tabla": "PSI-25_Experimental table_BASS-II", "tipo": "solido", "material": "Fuel Sample Material",
     "o2": "Calibrated  initial O2 % by vol", "resultados": ["Air display", "Calibrated final O2 % by vol"]},
    {"tabla": "PSI-102_Experimental table_SAME", "tipo": "solido", "material": "Sample Material",
     "flujo": "Air Flow (cm/s)", "resultados": ["Weight loss rate (mg/min)"]},
    # ---- líquidos: gotas de combustible
    {"tabla": "PSI-69_Experimental table_FLEX", "tipo": "liquido", "material": "Fuel",
     "o2": "O initial ambient composition; mole fraction", "o2_fraccion": True,
     "presion": "Ambient pressure; mmHg", "presion_a_atm": 1 / 760,
     "resultados": ["Test end", "Burn time; s", "Burning rate; mm", "Droplet initial diameter; mm",
                    "CO initial ambient composition; mole fraction", "He initial ambient composition; mole fraction"]},
    {"tabla": "PSI-39_Experimental table_CFI", "tipo": "liquido", "material": "Fuel", "o2": "Oxygen", "o2_fraccion": True,
     "presion": "Pressure", "presion_a_atm": 1.0, "resultados": ["Helium", "Nitrogen"]},
    # ---- gases
    {"tabla": "PSI-159_Experimental table_CFI-G_Inverse Flames", "tipo": "gas", "material": "Fuel", "o2": "XO2",
     "o2_fraccion": True, "presion": "approx p (bar)", "presion_a_atm": 0.98692,
     "resultados": ["Hot ignition", "burn time (sec)", "Self -ext or flow term", "Comments"]},
]

# Nombres más claros para algunas columnas (subíndices y "µ" perdidos al exportar)
NOMBRES_CLAROS = {
    "O initial ambient composition; mole fraction": "O2 inicial (fracción molar)",
    "N initial ambient composition; mole fraction": "N2 inicial (fracción molar)",
    "?-g Burn Length": "µg Burn Length",
    "?-g Spread Length": "µg Spread Rate",
    "CO initial ambient composition; mole fraction": "CO2 inicial (fracción molar)",
    "He initial ambient composition; mole fraction": "He inicial (fracción molar)",
    "Burning rate; mm": "Burning rate (prob. mm²/s, sin confirmar)",
}

# Códigos de CFI-G
COLUMNAS_CON_CODIGOS = {"Self -ext or flow term"}
CODIGOS = {"SE": "se apagó sola (SE)", "FT": "se cortó el flujo de combustible (FT)"}

# Español -> términos que aparecen en los datos
SINONIMOS = {
    "algodon": ["cotton", "sibal"], "tela": ["fabric", "sibal", "cotton"], "tejido": ["fabric", "sibal", "cotton"],
    "fibra de vidrio": ["fiberglass", "sibal"], "plexiglas": ["pmma"], "metacrilato": ["pmma"], "acrilico": ["pmma"],
    "metilmetacrilato": ["pmma"], "silicona": ["silicone"], "teflon": ["teflon"], "kapton": ["kapton"],
    "nomex": ["nomex"], "cera": ["wax", "candle"], "vela": ["candle"], "mecha": ["lampwick"],
    "heptano": ["heptane"], "metanol": ["methanol"], "decano": ["decane"], "dodecano": ["c12h26", "dodecane"],
    "etanol": ["ethanol"], "octano": ["octane"], "propano": ["propane"], "etano": ["ethane"], "butano": ["butane"],
    "etileno": ["c2h4", "ethylene"], "metano": ["ch4", "methane"],
}


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _terminos(material: str) -> list[str]:
    m = _norm(material).strip()
    if not m:
        return []
    terminos = {m}
    for es, en in SINONIMOS.items():
        if es in m:
            terminos.update(en)
    return sorted(terminos)


def _primer_numero(serie: pd.Series) -> pd.Series:
    """Primer número de cada celda: '21.5 - 21.7' -> 21.5, '~ 22.1' -> 22.1, '20 cm/s' -> 20."""
    texto = serie.astype(str).str.replace(",", ".", regex=False)
    return pd.to_numeric(texto.str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")


def _limpio(v):
    return datos._limpio(v)


def evaluar(material: str | None = None, oxigeno_pct: float | None = None, flujo_aire_cm_s: float | None = None,
            presion_atm: float | None = None, tipo: str | None = None, max_ensayos: int = 4) -> dict:
    terminos = _terminos(material or "")
    tipo = (tipo or "").lower().strip() or None
    tablas = datos.tablas()
    salida = []
    for exp in EXPERIMENTOS:
        if tipo and exp["tipo"] != tipo:
            continue
        df = tablas.get(exp["tabla"])
        if df is None:
            continue
        df = df.copy()
        if exp.get("id") and exp["id"] in df.columns:  # fuera filas de notas y de calibración
            df = df[df[exp["id"]].astype(str).str.strip().str.match(exp["id_valido"])]
        mat = exp["material"]
        if exp.get("rellenar_material"):  # celdas en blanco = mismo material que la fila anterior
            df[mat] = df[mat].ffill()
        if terminos:
            texto = df[mat].astype(str).map(_norm)
            df = df[texto.apply(lambda t: any(term in t for term in terminos))]
        if df.empty:
            continue

        # Condiciones normalizadas: O2 en %, flujo en cm/s, presión en atm
        cond = pd.DataFrame(index=df.index)
        if exp.get("o2") in df.columns:
            cond["o2_pct"] = _primer_numero(df[exp["o2"]]) * (100 if exp.get("o2_fraccion") else 1)
        if exp.get("flujo") in df.columns:
            cond["flujo_cm_s"] = _primer_numero(df[exp["flujo"]])
        if exp.get("presion") in df.columns:
            cond["presion_atm"] = _primer_numero(df[exp["presion"]]) * exp.get("presion_a_atm", 1)

        # (valor pedido, escala para la distancia, margen para considerarlo "dentro de lo ensayado")
        pedido = {"o2_pct": (oxigeno_pct, 5.0, 1.5), "flujo_cm_s": (flujo_aire_cm_s, 10.0, 2.0),
                  "presion_atm": (presion_atm, 0.5, 0.1)}
        distancia = pd.Series(0.0, index=df.index)
        comparadas, fuera = [], []
        for col, (valor, escala, margen) in pedido.items():
            if valor is None or col not in cond or cond[col].notna().sum() == 0:
                continue
            v = float(valor)
            comparadas.append(col)
            distancia += ((cond[col] - v).abs() / escala).fillna(3)
            lo, hi = cond[col].min(), cond[col].max()
            if v < lo - margen or v > hi + margen:
                fuera.append(f"{col}={v:g} fuera de lo ensayado [{_limpio(lo)} – {_limpio(hi)}]")
        orden = distancia.sort_values().index[:max_ensayos]

        ensayos = []
        for i in orden:
            fila = {"material": str(df.at[i, mat])}
            for col in ("o2_pct", "flujo_cm_s", "presion_atm"):
                if col in cond and pd.notna(cond.at[i, col]):
                    fila[col] = _limpio(round(float(cond.at[i, col]), 3))
            for r in exp["resultados"]:
                if r in df.columns and pd.notna(df.at[i, r]) and str(df.at[i, r]).strip() not in ("", "-"):
                    valor = _limpio(df.at[i, r])
                    valor = CODIGOS.get(str(valor).strip(), valor) if r in COLUMNAS_CON_CODIGOS else valor
                    fila[NOMBRES_CLAROS.get(r, r)] = valor
            ensayos.append(fila)

        rangos = {col: [_limpio(cond[col].min()), _limpio(cond[col].max())]
                  for col in cond.columns if cond[col].notna().any()}
        f = datos._ficha_psi(exp["tabla"])
        salida.append({
            "tabla": exp["tabla"],
            "investigacion": f"{f['accession']} {f.get('investigationAcronym') or ''}".strip() if f else None,
            "tipo": exp["tipo"],
            "ensayos_coincidentes": int(len(df)),
            "condiciones_ensayadas": rangos,
            "comparado_por": comparadas,
            "fuera_de_lo_ensayado": fuera,
            "ensayos_mas_parecidos": ensayos,
        })

    if not salida:
        return {"aviso": f"No hay ensayos en el PSI con '{material}'" + (f" de tipo {tipo}" if tipo else "") +
                ". Prueba con el nombre en inglés o un material parecido (cotton, PMMA, Nomex, silicone, "
                "heptane, methanol...).", "resultados": []}
    # Primero los experimentos que permiten comparar condiciones y en los que el escenario cae dentro de lo ensayado
    salida.sort(key=lambda r: (0 if r["comparado_por"] else 1, len(r["fuera_de_lo_ensayado"]),
                               -len(r["comparado_por"]), -r["ensayos_coincidentes"]))
    return {
        "escenario": {"material": material, "oxigeno_pct": oxigeno_pct, "flujo_aire_cm_s": flujo_aire_cm_s,
                      "presion_atm": presion_atm, "tipo": tipo, "terminos_buscados": terminos},
        "resultados": salida[:6],
        "aviso": "Comparación con ensayos reales en microgravedad del NASA PSI; no es una predicción ni una "
                 "evaluación de seguridad certificada.",
    }
