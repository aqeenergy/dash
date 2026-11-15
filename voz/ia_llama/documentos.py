"""Documentos subidos por el usuario y documentos creados por la IA.

Subir:  la web envía un PDF, DOCX, TXT o MD a POST /ia/documentos. Se guarda en documentos_subidos/,
        se trocea, se calculan sus embeddings y se añade a un índice propio (indice_subidos/), que se
        combina con el índice de las fichas PSI. A partir de ese momento la IA puede buscar en él,
        leerlo entero y citarlo.
Crear:  la IA llama a crear_documento con un texto en Markdown; se guarda en documentos_generados/
        como .md, .docx y .pdf, y la web lo descarga en GET /ia/generados/<archivo>.
"""
from __future__ import annotations

import logging
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from . import config, rag

log = logging.getLogger(__name__)

EXTENSIONES_SUBIDA = {".pdf", ".docx", ".txt", ".md"}
_candado = threading.Lock()  # dos subidas a la vez no deben pisarse el índice


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


# ============================================================================ subir

def subir(nombre_original: str, contenido: bytes) -> dict:
    """Guarda e indexa un documento subido. Devuelve un resumen para la web."""
    extension = Path(nombre_original or "").suffix.lower()
    if extension not in EXTENSIONES_SUBIDA:
        raise ErrorDocumento(f"Formato no admitido ({extension or 'sin extensión'}). "
                             f"Usa: {', '.join(sorted(EXTENSIONES_SUBIDA))}")
    if len(contenido) > config.MAX_MB_SUBIDA * 1024 * 1024:
        raise ErrorDocumento(f"El archivo supera el máximo de {config.MAX_MB_SUBIDA:g} MB")
    if not contenido:
        raise ErrorDocumento("El archivo está vacío")

    config.DIR_SUBIDOS.mkdir(parents=True, exist_ok=True)
    with _candado:
        ruta = _ruta_libre(config.DIR_SUBIDOS, _nombre_seguro(nombre_original))
        ruta.write_bytes(contenido)
        try:
            fragmentos = rag.fragmentos_de(ruta, f"subidos/{ruta.name}")
        except Exception as e:
            ruta.unlink(missing_ok=True)
            raise ErrorDocumento(f"No se pudo leer el documento: {e}") from e
        if not fragmentos:
            ruta.unlink(missing_ok=True)
            raise ErrorDocumento("No se ha podido extraer texto (¿es un PDF escaneado como imagen?)")

        anterior = rag.Indice.cargar(config.DIR_INDICE_SUBIDOS) if (config.DIR_INDICE_SUBIDOS / "fragmentos.json").exists() \
            else rag.Indice([], None)
        for i, f in enumerate(fragmentos):
            f.id = len(anterior.fragmentos) + i
        vectores = None
        if config.GEMINI_API_KEY:
            try:  # pocos reintentos: la web está esperando
                vectores = rag.embeber([f.texto for f in fragmentos], "RETRIEVAL_DOCUMENT", reintentos=2)
            except Exception as e:
                log.warning("Sin embeddings para %s (%s): se buscará por palabras clave", ruta.name, e)
        nuevo = anterior.unir(rag.Indice(fragmentos, vectores))
        nuevo.guardar(config.DIR_INDICE_SUBIDOS)

    from . import herramientas  # aquí para evitar importaciones circulares
    herramientas.recargar_indice()
    return {"nombre": ruta.name, "fuente": f"subidos/{ruta.name}", "fragmentos": len(fragmentos),
            "caracteres": sum(len(f.texto) for f in fragmentos), "busqueda_semantica": vectores is not None}


# ============================================================================ listar y leer

def listar() -> dict:
    from . import herramientas

    por_fuente: dict[str, int] = {}
    for f in herramientas.indice().fragmentos:
        por_fuente[f.fuente] = por_fuente.get(f.fuente, 0) + 1
    subidos = [{"nombre": k, "fragmentos": v} for k, v in por_fuente.items() if k.startswith("subidos/")]
    base = [{"nombre": k, "fragmentos": v} for k, v in por_fuente.items() if not k.startswith("subidos/")]
    generados = sorted(p.name for p in config.DIR_GENERADOS.glob("*.md")) if config.DIR_GENERADOS.exists() else []
    return {"subidos_por_el_usuario": subidos, "documentos_base": base, "creados_por_la_ia": generados}


def _ruta_documento(nombre: str) -> Path:
    """Encuentra un documento por su nombre (con o sin carpeta, sin distinguir mayúsculas)."""
    limpio = nombre.strip().replace("\\", "/")
    candidatos = []
    if limpio.startswith("subidos/"):
        candidatos.append(config.DIR_SUBIDOS / limpio.split("/", 1)[1])
    candidatos += [config.DIR_DOCUMENTOS / limpio, config.DIR_SUBIDOS / limpio, config.DIR_GENERADOS / limpio]
    for c in candidatos:
        try:
            c = c.resolve()
        except OSError:
            continue
        dentro = any(str(c).startswith(str(d.resolve())) for d in
                     (config.DIR_DOCUMENTOS, config.DIR_SUBIDOS, config.DIR_GENERADOS))
        if dentro and c.is_file():
            return c
    clave = Path(limpio).name.lower()
    for d in (config.DIR_SUBIDOS, config.DIR_DOCUMENTOS, config.DIR_GENERADOS):
        if d.exists():
            for p in d.rglob("*"):
                if p.is_file() and (p.name.lower() == clave or p.stem.lower() == Path(clave).stem):
                    return p
    raise ErrorDocumento(f"No encuentro el documento '{nombre}'. Usa listar_documentos para ver los nombres.")


def leer(nombre: str, parte: int = 1) -> dict:
    """Texto completo de un documento, en partes de MAX_CARACTERES_LECTURA caracteres."""
    ruta = _ruta_documento(nombre)
    texto = "\n\n".join(t for _, t in rag.leer_paginas(ruta) if t.strip())
    tam = config.MAX_CARACTERES_LECTURA
    total = max(1, -(-len(texto) // tam))
    parte = min(max(1, int(parte or 1)), total)
    return {"documento": ruta.name, "parte": parte, "partes_totales": total,
            "texto": texto[(parte - 1) * tam: parte * tam]}


# ============================================================================ crear

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
    if not str(ruta).startswith(str(config.DIR_GENERADOS.resolve())) or not ruta.is_file():
        raise ErrorDocumento("No existe ese documento")
    return ruta
