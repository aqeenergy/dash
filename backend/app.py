"""Artemis SI — servidor del dashboard.

Ejecutar:  .venv/Scripts/python -m uvicorn backend.app:app --port 8000
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .prompt import SYSTEM_PROMPT, build_user_message
from .retrieval import BM25Index, format_context, gravity_regime, load_corpus, retrieve

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "psi"
FRONTEND = ROOT / "frontend"
MODEL = os.environ.get("ARTEMIS_MODEL", "claude-opus-5-5")
PSI_TO_KPA = 6.894757

app = FastAPI(title="Artemis SI")
_index: BM25Index | None = None


def index() -> BM25Index:
    global _index
    if _index is None:
        _index = BM25Index(load_corpus(DATA_DIR))
    return _index


class Params(BaseModel):
    gravity_g: float = Field(ge=0, le=1.5)
    pressure_psi: float = Field(gt=0, le=20)
    o2_pct: float = Field(ge=0, le=100)
    material: str = ""
    airflow_cm_s: float = Field(default=0, ge=0, le=500)
    question: str = ""


def describe(p: Params) -> str:
    p_kpa = p.pressure_psi * PSI_TO_KPA
    ppo2 = p_kpa * p.o2_pct / 100
    regime = {"0g": "Microgravedad", "1g": "Gravedad terrestre", "partial": "Gravedad parcial"}[gravity_regime(p.gravity_g)]
    lines = [
        f"- Gravedad: {p.gravity_g:.2f} g ({regime})",
        f"- Presión total: {p_kpa:.1f} kPa ({p.pressure_psi:.1f} psi)",
        f"- Concentración de O2: {p.o2_pct:.1f} % vol (presión parcial de O2 ≈ {ppo2:.1f} kPa)",
        f"- Flujo de aire inducido: {p.airflow_cm_s:.0f} cm/s",
        f"- Material / combustible: {p.material or 'no especificado'}",
    ]
    if p.question.strip():
        lines.append(f"- Pregunta: {p.question.strip()}")
    return "\n".join(lines)


@app.get("/api/status")
def status():
    chunks = index().chunks
    return {
        "model": MODEL,
        "chunks": len(chunks),
        "documents": sorted({c.doc_id for c in chunks}),
        "seed_only": all(c.source == "SEED" for c in chunks),
    }


@app.post("/api/reload")
def reload():
    global _index
    _index = None
    return status()


@app.post("/api/retrieve")
def api_retrieve(p: Params):
    return {"hits": retrieve(index(), p.model_dump()), "query": describe(p)}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/analyze")
def analyze(p: Params):
    hits = retrieve(index(), p.model_dump())
    user_msg = build_user_message(format_context(hits), describe(p))

    def gen():
        yield _sse("sources", hits)
        try:
            client = anthropic.Anthropic()
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for text in stream.text_stream:
                    yield _sse("text", text)
                final = stream.get_final_message()
            if final.stop_reason == "refusal":
                yield _sse("error", "El modelo rechazó la solicitud (stop_reason=refusal).")
            elif final.stop_reason == "max_tokens":
                yield _sse("error", "Respuesta truncada por max_tokens.")
            u = final.usage
            yield _sse("done", {
                "model": final.model,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            })
        except anthropic.AuthenticationError:
            yield _sse("error", "Credenciales no válidas o ausentes. Define ANTHROPIC_API_KEY antes de arrancar el servidor.")
        except anthropic.RateLimitError:
            yield _sse("error", "Límite de peticiones alcanzado (429). Reintenta en unos segundos.")
        except anthropic.APIStatusError as e:
            yield _sse("error", f"Error de la API ({e.status_code}): {e.message}")
        except anthropic.APIConnectionError:
            yield _sse("error", "No se pudo conectar con la API de Anthropic.")
        except Exception as e:
            if "authentication method" in str(e):
                yield _sse("error", "No hay credenciales de Anthropic. Define ANTHROPIC_API_KEY y reinicia el servidor.")
            else:
                yield _sse("error", f"{type(e).__name__}: {e}")

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
def home():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
