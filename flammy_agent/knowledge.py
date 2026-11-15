"""Flammy knowledge base: completely dynamic, reading from D:\\nasa_dashboard\\base_de_datos.

Zero hardcoded mock data. All rules, materials, responses, and sources are fetched locally.
"""
import json
from pathlib import Path

# Ruta estricta a la carpeta de tu base de datos real
DB_DIR = Path(__file__).resolve().parent.parent / "base_de_datos"        # read-only
CACHE_DIR = Path(__file__).resolve().parent.parent / "knowledge_cache"   # derived by psi_database.py

def _load_db(filename: str, default: any) -> any:
    """Load a derived knowledge file (knowledge_cache/ first, base_de_datos/ as read-only fallback)."""
    path = CACHE_DIR / filename if (CACHE_DIR / filename).exists() else DB_DIR / filename
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error cargando {filename} de la BD: {e}")
    return default

DISCLAIMER = "Informational support based on the official NASA PSI database."

# 100% DATOS REALES DE TU CARPETA (se eliminó la información inventada)
SOURCES = _load_db("sources.json", {})
MATERIALS = _load_db("materials.json", {})
FIRE_RESPONSE = _load_db("fire_response.json", {})
CLASS_NOTES = _load_db("class_notes.json", {})
RULES = _load_db("rules.json", [])
EXPERIMENTS = _load_db("experiments.json", {})

FALLBACK = {
    "title": "No specific hazard detected in PSI Database",
    "short": "check detectors, the O2 analyzer and CO/CO2 monitors.",
    "why": ["Not enough data matching the exact records in the PSI Database."],
    "actions": ["Provide material, % O2 and ventilation type matching the database."],
    "sources": []
}