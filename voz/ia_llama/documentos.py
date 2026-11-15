"""Documentos que crea la IA (informe, resumen, ficha...) en Markdown, Word y PDF.
Traído de la última versión de la IA (NASA-SPACE-APPS/ia_voz_texto), solo la parte de crear."""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


class ErrorDocumento(ValueError):
    """Error con un mensaje pensado para mostrarlo al usuario."""

def _nombre_seguro(nombre: str, extension: str | None = None) -> str:
    base = Path(nombre).stem if extension is None else nombre
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")[:80] or "documento"
    return base + (extension if extension is not None else Path(nombre).suffix.lower())


def _ruta_libre(directorio: Path, nombre: str) -> Path:
    ruta = directorio / nombre
    n = 2
    while ruta.exists():
        ruta = directorio / f"{Path(nombre).stem}_{n}{Path(nombre).suffix}"
        n += 1
    return ruta


def _dentro_de(ruta: Path, directorio: Path) -> bool:
    """¿Está `ruta` dentro de `directorio`? (Comparar con startswith dejaría pasar "documentos_privados/...")."""
    try:
        return ruta.resolve().is_relative_to(directorio.resolve())
    except OSError:
        return False


def _a_latin1(texto: str) -> str:
    """Las fuentes integradas del PDF solo tienen caracteres latinos: sustituir el resto."""
    cambios = {"₂": "2", "₃": "3", "₄": "4", "³": "3", "—": "-", "–": "-", "“": '"', "”": '"', "‘": "'",
               "’": "'", "…": "...", "•": "-", "→": "->", "≈": "~", "≤": "<=", "≥": ">=", "µ": "u", "×": "x"}
    for a, b in cambios.items():
        texto = texto.replace(a, b)
    return texto.encode("latin-1", "replace").decode("latin-1")


def _lineas_markdown(contenido: str):
    """Recorre el Markdown y devuelve (tipo, texto): h1, h2, h3, viñeta, numerada, párrafo, vacía."""
    for linea in contenido.splitlines():
        l = linea.rstrip()
        if not l.strip():
            yield "vacia", ""
        elif m := re.match(r"^(#{1,3})\s+(.*)", l):
            yield f"h{len(m.group(1))}", m.group(2)
        elif m := re.match(r"^\s*[-*•]\s+(.*)", l):
            yield "vineta", m.group(1)
        elif m := re.match(r"^\s*\d+[.)]\s+(.*)", l):
            yield "numerada", m.group(1)
        else:
            yield "parrafo", l


def _docx(titulo: str, contenido: str, ruta: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_heading(titulo, level=0)
    for tipo, texto in _lineas_markdown(contenido):
        if tipo == "vacia":
            continue
        if tipo in ("h1", "h2", "h3"):
            doc.add_heading(texto, level=int(tipo[1]))
            continue
        estilo = {"vineta": "List Bullet", "numerada": "List Number"}.get(tipo)
        p = doc.add_paragraph(style=estilo) if estilo else doc.add_paragraph()
        for i, trozo in enumerate(re.split(r"\*\*(.+?)\*\*", texto)):  # **negrita**
            if trozo:
                p.add_run(trozo).bold = (i % 2 == 1)
    doc.save(str(ruta))


def _pdf(titulo: str, contenido: str, ruta: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 9, _a_latin1(titulo))
    pdf.ln(3)
    tamanos = {"h1": 15, "h2": 13, "h3": 12}
    numero = 0
    for tipo, texto in _lineas_markdown(contenido):
        texto = _a_latin1(texto)
        pdf.set_x(pdf.l_margin)
        numero = numero + 1 if tipo == "numerada" else 0
        if tipo == "vacia":
            pdf.ln(2)
        elif tipo in tamanos:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", tamanos[tipo])
            pdf.multi_cell(0, 7, texto.replace("**", ""))
        else:
            pdf.set_font("Helvetica", "", 11)
            prefijo = "- " if tipo == "vineta" else (f"{numero}. " if tipo == "numerada" else "")
            pdf.multi_cell(0, 6, prefijo + texto, markdown=True)
    pdf.output(str(ruta))


def crear(titulo: str, contenido: str) -> dict:
    """Guarda un documento redactado por la IA en Markdown, Word y PDF."""
    titulo = (titulo or "").strip()[:150] or "Documento"
    contenido = (contenido or "").strip()
    if len(contenido) < 20:
        raise ErrorDocumento("El contenido está vacío o es demasiado corto")
    contenido = contenido[:40000]
    config.DIR_GENERADOS.mkdir(parents=True, exist_ok=True)
    base = _nombre_seguro(f"{datetime.now():%Y%m%d-%H%M}_{titulo}", "")
    ruta_md = _ruta_libre(config.DIR_GENERADOS, base + ".md")
    base = ruta_md.stem
    ruta_md.write_text(f"# {titulo}\n\n{contenido}\n", encoding="utf-8")
    archivos = [{"formato": "md", "nombre": ruta_md.name}]
    for formato, funcion in (("docx", _docx), ("pdf", _pdf)):
        ruta = config.DIR_GENERADOS / f"{base}.{formato}"
        try:
            funcion(titulo, contenido, ruta)
            archivos.append({"formato": formato, "nombre": ruta.name})
        except Exception as e:  # si falla un formato, los demás siguen sirviendo
            log.warning("No se pudo crear %s: %s", ruta.name, e)
    for a in archivos:
        a["url"] = f"/ia/generados/{a['nombre']}"
    return {"titulo": titulo, "archivos": archivos}


def ruta_generado(nombre: str) -> Path:
    """Ruta segura de un documento creado (nunca fuera de documentos_generados/)."""
    ruta = (config.DIR_GENERADOS / Path(nombre).name).resolve()
    if not _dentro_de(ruta, config.DIR_GENERADOS) or not ruta.is_file():
        raise ErrorDocumento("No existe ese documento")
    return ruta
