# FLAMA — Flame in Freefall

NASA Space Apps Challenge 2026. Fire-safety dashboard for crewed spacecraft built only on the NASA PSI
(Physical Sciences Informatics) data in `base_de_datos/` (read-only).

- Public site: https://flama-nasa.streamlit.app (Streamlit Community Cloud, redeploys on every push to `main`)
- AI voice/text server: `ia_web/servidor_web.py` (wraps `voz/`), deployed on Render (`render.yaml`)

## Run locally

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

```bash
.venv/Scripts/python -m streamlit run app.py
```

The web uses the public AI server by default. To use one on this machine, start it and set `FLAMA_IA_URL=local`:

```bash
voz/.venv/Scripts/python -m uvicorn ia_web.servidor_web:app --port 8001
```

The Gemini key goes in `voz/.env` (`GEMINI_API_KEY=...`, never committed). Without any AI server the chat
answers from the database files (verbatim quotes and table figures, no generative AI).

## Map

| Part | Files |
|---|---|
| Entry point | `app.py` |
| Whole interface (one HTML document) | `ui_components.py` |
| PSI index and Flammy knowledge (built into `knowledge_cache/`) | `psi_database.py` |
| Flammy, the advisor (runs in the browser) | `flammy_agent/flammy_engine.js` (Python reference: `flammy_agent/`) |
| Text library of the database (`static/library/`) | `biblioteca.py`, `library/` |
| Safety Mechanisms bubble | `safety_research.py`, `safety/` |
| 3D cabin simulator | `sim3d_data.py`, `sim3d/`, `static/nave.glb` |
| Theory Lab | `theories/`, `static/theories/`, `ia_web/teorias.py` |
| AI chat (web side) | `ia_web/web/` |
| AI server | `ia_web/servidor_web.py`, `voz/` |
| Fonts | `flama_type.py`, `static/fonts/` |

## Tests

```bash
.venv/Scripts/python tests_safety.py
```

```bash
voz/.venv/Scripts/python -m ia_web.test_citas
```
