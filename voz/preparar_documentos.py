"""Convierte las fichas de metadatos del NASA PSI (PSI-XX.json) en documentos Markdown
que la IA puede buscar: título, DOI, objetivos, enfoque, hipótesis, impacto y publicaciones.

    python preparar_documentos.py        # escribe en voz/documentos/psi/
    python ingestar.py                   # después, construir el índice

Hay que ejecutarlo solo una vez (o cuando se actualicen las fichas del PSI).
"""
import json
import re
import sys

from ia_llama import config

CAMPOS = [
    ("objective", "Objetivo"),
    ("approach", "Enfoque experimental"),
    ("hypothesis", "Hipótesis"),
    ("researchImpacts", "Impacto de la investigación"),
]


def ficha_a_markdown(d: dict) -> str:
    acronimo = d.get("investigationAcronym") or d["accession"]
    lineas = [
        f"# {d['accession']} · {acronimo}: {d.get('title', '')}",
        "",
        f"- Accesión PSI: {d['accession']}",
        f"- DOI: https://doi.org/{d['doi']}" if d.get("doi") else "- DOI: no disponible",
        f"- Programa: {d.get('flightProgram') or 'no indicado'}",
        f"- Hardware: {d.get('experimentHardware') or 'no indicado'}",
        f"- Área: {d.get('researchArea', '')} / {d.get('subResearchArea', '')}",
        f"- Periodo: {d.get('investigationStartDate', '?')} a {d.get('investigationEndDate', '?')}",
        f"- Licencia: {d.get('licenseName', '')}",
        "",
    ]
    for clave, titulo in CAMPOS:
        texto = (d.get(clave) or "").strip()
        if texto:
            lineas += [f"## {titulo}", "", texto, ""]
    pubs = d.get("publications") or []
    if pubs:
        lineas += ["## Publicaciones", ""]
        for p in pubs:
            doi = f" DOI {p['doi']}" if p.get("doi") else ""
            lineas.append(f"- {p.get('title', '').strip()} ({p.get('authorList', '').strip()}){doi}")
    return "\n".join(lineas).strip() + "\n"


def main() -> None:
    if not config.DIR_METADATOS.exists():
        sys.exit(f"No encuentro las fichas PSI en {config.DIR_METADATOS}")
    destino = config.DIR_DOCUMENTOS / "psi"
    destino.mkdir(parents=True, exist_ok=True)
    n = 0
    for ruta in sorted(config.DIR_METADATOS.glob("PSI-*.json")):
        d = json.loads(ruta.read_text(encoding="utf-8"))
        acronimo = re.sub(r"[^A-Za-z0-9-]+", "_", d.get("investigationAcronym") or "").strip("_")
        nombre = f"{d['accession']}_{acronimo}.md" if acronimo else f"{d['accession']}.md"
        (destino / nombre).write_text(ficha_a_markdown(d), encoding="utf-8")
        n += 1
    print(f"{n} fichas convertidas en {destino}")


if __name__ == "__main__":
    main()
