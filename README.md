# Artemis SI — Dashboard de seguridad contra incendios

Dashboard que recupera evidencia de documentos PSI (BASS, Saffire, FLEX, ACME…) y la pasa a Claude (`claude-opus-5-5`) con el prompt de sistema "Artemis SI" para producir un informe en 4 secciones.

## Arranque

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```bash
.venv/Scripts/python -m uvicorn backend.app:app --port 8000
```

Abre http://localhost:8000.

## Cómo funciona

| Pieza | Archivo |
|---|---|
| Prompt de sistema (estático, cacheado) | `backend/prompt.py` |
| Recuperación BM25 + regla de gravedad parcial | `backend/retrieval.py` |
| API (`/api/retrieve` gratis, `/api/analyze` llama al modelo en streaming) | `backend/app.py` |
| Interfaz | `frontend/` |
| Corpus | `data/psi/` |

- **Gravedad parcial** (0.01–0.99 g): la recuperación añade siempre ≥2 fragmentos etiquetados `0g` y ≥2 `1g`, para que el Motor de Extrapolación tenga los dos límites.
- **Citas**: cada fragmento tiene un ID (`BASS-02`); el modelo debe citarlo y la interfaz enlaza la cita con la fuente.
- **Refusals**: se usa el fallback de servidor (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`).
- Modelo configurable con la variable `ARTEMIS_MODEL`.

## Corpus

Los archivos actuales de `data/psi/` son resúmenes **SEED no oficiales** (marcados `source: SEED`) para que el sistema funcione desde el principio. Sustitúyelos por el texto real de los conjuntos de datos PSI:

- `.md` / `.txt` con front matter, o `.pdf` (sin front matter: el ID sale del nombre del archivo y la gravedad queda sin etiquetar; añade un `.md` si necesitas etiquetarla).

```
---
id: BASS
title: Burning and Suppression of Solids
gravity: 0g          # 0g | 1g | 0g,1g
source: PSI          # PSI | SEED
---
## Sección
texto…
```

Tras añadir archivos: `POST /api/reload` o reinicia el servidor.
