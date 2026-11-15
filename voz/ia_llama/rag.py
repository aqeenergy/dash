"""RAG: trocea documentos, genera embeddings con Gemini y busca los fragmentos más relevantes.

Si los embeddings no están disponibles (sin clave, sin cuota o índice sin vectores) se usa
una búsqueda por palabras clave (BM25), así la IA nunca se queda sin poder buscar.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import config

log = logging.getLogger(__name__)

EXTENSIONES_TEXTO = {".txt", ".md"}
EXTENSIONES = EXTENSIONES_TEXTO | {".pdf"}


@dataclass
class Fragmento:
    id: int
    fuente: str
    pagina: int | None
    texto: str


# ----------------------------------------------------------------------------- lectura y troceado

def _leer_paginas(ruta: Path) -> list[tuple[int | None, str]]:
    """Devuelve [(número_de_página, texto)]. Los .txt/.md cuentan como una sola 'página' (None)."""
    if ruta.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        lector = PdfReader(str(ruta))
        return [(i + 1, p.extract_text() or "") for i, p in enumerate(lector.pages)]
    return [(None, ruta.read_text(encoding="utf-8", errors="ignore"))]


def _limpiar(texto: str) -> str:
    texto = texto.replace("­", "")  # guiones de corte suave
    texto = re.sub(r"-\n(\w)", r"\1", texto)  # palabras partidas por guion al final de línea
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def trocear(texto: str, tam: int = config.TAM_FRAGMENTO, solape: int = config.SOLAPE_FRAGMENTO) -> list[str]:
    """Trocea por párrafos intentando no superar `tam` caracteres, con solape entre trozos."""
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    trozos, actual = [], ""
    for p in parrafos:
        while len(p) > tam:  # párrafo gigante: se corta a la fuerza
            if actual:
                trozos.append(actual)
                actual = ""
            trozos.append(p[:tam])
            p = p[tam - solape:]
        if len(actual) + len(p) + 1 <= tam:
            actual = f"{actual}\n{p}".strip()
        else:
            if actual:
                trozos.append(actual)
            cola = actual[-solape:] if actual and solape else ""
            actual = f"{cola}\n{p}".strip()
    if actual:
        trozos.append(actual)
    return [t for t in trozos if len(t) > 40]


def cargar_fragmentos(directorio: Path = config.DIR_DOCUMENTOS) -> list[Fragmento]:
    fragmentos: list[Fragmento] = []
    for ruta in sorted(directorio.rglob("*")):
        if (ruta.suffix.lower() not in EXTENSIONES or ruta.name.startswith(".")
                or ruta.stem.upper() == "LEEME"):
            continue
        try:
            paginas = _leer_paginas(ruta)
        except Exception as e:  # un PDF roto no debe tumbar la ingesta entera
            log.warning("No se pudo leer %s: %s", ruta.name, e)
            continue
        nombre = str(ruta.relative_to(directorio))
        # Cada fragmento lleva delante el título del documento: así un trozo del medio
        # ("the droplet extinguished at...") sigue sabiendo de qué experimento es.
        primera = next((l for _, t in paginas for l in t.splitlines() if l.strip()), "")
        titulo = primera.lstrip("# ").strip() if primera.startswith("#") else ruta.stem
        for num_pag, texto in paginas:
            for trozo in trocear(_limpiar(texto)):
                if not trozo.startswith(primera.strip()):
                    trozo = f"[{titulo}]\n{trozo}"
                fragmentos.append(Fragmento(len(fragmentos), nombre, num_pag, trozo))
        log.info("%s: %d fragmentos acumulados", nombre, len(fragmentos))
    return fragmentos


# ----------------------------------------------------------------------------- embeddings

def _normalizar(m: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(normas == 0, 1, normas)


_cliente_embeddings = None


def _cliente():
    """Un único cliente reutilizado: evita abrir una conexión nueva con Google en cada búsqueda."""
    global _cliente_embeddings
    if _cliente_embeddings is None:
        from google import genai

        _cliente_embeddings = genai.Client(api_key=config.GEMINI_API_KEY)
    return _cliente_embeddings


def embeber(textos: list[str], tipo: str, cliente=None, lote: int = 50, reintentos: int = 6) -> np.ndarray:
    """tipo: 'RETRIEVAL_DOCUMENT' para indexar, 'RETRIEVAL_QUERY' para preguntas.
    reintentos: cuántas veces esperar y repetir si Google responde 429 (0 = fallar al momento)."""
    from google.genai import types

    cliente = cliente or _cliente()
    vectores: list[list[float]] = []
    for i in range(0, len(textos), lote):
        bloque = textos[i:i + lote]
        for intento in range(reintentos + 1):
            try:
                r = cliente.models.embed_content(
                    model=config.MODELO_EMBEDDINGS,
                    contents=bloque,
                    config=types.EmbedContentConfig(
                        task_type=tipo, output_dimensionality=config.DIMENSION_EMBEDDINGS
                    ),
                )
                vectores.extend(e.values for e in r.embeddings)
                break
            except Exception as e:
                # 429 = límite del plan gratuito: esperar y reintentar
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and intento < reintentos:
                    espera = 2 ** intento * 5
                    log.warning("Límite de cuota alcanzado, espero %ds...", espera)
                    time.sleep(espera)
                else:
                    raise
        else:
            raise RuntimeError("Se agotaron los reintentos generando embeddings")
    return _normalizar(np.array(vectores, dtype=np.float32))


@lru_cache(maxsize=256)
def _embeber_consulta(consulta: str) -> np.ndarray:
    # En plena conversación no se espera nunca: si Google falla, se usa BM25 al momento
    return embeber([consulta], "RETRIEVAL_QUERY", reintentos=0)[0]


# ----------------------------------------------------------------------------- búsqueda por palabras (BM25)

def _tokens(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", texto) if len(t) > 1]


class BM25:
    def __init__(self, documentos: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(_tokens(d)) for d in documentos]
        self.longitudes = [sum(d.values()) for d in self.docs]
        self.media = (sum(self.longitudes) / len(self.docs)) if self.docs else 0
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def puntuar(self, consulta: str) -> np.ndarray:
        q = _tokens(consulta)
        puntos = np.zeros(len(self.docs), dtype=np.float32)
        for i, (d, lon) in enumerate(zip(self.docs, self.longitudes)):
            for t in q:
                if t in d:
                    f = d[t]
                    puntos[i] += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * lon / (self.media or 1))
                    )
        return puntos


# ----------------------------------------------------------------------------- índice

class Indice:
    def __init__(self, fragmentos: list[Fragmento], vectores: np.ndarray | None):
        self.fragmentos = fragmentos
        self.vectores = vectores
        self.bm25 = BM25([f.texto for f in fragmentos])

    # --- persistencia
    def guardar(self, directorio: Path = config.DIR_INDICE) -> None:
        directorio.mkdir(parents=True, exist_ok=True)
        (directorio / "fragmentos.json").write_text(
            json.dumps([asdict(f) for f in self.fragmentos], ensure_ascii=False), encoding="utf-8"
        )
        meta = {"modelo": config.MODELO_EMBEDDINGS, "dimension": config.DIMENSION_EMBEDDINGS}
        (directorio / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        if self.vectores is not None:
            np.save(directorio / "embeddings.npy", self.vectores)

    @classmethod
    def cargar(cls, directorio: Path = config.DIR_INDICE) -> "Indice":
        archivo = directorio / "fragmentos.json"
        if not archivo.exists():
            log.warning("No hay índice en %s. Ejecuta: python ingestar.py", directorio)
            return cls([], None)
        fragmentos = [Fragmento(**d) for d in json.loads(archivo.read_text(encoding="utf-8"))]
        ruta_vec = directorio / "embeddings.npy"
        vectores = np.load(ruta_vec) if ruta_vec.exists() else None
        if vectores is not None and len(vectores) != len(fragmentos):
            log.warning("El índice de embeddings no cuadra con los fragmentos; uso solo BM25")
            vectores = None
        ruta_meta = directorio / "meta.json"
        if vectores is not None and ruta_meta.exists():
            meta = json.loads(ruta_meta.read_text(encoding="utf-8"))
            if (meta.get("modelo"), meta.get("dimension")) != (config.MODELO_EMBEDDINGS, config.DIMENSION_EMBEDDINGS):
                log.warning("El índice se creó con %s/%s y ahora se usa %s/%s: vuelve a ejecutar ingestar.py. "
                            "Mientras tanto, solo búsqueda por palabras.", meta.get("modelo"), meta.get("dimension"),
                            config.MODELO_EMBEDDINGS, config.DIMENSION_EMBEDDINGS)
                vectores = None
        return cls(fragmentos, vectores)

    # --- búsqueda
    def buscar(self, consulta: str, k: int = config.MAX_FRAGMENTOS) -> list[dict]:
        if not self.fragmentos:
            return []
        lexico = self.bm25.puntuar(consulta)
        semantico = None
        if self.vectores is not None and config.GEMINI_API_KEY:
            try:
                q = _embeber_consulta(consulta.strip().lower())
                semantico = self.vectores @ q
            except Exception as e:
                log.warning("Fallo en embeddings de la consulta (%s); uso solo BM25", e)

        if semantico is not None:
            # Fusión por rango recíproco: combina búsqueda semántica y por palabras clave
            puntos = np.zeros(len(self.fragmentos), dtype=np.float32)
            for orden in (np.argsort(-semantico), np.argsort(-lexico)):
                for rango, i in enumerate(orden[:50]):
                    puntos[i] += 1.0 / (60 + rango)
        else:
            puntos = lexico

        mejores = [i for i in np.argsort(-puntos)[:k] if puntos[i] > 0]
        return [
            {
                "fuente": self.fragmentos[i].fuente,
                "pagina": self.fragmentos[i].pagina,
                "texto": self.fragmentos[i].texto,
            }
            for i in mejores
        ]


def construir_indice(con_embeddings: bool = True) -> Indice:
    fragmentos = cargar_fragmentos()
    vectores = None
    if fragmentos and con_embeddings:
        if not config.GEMINI_API_KEY:
            log.warning("Sin GEMINI_API_KEY: el índice se crea solo para búsqueda por palabras")
        else:
            vectores = embeber([f.texto for f in fragmentos], "RETRIEVAL_DOCUMENT")
    return Indice(fragmentos, vectores)
