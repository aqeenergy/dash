"""Recuperación ligera (BM25) sobre los documentos PSI de data/psi.

Formatos admitidos: .md, .txt (con front matter opcional) y .pdf.
Front matter (entre líneas '---'):
    id: BASS            -> prefijo de los identificadores de fragmento
    title: ...
    gravity: 0g | 1g | 0g,1g
    source: SEED | PSI
Los .md se trocean por encabezados '## '; .txt y .pdf por bloques de ~1200 caracteres.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

STOPWORDS = set(
    """a al algo como con de del el en entre es esta este la las lo los mas o para
    por que se sin sobre su sus un una y the of and to in on for with by is are was
    at as an be from that this it or""".split()
)


@dataclass
class Chunk:
    id: str
    doc_id: str
    title: str
    heading: str
    text: str
    gravity: set[str]
    source: str
    tokens: list[str] = field(default_factory=list, repr=False)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tokenize(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9.\-]*", _norm(s)) if t not in STOPWORDS and len(t) > 1]


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, raw[m.end():]


def _split_fixed(text: str, size: int = 1200) -> list[tuple[str, str]]:
    paras, out, buf = re.split(r"\n\s*\n", text), [], ""
    for p in paras:
        if buf and len(buf) + len(p) > size:
            out.append(("", buf.strip()))
            buf = ""
        buf += p + "\n\n"
    if buf.strip():
        out.append(("", buf.strip()))
    return out


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def load_corpus(folder: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(folder.glob("**/*")):
        if path.suffix.lower() not in {".md", ".txt", ".pdf"}:
            continue
        raw = _read_pdf(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        doc_id = re.sub(r"[^A-Za-z0-9]+", "-", meta.get("id", path.stem)).strip("-").upper()
        title = meta.get("title", path.stem)
        gravity = {g.strip().lower() for g in meta.get("gravity", "").split(",") if g.strip()}
        source = meta.get("source", "PSI").upper()

        if path.suffix.lower() == ".md" and "\n## " in "\n" + body:
            parts = re.split(r"(?m)^## ", body)
            sections = []
            intro = parts[0].strip()
            for part in parts[1:]:
                heading, _, text = part.partition("\n")
                sections.append((heading.strip(), text.strip()))
            if intro and not intro.upper().startswith("SEED"):  # el aviso SEED ya viaja como metadato
                sections.insert(0, ("Resumen", intro))
        else:
            sections = _split_fixed(body)

        for i, (heading, text) in enumerate(sections, 1):
            if not text:
                continue
            c = Chunk(f"{doc_id}-{i:02d}", doc_id, title, heading, text, gravity, source)
            c.tokens = tokenize(f"{title} {heading} {text}")
            chunks.append(c)
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tf = [Counter(c.tokens) for c in chunks]
        self.avgdl = (sum(len(c.tokens) for c in chunks) / len(chunks)) if chunks else 0
        df = Counter(t for c in chunks for t in set(c.tokens))
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, query_tokens: list[str]) -> list[tuple[float, Chunk]]:
        out = []
        for c, tf in zip(self.chunks, self.tf):
            dl, s = len(c.tokens), 0.0
            for t in query_tokens:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append((s, c))
        out.sort(key=lambda x: x[0], reverse=True)
        return out


def gravity_regime(g: float) -> str:
    if g <= 0.01:
        return "0g"
    if g >= 0.99:
        return "1g"
    return "partial"


def expand_query(params: dict) -> str:
    """Convierte los parámetros del dashboard en términos de búsqueda."""
    g, o2, p_psi = params["gravity_g"], params["o2_pct"], params["pressure_psi"]
    terms = [params.get("material", ""), params.get("question", "")]
    regime = gravity_regime(g)
    if regime == "0g":
        terms.append("microgravity microgravedad iss flujo opuesto concurrente esferica sin flotabilidad")
    elif regime == "1g":
        terms.append("gravedad terrestre 1g flotabilidad propagacion ascendente nasa-std-6001 ensayo")
    else:
        terms.append("gravedad parcial lunar marciana flotabilidad microgravedad gravedad terrestre")
    if o2 > 25:
        terms.append("oxigeno enriquecido limites inflamabilidad")
    if p_psi < 14:
        terms.append("presion reducida atmosferas exploracion")
    if params.get("airflow_cm_s", 0) > 0:
        terms.append("flujo velocidad ventilacion convección forzada")
    return " ".join(terms)


def retrieve(index: BM25Index, params: dict, k: int = 6) -> list[dict]:
    ranked = [(s, c) for s, c in index.score(tokenize(expand_query(params)))]
    selected: list[tuple[float, Chunk]] = [x for x in ranked[:k] if x[0] > 0]

    # Motor de Extrapolación: en gravedad parcial garantiza fragmentos de ambos extremos.
    if gravity_regime(params["gravity_g"]) == "partial":
        for bound in ("0g", "1g"):
            have = sum(1 for _, c in selected if bound in c.gravity)
            for s, c in ranked:
                if have >= 2:
                    break
                if bound in c.gravity and all(c is not x for _, x in selected):
                    selected.append((s, c))
                    have += 1

    return [
        {
            "id": c.id,
            "doc": c.doc_id,
            "title": c.title,
            "heading": c.heading,
            "gravity": sorted(c.gravity),
            "source": c.source,
            "score": round(s, 2),
            "text": c.text,
        }
        for s, c in selected
    ]


def format_context(hits: list[dict]) -> str:
    return "\n\n".join(
        f"[{h['id']}] {h['title']} — {h['heading']} (gravedad: {', '.join(h['gravity']) or 'n/d'}; fuente: {h['source']})\n{h['text']}"
        for h in hits
    )
