"""ui_components.py — FLAMA // Linear/Apple-Grade Restrained Motion, Real DB & Flammy Sentinel.

Animation Architecture (60 FPS Compositor-Only):
  1. Bubble Hover (Formal & Restrained): Static at rest. On hover: -4px elevation,
     1.025 scale, deep diffuse shadow, and a 1px outer ring fade-in over 280ms
     using cubic-bezier(0.22, 1, 0.36, 1) with zero bounce.
  2. Click Microinteractions: Subtle 0.97 scale press compression, low-opacity
     radial ripple from click coordinates, sober focus/disabled states, and subtle
     icon shifts.
  3. FLIP Bubble Zoom Transition (580ms): Continuous expansion from the clicked
     bubble's exact screen coordinates to full viewport with background blur.
  4. Real Database Sync & Offline Flammy Sentinel: Reads dynamically from
     D:\\nasa_dashboard\\base_de_datos\\ and runs Flammy on local port 8765.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# PSI Knowledge Bootstrap: build the derived JSONs (experiments, materials,
# rules, sources, fire_response, class_notes, mission_presets) from the RAW
# PSI metadata in base_de_datos/ BEFORE flammy_agent.knowledge reads them —
# knowledge.py loads those files at import time.
# ---------------------------------------------------------------------------
try:
    import psi_database

    if psi_database.ensure_knowledge().get("built"):
        # a running server (e.g. Streamlit Cloud after a git push) may hold the old knowledge in memory
        import importlib, sys as _sys
        for _m in ("flammy_agent.knowledge", "flammy_agent.engine", "flammy_agent.agent", "flammy_agent"):
            if _m in _sys.modules:
                importlib.reload(_sys.modules[_m])
    _PSI_CARDS: list[dict[str, Any]] = psi_database.investigation_cards()
except Exception:
    logging.getLogger("flama").exception("PSI knowledge bootstrap failed")
    _PSI_CARDS = []

# ---------------------------------------------------------------------------
# Database Loader (No hardcoded mock data allowed)
# ---------------------------------------------------------------------------
DB_DIR = Path(__file__).resolve().parent / "base_de_datos"        # READ-ONLY
CACHE_DIR = Path(__file__).resolve().parent / "knowledge_cache"   # derived by psi_database.py


def _load_db_json(filename: str, default: Any) -> Any:
    path = CACHE_DIR / filename if (CACHE_DIR / filename).exists() else DB_DIR / filename
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


# Load Experiments dynamically for Bubble 1. Pills = curated flight-program
# observers (fm2, luci, ...); the PSI-XX investigations get the ranked card
# browser below instead of one pill each.
_db_experiments = _load_db_json("experiments.json", {})
_curated_experiments = {
    e_id: e_data for e_id, e_data in (_db_experiments or {}).items()
    if isinstance(_db_experiments, dict) and not str(e_id).lower().startswith("psi-")
}
if _curated_experiments:
    EXP_BUTTONS_HTML = "".join(
        f'<button class="switch-bubble-btn press-able exp-observe-btn" data-exp="{html.escape(str(e_id))}">'
        f'{html.escape(str(e_data.get("name", e_id)).split(" - ")[0] if isinstance(e_data, dict) else str(e_id))}</button>'
        for e_id, e_data in _curated_experiments.items()
    )
else:
    EXP_BUTTONS_HTML = (
        '<div style="color:var(--space-500);font-size:12px;width:100%;text-align:center;margin-top:10px;">'
        "AWAITING EXPERIMENTS FROM PSI DATABASE...</div>"
    )

# JSON payload for the Bubble-1 investigation browser (HTML-escaped text fields).
_PSI_DB_JSON = json.dumps(
    [
        {**c, "name": html.escape(str(c.get("name", ""))), "acr": html.escape(str(c.get("acr", ""))),
         "blurb": html.escape(str(c.get("blurb", ""))), "hardware": html.escape(str(c.get("hardware", "")))}
        for c in _PSI_CARDS
    ],
    ensure_ascii=False,
).replace("</", "<\\/")

_PSI_BROWSER_HTML = """
<style>
  .psi-browser { width: 100%; max-width: 980px; margin-top: 26px; text-align: left; }
  .psi-toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 10px; }
  .psi-toolbar input { flex: 1 1 260px; background: #101216; border: 1px solid #1A1D23; color: #F4F3EF;
      border-radius: 8px; padding: 10px 14px; font: 400 14px var(--font-ui); letter-spacing: 0; outline: none; }
  .psi-toolbar input::placeholder { color: #6B717C; }
  .psi-toolbar input:focus { border-color: #2F63B0; }
  .psi-toolbar select { background: #101216; border: 1px solid #1A1D23; color: #BCD6EE; border-radius: 8px;
      padding: 10px 12px; font: 500 13px var(--font-ui); }
  .psi-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .psi-chip { background: transparent; border: 1px solid #1A1D23; color: #D9D8D3; border-radius: 999px;
      padding: 6px 13px; font: 500 12px var(--font-ui); letter-spacing: .02em; cursor: pointer;
      transition: border-color .2s, color .2s; }
  .psi-chip:hover { border-color: #6FA3D8; color: #E8F1FA; }
  .psi-chip.active { border-color: #6FA3D8; color: #E8F1FA; background: rgba(18, 48, 110, 0.45); }
  .psi-count { font: 500 12px var(--font-ui); color: #8A909A; letter-spacing: .01em; margin: 8px 2px 12px; }
  .psi-card-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr)); gap: 12px; }
  .psi-card { background: #101216; border: 1px solid #1A1D23; border-radius: 12px; padding: 14px 16px;
      display: flex; flex-direction: column; gap: 7px; transition: border-color .25s, transform .25s; }
  .psi-card:hover { border-color: #2F63B0; transform: translateY(-2px); }
  .psi-card-top { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .psi-acc { font: 600 12.5px var(--font-data); color: #6FA3D8; letter-spacing: 0; }
  .psi-badge { font: 600 10.5px var(--font-ui); letter-spacing: .04em; color: #D9D8D3;
      border: 1px solid #1A1D23; border-radius: 4px; padding: 2px 6px; }
  .psi-badge.psi-rel { color: #FFC27A; border-color: #8C2A08; background: rgba(140, 42, 8, 0.28); }
  .psi-fuel-solid { color: #FF8A2A; border-color: #8C2A08; }
  .psi-fuel-droplet { color: #BCD6EE; border-color: #2F63B0; }
  .psi-fuel-gaseous { color: #6FA3D8; border-color: #2F63B0; }
  .psi-fuel-detection { color: #FFC27A; border-color: #8C2A08; }
  .psi-fuel-analysis { color: #D9D8D3; }
  .psi-name { font: 600 15px var(--font-ui); color: #F4F3EF; line-height: 1.35; letter-spacing: -0.01em; text-wrap: balance; }
  .psi-name b { color: #E8F1FA; font-weight: 700; }
  .psi-blurb { font: 400 13.5px var(--font-ui); color: #C4C3BE; line-height: 1.55; text-wrap: pretty; }
  .psi-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; font: 400 11.5px var(--font-data);
      color: #8A909A; letter-spacing: 0; margin-top: auto; }
  .psi-meta a { color: #6FA3D8; text-decoration: none; }
  .psi-meta a:hover { text-decoration: underline; }
  .psi-actions { margin-top: 4px; }
  .psi-lib { all: unset; cursor: pointer; color: #6FA3D8; font: 500 11.5px var(--font-ui); }
  .psi-lib:hover { text-decoration: underline; text-underline-offset: 3px; }
  .psi-lib:focus-visible { outline: 2px solid #6FA3D8; outline-offset: 2px; }
</style>
<div class="psi-browser">
  <div class="psi-toolbar">
    <input id="psi-search" placeholder="SEARCH PSI ARCHIVE — TITLE, HARDWARE, FUEL, DOI..." autocomplete="off"/>
    <select id="psi-sort">
      <option value="relevance">SORT: RELEVANCE TO LIVE SIM</option>
      <option value="accession">SORT: ACCESSION</option>
      <option value="tables">SORT: DATA VOLUME</option>
      <option value="library">VIEW: DATABASE LIBRARY · ALL FILES AS TEXT</option>
    </select>
  </div>
  <div class="psi-chips" id="psi-chips">
    <button class="psi-chip active" data-fuel="all">ALL</button>
    <button class="psi-chip" data-fuel="solid">SOLID FUELS</button>
    <button class="psi-chip" data-fuel="droplet">DROPLETS</button>
    <button class="psi-chip" data-fuel="gaseous">GASEOUS</button>
    <button class="psi-chip" data-fuel="detection">DETECTION</button>
    <button class="psi-chip" data-fuel="analysis">ANALYSIS</button>
  </div>
  <div id="psi-count" class="psi-count"></div>
  <div id="psi-card-list" class="psi-card-list"></div>
  <div id="psi-library" class="lib" hidden>
    <nav id="lib-list" class="lib-list" aria-label="Database files"></nav>
    <section id="lib-view" class="lib-view" aria-live="polite"></section>
  </div>
</div>
"""


def render_live_mission_control() -> None:
    import flama_type

    FLAMA_FONT_FACES = flama_type.font_face_css()
    from flammy_agent import knowledge as _fk

    _flammy_k = json.dumps({"materials": _fk.MATERIALS, "rules": _fk.RULES, "fire_response": _fk.FIRE_RESPONSE,
                            "class_notes": _fk.CLASS_NOTES, "sources": _fk.SOURCES, "experiments": _fk.EXPERIMENTS,
                            "fallback": _fk.FALLBACK, "disclaimer": _fk.DISCLAIMER}, ensure_ascii=False).replace("</", "<" + "\\" + "/")
    _engine_js = (Path(__file__).resolve().parent / "flammy_agent" / "flammy_engine.js").read_text(encoding="utf-8")
    FLAMMY_ENGINE_JS = ("<script>window.FLAMMY_KNOWLEDGE = " + _flammy_k + ";</script><script>"
                        + _engine_js.replace("</", "<" + "\\" + "/") + "</script>")
    _web = Path(__file__).resolve().parent / "ia_web" / "web"
    IA_CHAT_HTML = (_web / "chat.html").read_text(encoding="utf-8")
    IA_CHAT_CSS = (_web / "chat.css").read_text(encoding="utf-8")
    import os as _os
    try:
        import biblioteca

        biblioteca.build()
    except Exception:
        logging.getLogger("flama").exception("Text library could not be built")
    try:
        import safety_research

        safety_research.build()
    except Exception:
        logging.getLogger("flama").exception("Safety research data could not be built")
    _saf = Path(__file__).resolve().parent / "safety"
    SAFETY_HTML = (_saf / "safety.html").read_text(encoding="utf-8")
    SAFETY_CSS = (_saf / "safety.css").read_text(encoding="utf-8")
    SAFETY_JS = "<script>" + (_saf / "safety.js").read_text(encoding="utf-8").replace("</", "<" + "\\" + "/") + "</script>"
    _th = Path(__file__).resolve().parent / "theories"
    THEORY_HTML = (_th / "theories.html").read_text(encoding="utf-8")
    THEORY_CSS = (_th / "theories.css").read_text(encoding="utf-8")
    THEORY_JS = "<script>" + (_th / "theories.js").read_text(encoding="utf-8").replace("</", "<" + "\\" + "/") + "</script>"
    _lib = Path(__file__).resolve().parent / "library"
    LIB_CSS = (_lib / "library.css").read_text(encoding="utf-8")
    LIB_JS = "<script>" + (_lib / "library.js").read_text(encoding="utf-8").replace("</", "<" + "\\" + "/") + "</script>"
    _ia_url = _os.getenv("FLAMA_IA_URL", "")
    try:  # Streamlit Community Cloud secrets
        _ia_url = _ia_url or str(st.secrets.get("FLAMA_IA_URL", ""))
    except Exception:
        pass
    # Public AI server (Render). An env var or Streamlit secret FLAMA_IA_URL overrides it;
    # FLAMA_IA_URL="local" uses the server on this machine (port FLAMA_IA_PUERTO).
    _ia_url = _ia_url or "https://flama-ia.onrender.com"
    if _ia_url.strip().lower() == "local":
        _ia_url = ""
    _cfg = json.dumps({"puerto": int(_os.getenv("FLAMA_IA_PUERTO", "8001")), "nombre": "Llama", "base": _ia_url.strip()})
    _chat_js = (_web / "chat.js").read_text(encoding="utf-8").replace("</", "<" + "\\" + "/")
    IA_CHAT_JS = "<script>window.FLAMA_IA = " + _cfg + ";</script>" + "<script>" + _chat_js + "</script>"
    try:
        import sim3d_data

        SIM3D_HTML = sim3d_data.section_html()
    except Exception:
        logging.getLogger("flama").exception("3D simulator could not be built")
        SIM3D_HTML = ('<div class="empty-module-box"><div class="empty-module-code">'
                      "3D SIMULATOR UNAVAILABLE — SEE SERVER LOG</div></div>")


    flama_top_left_logo_svg = """
      <svg class="flama-logo-sphere" viewBox="0 0 48 48" aria-hidden="true">
        <defs>
          <radialGradient id="flamaLogoHalo" cx="50%" cy="50%" r="50%">
            <stop offset="42%" stop-color="#0B3BFF" stop-opacity="0.9"/>
            <stop offset="64%" stop-color="#0A2FD0" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#020A3A" stop-opacity="0"/>
          </radialGradient>
          <radialGradient id="flamaLogoBody" cx="50%" cy="54%" r="52%">
            <stop offset="0%"  stop-color="#0A2FCF"/>
            <stop offset="58%" stop-color="#0B36E4"/>
            <stop offset="82%" stop-color="#1048F5"/>
            <stop offset="93%" stop-color="#2E7BFF"/>
            <stop offset="100%" stop-color="#4C9BFF" stop-opacity="0.7"/>
          </radialGradient>
          <filter id="flamaLogoSoft" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="0.45"/></filter>
        </defs>
        <circle class="flama-logo-halo" cx="24" cy="24" r="23.5" fill="url(#flamaLogoHalo)"/>
        <circle class="flama-logo-core" cx="24" cy="24" r="13.6" fill="url(#flamaLogoBody)" filter="url(#flamaLogoSoft)"/>
      </svg>
    """

    # served as a static file: cached by the browser (it used to be base64 twice inside the page: 4.4 MB)
    video_data_uri = "app/static/flama_cover.mp4" if (Path(__file__).resolve().parent / "static" / "flama_cover.mp4").exists() else ""

    html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
{FLAMA_FONT_FACES}

  /* =========================================================================
     0. CSS VARIABLES FOR DURATIONS, EASINGS & PALETTE
     ========================================================================= */
  :root {{
    /* Type rule (flama_type.py): every UPPERCASE letter renders in Roboto Condensed,
       every lowercase letter in Chalet (Jost stand-in until Chalet is installed). */
    --font-ui:   "FlamaType", "Segoe UI", system-ui, -apple-system, sans-serif;
    --font-data: "FlamaType", "Segoe UI", system-ui, sans-serif;
    --stretch-display: 116%;
    --stretch-data: 87.5%;
    --space-900: #07080A;
    --space-800: #101216;
    --space-700: #1A1D23;
    --space-500: #3A3F48;
    --paper-50:  #F4F3EF;
    --paper-200: #D9D8D3;
    --glow-100:  #E8F1FA;
    --sky-200:   #BCD6EE;
    --sky-400:   #6FA3D8;
    --sky-600:   #2F63B0;
    --sky-800:   #12306E;
    --sky-950:   #0A1838;
    --flare-200: #FFC27A;
    --flare-400: #FF8A2A;
    --flare-500: #F2600F;
    --flare-800: #8C2A08;

    --dur-press:    110ms;
    --dur-fast:     180ms;
    --dur-hover:    280ms;
    --dur-entrance: 480ms;
    --dur-zoom:     580ms;

    --ease-smooth:  cubic-bezier(0.22, 1, 0.36, 1);
    --ease-in-out:  cubic-bezier(0.65, 0, 0.35, 1);
    --ease-out:     cubic-bezier(0.16, 1, 0.3, 1);
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}

  .tcard-val, .field-val, .phys-pill-val, .psi-acc, .psi-meta {{ font-variant-numeric: tabular-nums slashed-zero; font-stretch: var(--stretch-data); }}
  .orb-title {{ font-stretch: 104%; }}
  .ws-title, .cover-init-btn, .ws-tag, .empty-module-code, .tcard-lbl, .phys-pill-lbl, .eclss-title,
  .switch-bubble-btn, .sim-subtab-btn, .menu-item, .fb-name, .psi-chip {{ font-stretch: var(--stretch-display); }}
  ::selection {{ background: rgba(111, 163, 216, 0.35); color: #F4F3EF; }}

  body {{
    background: #000000;
    color: var(--paper-50);
    font-family: var(--font-ui);
    overflow-x: hidden;
    padding: 0;
    cursor: default;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }}

  #ambient-gradient-backdrop {{
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background:
      radial-gradient(80% 60% at 50% 18%, rgba(18, 48, 110, 0.14) 0%, transparent 70%),
      radial-gradient(60% 50% at 75% 82%, rgba(47, 99, 176, 0.07) 0%, transparent 75%);
    animation: subtleGradientShift 24s ease-in-out infinite alternate;
  }}
  @keyframes subtleGradientShift {{
    0%   {{ opacity: 0.75; transform: scale(1.00); }}
    100% {{ opacity: 1.00; transform: scale(1.06); }}
  }}

  #bubble-zoom-portal {{
    position: fixed;
    top: 0;
    left: 0;
    width: 146px;
    height: 146px;
    border-radius: 50%;
    pointer-events: none;
    z-index: 9998;
    opacity: 0;
    background: radial-gradient(
      circle at 38% 35%,
      rgba(26, 29, 35, 0.92) 0%,
      rgba(16, 18, 22, 0.97) 55%,
      rgba(7, 8, 10, 0.99) 100%
    );
    border: 1px solid rgba(188, 214, 238, 0.42);
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.85);
    will-change: transform, opacity;
  }}

  .zoom-blur-out {{
    filter: blur(8px);
    opacity: 0 !important;
    transform: scale(1.04);
    transition: filter var(--dur-zoom) var(--ease-smooth),
                opacity var(--dur-zoom) var(--ease-smooth),
                transform var(--dur-zoom) var(--ease-smooth);
  }}

  .os-view {{
    display: none;
    position: relative;
    z-index: 5;
  }}
  .os-view.active {{
    display: block;
    animation: viewFade var(--dur-entrance) var(--ease-smooth) forwards;
  }}
  @keyframes viewFade {{
    from {{ opacity: 0; }}
    to   {{ opacity: 1; }}
  }}

  @keyframes interiorFadeUp {{
    0% {{
      opacity: 0;
      transform: translate3d(0, 12px, 0);
    }}
    100% {{
      opacity: 1;
      transform: translate3d(0, 0, 0);
    }}
  }}
  .stagger-in {{
    opacity: 0;
    animation: interiorFadeUp var(--dur-entrance) var(--ease-smooth) forwards;
    animation-delay: calc(var(--stagger-idx, 0) * 55ms + 60ms);
  }}

  .reveal-on-scroll {{
    opacity: 0;
    transform: translate3d(0, 12px, 0);
    transition: opacity var(--dur-entrance) var(--ease-smooth),
                transform var(--dur-entrance) var(--ease-smooth);
  }}
  .reveal-on-scroll.is-visible {{
    opacity: 1;
    transform: translate3d(0, 0, 0);
  }}

  button, .floating-orb, .video-loader-pill, select {{
    position: relative;
    overflow: hidden;
  }}

  button:focus-visible, select:focus-visible, input:focus-visible, .floating-orb:focus-visible {{
    outline: 1.5px solid var(--sky-400) !important;
    outline-offset: 3px !important;
  }}
  button:disabled, select:disabled {{
    opacity: 0.40 !important;
    cursor: not-allowed !important;
    pointer-events: none !important;
  }}

  .press-able {{
    transition: transform var(--dur-hover) var(--ease-smooth),
                background var(--dur-fast) var(--ease-smooth),
                border-color var(--dur-fast) var(--ease-smooth),
                color var(--dur-fast) var(--ease-smooth),
                box-shadow var(--dur-hover) var(--ease-smooth);
  }}
  .press-able:active {{
    transform: scale(0.97) !important;
    transition: transform var(--dur-press) var(--ease-smooth) !important;
  }}

  .anim-icon {{
    transition: transform var(--dur-hover) var(--ease-smooth);
  }}
  button:hover .anim-icon, .flama-logo-home-btn:hover .anim-icon {{
    transform: rotate(8deg) scale(1.04);
  }}
  .switch-bubble-btn:hover {{
    transform: translate3d(-2px, 0, 0);
  }}

  .click-ripple {{
    position: absolute;
    border-radius: 50%;
    pointer-events: none;
    background: radial-gradient(
      circle,
      rgba(244, 243, 239, 0.16) 0%,
      rgba(188, 214, 238, 0.08) 55%,
      transparent 100%
    );
    transform: scale(0);
    animation: discreetRipple 520ms var(--ease-smooth) forwards;
    z-index: 30;
  }}
  @keyframes discreetRipple {{
    0%   {{ transform: scale(0); opacity: 1; }}
    100% {{ transform: scale(3.2); opacity: 0; }}
  }}

  /* =========================================================================
     VIEW 0: DUAL-VIDEO HARDWARE CROSSFADE COVER (Loops from t = 8.0s forever)
     ========================================================================= */
  .cover-stage {{
    position: relative;
    width: 100%;
    min-height: calc(var(--app-vh, 100vh) * 0.92);
    background: #000000;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    padding: 16px 24px 48px 24px;
  }}

  .video-loader-pill {{
    position: absolute;
    top: 14px;
    right: 16px;
    background: rgba(16, 18, 22, 0.65);
    border: 1px solid rgba(58, 63, 72, 0.65);
    border-radius: 999px;
    padding: 5px 12px;
    font-family: var(--font-ui);
    font-size: 11px;
    color: var(--paper-200);
    cursor: pointer;
    z-index: 20;
    opacity: 0.42;
  }}
  .video-loader-pill:hover {{
    opacity: 1.0;
    border-color: var(--sky-400);
  }}

  .cover-video-viewport {{
    position: relative;
    width: 820px;
    max-width: 96vw;
    aspect-ratio: 16 / 9;
    background: #000000;
  }}

  .cover-vid-layer {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
    pointer-events: none;
    transition: opacity 0.50s linear;
  }}

  .cover-init-btn {{
    margin-top: 44px;
    background: rgba(16, 18, 22, 0.88);
    color: var(--paper-50);
    border: 1px solid rgba(111, 163, 216, 0.42);
    border-radius: 999px;
    padding: 13px 48px;
    font-family: var(--font-ui);
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    cursor: pointer;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.65);
    z-index: 10;
  }}
  .cover-init-btn:hover {{
    background: var(--sky-800);
    border-color: var(--sky-200);
    color: var(--paper-50);
    transform: translate3d(0, -2px, 0);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.8), 0 0 20px rgba(111, 163, 216, 0.25);
  }}

  /* =========================================================================
     TOP-LEFT FLAMA LOGO (BLUISH MICROGRAVITY FLAME SPHERE) + MENU
     ========================================================================= */
  .top-nav-row {{
    display: none;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px 0 20px;
    background: transparent;
    position: relative;
    z-index: 100;
  }}
  .top-nav-row.visible {{
    display: flex;
  }}
  .top-left-brand-group {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .flama-logo-home-btn {{
    width: 46px;
    height: 46px;
    border-radius: 50%;
    padding: 0;
    background: transparent;
    border: 0 !important;
    box-shadow: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }}
  .flama-logo-home-btn:focus-visible {{ outline: 2px solid var(--sky-400); outline-offset: 2px; }}
  .flama-logo-sphere {{ width: 46px; height: 46px; display: block; overflow: visible; }}
  .flama-logo-halo {{ transform-box: fill-box; transform-origin: center; animation: flamaLogoGlow 2.8s ease-in-out infinite; }}
  .flama-logo-core {{ transform-box: fill-box; transform-origin: 50% 60%; animation: flamaLogoFlicker 1.9s ease-in-out infinite;
                       transition: transform var(--dur-hover) var(--ease-smooth); }}
  .flama-logo-home-btn:hover .flama-logo-core {{ transform: scale(1.08); }}
  @keyframes flamaLogoGlow    {{ 0%,100% {{ transform: scale(1); opacity: .75; }} 50% {{ transform: scale(1.07); opacity: 1; }} }}
  @keyframes flamaLogoFlicker {{ 0%,100% {{ transform: scale(1,1); }} 30% {{ transform: scale(1.03,.97); }} 65% {{ transform: scale(.98,1.03); }} }}
  @media (prefers-reduced-motion: reduce) {{ .flama-logo-halo, .flama-logo-core {{ animation: none; }} }}

  .hamburger-btn {{
    width: 38px;
    height: 36px;
    background: rgba(16, 18, 22, 0.78);
    border: 1px solid var(--space-700);
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 4.5px;
    cursor: pointer;
  }}
  .hamburger-btn:hover {{
    border-color: rgba(111, 163, 216, 0.45);
    background: var(--space-800);
  }}
  .hamburger-line {{
    width: 16px;
    height: 1.8px;
    background: var(--paper-200);
    border-radius: 2px;
    transition: transform var(--dur-hover) var(--ease-smooth);
  }}

  .hamburger-dropdown {{
    display: none;
    position: absolute;
    top: 62px;
    left: 20px;
    width: 280px;
    background: var(--space-800);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    box-shadow: 0 18px 42px rgba(0, 0, 0, 0.82);
    z-index: 9999;
    padding: 6px;
  }}
  .hamburger-dropdown.open {{
    display: block;
    animation: menuSlide var(--dur-fast) var(--ease-smooth) forwards;
  }}
  @keyframes menuSlide {{
    from {{ opacity: 0; transform: translate3d(0, -6px, 0); }}
    to   {{ opacity: 1; transform: translate3d(0, 0, 0); }}
  }}
  .menu-item {{
    width: 100%;
    text-align: left;
    background: transparent;
    color: var(--paper-200);
    border: none;
    border-radius: 6px;
    padding: 9px 12px;
    font-family: var(--font-ui);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: background var(--dur-fast) var(--ease-smooth),
                color var(--dur-fast) var(--ease-smooth);
  }}
  .menu-item:hover {{
    background: var(--space-700);
    color: var(--paper-50);
  }}
  .menu-item.active {{
    background: var(--sky-600);
    color: var(--paper-50);
  }}

  /* =========================================================================
     VIEW 1: COMMAND HUB (Cosmic Trail + Command Bar + 4 Formal Static Orbs)
     ========================================================================= */
  .hub-stage {{
    position: relative;
    min-height: 84vh;
    background: transparent;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 16px 36px 16px;
    overflow: hidden;
  }}

  .cosmic-comet-stage {{
    width: 100%;
    max-width: 1320px;
    height: 175px;
    position: relative;
    margin: 0 auto 18px auto;
    pointer-events: none;
  }}

  .fine-stream-blue {{
    stroke-dasharray: 420 980;
    animation: fineFlow1 12s linear infinite;
  }}
  .fine-stream-orange {{
    stroke-dasharray: 340 1060;
    animation: fineFlow2 15s linear infinite;
  }}
  .fine-stream-white {{
    stroke-dasharray: 220 1180;
    animation: fineFlow1 12s linear 0.15s infinite;
  }}
  .fine-Sec-filament {{
    stroke-dasharray: 280 1120;
    animation: fineFlowRev 18s linear infinite;
  }}
  .nebula-whisper {{
    animation: whisperPulse 9s ease-in-out infinite;
  }}
  .dust-twinkle-a {{
    animation: dustFloat 8s ease-in-out infinite;
  }}
  .dust-twinkle-b {{
    animation: dustFloat 10s ease-in-out 2.5s infinite;
  }}
  @keyframes fineFlow1 {{
    0%   {{ stroke-dashoffset: 1400; }}
    100% {{ stroke-dashoffset: 0; }}
  }}
  @keyframes fineFlow2 {{
    0%   {{ stroke-dashoffset: 1400; }}
    100% {{ stroke-dashoffset: 0; }}
  }}
  @keyframes fineFlowRev {{
    0%   {{ stroke-dashoffset: -1400; }}
    100% {{ stroke-dashoffset: 0; }}
  }}
  @keyframes whisperPulse {{
    0%, 100% {{ opacity: 0.20; }}
    50%      {{ opacity: 0.42; }}
  }}
  @keyframes dustFloat {{
    0%, 100% {{ transform: translate3d(0, 0, 0); opacity: 0.30; }}
    50%      {{ transform: translate3d(10px, -3px, 0); opacity: 0.80; }}
  }}

  .command-center-wrap {{
    width: 100%;
    max-width: 740px;
    margin: 0 auto 50px auto;
    position: relative;
    z-index: 10;
  }}
  .command-bar-shell {{
    display: flex;
    align-items: center;
    background: #181A1F;
    border: 1px solid #282C34;
    border-radius: 14px;
    height: 54px;
    padding: 0 14px 0 22px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.55);
    transition: border-color var(--dur-hover) var(--ease-smooth),
                box-shadow var(--dur-hover) var(--ease-smooth),
                background var(--dur-hover) var(--ease-smooth);
  }}
  .command-bar-shell:hover {{
    border-color: #3A3F48;
  }}
  .command-bar-shell:focus-within {{
    background: #1C1F26;
    border-color: rgba(111, 163, 216, 0.55);
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.72), 0 0 0 1px rgba(111, 163, 216, 0.20);
  }}
  .cmd-input {{
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--paper-50);
    font-family: var(--font-ui);
    font-size: 15px;
    font-weight: 400;
  }}
  .cmd-input::placeholder {{
    color: #7D828C;
  }}

  .voice-btn {{
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: transparent;
    border: none;
    color: #D9D8D3;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
    margin-left: 10px;
  }}
  .voice-btn:hover {{
    color: var(--paper-50);
    background: rgba(255, 255, 255, 0.06);
  }}
  .voice-btn.recording {{
    background: var(--flare-500);
    color: var(--paper-50);
  }}

  .cmd-response-drawer {{
    display: none;
    margin-top: 14px;
    background: rgba(16, 18, 22, 0.96);
    border: 1px solid var(--space-700);
    border-left: 3px solid var(--sky-400);
    border-radius: 12px;
    padding: 16px 20px;
    font-size: 13.5px;
    line-height: 1.6;
    color: var(--paper-200);
    box-shadow: 0 16px 38px rgba(0, 0, 0, 0.75);
  }}
  .cmd-response-drawer.open {{
    display: block;
    animation: interiorFadeUp var(--dur-hover) var(--ease-smooth) forwards;
  }}
  .cmd-resp-head {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: var(--font-ui);
    font-size: 11px;
    font-weight: 600;
    color: var(--sky-400);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .cmd-resp-close {{
    background: transparent;
    border: none;
    color: var(--paper-200);
    font-family: var(--font-ui);
    font-size: 12px;
    cursor: pointer;
  }}

  /* =========================================================================
     1 & 4. BUBBLES (Static at rest, formal -4px / 1.025 hover)
     ========================================================================= */
  .circular-orbs-row {{
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 38px;
    flex-wrap: wrap;
    z-index: 10;
  }}

  @keyframes bubbleLoadFadeUp {{
    0% {{
      opacity: 0;
      transform: translate3d(0, 14px, 0);
    }}
    100% {{
      opacity: 1;
      transform: translate3d(0, 0, 0);
    }}
  }}

  .orb-slot {{
    opacity: 0;
  }}
  .orb-slot.entered.slot-1 {{ animation: bubbleLoadFadeUp var(--dur-entrance) var(--ease-smooth) 40ms forwards; }}
  .orb-slot.entered.slot-2 {{ animation: bubbleLoadFadeUp var(--dur-entrance) var(--ease-smooth) 110ms forwards; }}
  .orb-slot.entered.slot-3 {{ animation: bubbleLoadFadeUp var(--dur-entrance) var(--ease-smooth) 180ms forwards; }}
  .orb-slot.entered.slot-4 {{ animation: bubbleLoadFadeUp var(--dur-entrance) var(--ease-smooth) 250ms forwards; }}

  .floating-orb {{
    width: 146px;
    height: 146px;
    aspect-ratio: 1 / 1;
    border-radius: 50% !important;
    background: radial-gradient(
      circle at 32% 28%,
      rgba(18, 48, 110, 0.44) 0%,
      rgba(16, 18, 22, 0.96) 74%
    );
    border: 1px solid rgba(111, 163, 216, 0.28);
    box-shadow:
      0 10px 24px rgba(0, 0, 0, 0.55),
      inset 0 1px 2px rgba(244, 243, 239, 0.10);
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 18px;
    position: relative;
    overflow: hidden;
    user-select: none;
    cursor: pointer;
    will-change: transform, box-shadow;
    transition: transform var(--dur-hover) var(--ease-smooth),
                box-shadow var(--dur-hover) var(--ease-smooth),
                border-color var(--dur-hover) var(--ease-smooth),
                filter var(--dur-hover) var(--ease-smooth);
  }}

  .floating-orb::after {{
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 1px solid rgba(232, 241, 250, 0.55);
    opacity: 0;
    pointer-events: none;
    transition: opacity var(--dur-hover) var(--ease-smooth);
  }}

  @media (hover: hover) {{
    .floating-orb:hover {{
      transform: translate3d(0, -4px, 0) scale(1.025);
      border-color: rgba(188, 214, 238, 0.58);
      box-shadow:
        0 20px 42px rgba(0, 0, 0, 0.82),
        0 6px 18px rgba(18, 48, 110, 0.32),
        inset 0 1px 3px rgba(244, 243, 239, 0.18);
      filter: brightness(1.06);
    }}
    .floating-orb:hover::after {{
      opacity: 1;
    }}
  }}

  .floating-orb:active {{
    transform: translate3d(0, -1px, 0) scale(0.97) !important;
    transition: transform var(--dur-press) var(--ease-smooth) !important;
  }}

  .orb-title {{
    position: relative;
    z-index: 2;
    font-family: var(--font-ui);
    font-size: 13px;
    font-weight: 600;
    line-height: 1.3;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--paper-50);
    transition: color var(--dur-hover) var(--ease-smooth);
    pointer-events: none;
  }}
  .floating-orb:hover .orb-title {{
    color: var(--glow-100);
  }}

  /* =========================================================================
     BUBBLE WORKSPACES (1, 2, 4 EMPTY & 3 DUAL-SECTION SIMULATIONS)
     ========================================================================= */
  .workspace-wrap {{
    background: transparent;
    padding: 8px 16px 32px 16px;
    min-height: 82vh;
  }}
  .workspace-card {{
    background: rgba(16, 18, 22, 0.95);
    border: 1px solid var(--space-700);
    border-radius: 14px;
    padding: 22px 24px;
    max-width: 1380px;
    margin: 0 auto;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.70);
  }}
  .ws-header-row {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 1px solid var(--space-700);
    padding-bottom: 14px;
    margin-bottom: 18px;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .ws-tag {{
    font-family: var(--font-ui);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--sky-400);
    margin-bottom: 4px;
  }}
  .ws-title {{
    font-family: var(--font-ui);
    font-size: 28px;
    font-weight: 650;
    color: var(--paper-50);
    letter-spacing: -0.025em;
    line-height: 1.15;
    text-wrap: balance;
  }}
  .switch-bubble-btn {{
    background: var(--space-900);
    color: var(--paper-200);
    border: 1px solid var(--space-700);
    border-radius: 8px;
    padding: 8px 16px;
    font-family: var(--font-ui);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.01em;
    cursor: pointer;
  }}
  .switch-bubble-btn:hover {{
    background: var(--space-700);
    border-color: rgba(111, 163, 216, 0.45);
    color: var(--paper-50);
    box-shadow: 0 6px 18px rgba(47, 99, 176, 0.35);
  }}

  .empty-module-box {{
    min-height: 360px;
    background: var(--space-900);
    border: 1px dashed var(--space-700);
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 32px;
    text-align: center;
    gap: 16px;
  }}
  .empty-module-code {{
    font-family: var(--font-ui);
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--space-500);
  }}

  .exp-pills-row {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
  }}

  .sim-subtabs-bar {{
    display: inline-flex;
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 4px;
    gap: 6px;
    margin-bottom: 18px;
  }}
  .sim-subtab-btn {{
    background: transparent;
    color: var(--paper-200);
    border: none;
    border-radius: 7px;
    padding: 8px 18px;
    font-family: var(--font-ui);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
  }}
  .sim-subtab-btn:hover {{
    color: var(--paper-50);
    background: var(--space-800);
  }}
  .sim-subtab-btn.active {{
    background: var(--sky-600);
    color: var(--paper-50);
    box-shadow: 0 4px 14px rgba(47, 99, 176, 0.35);
  }}
  .sim-subview {{
    display: none;
  }}
  .sim-subview.active {{
    display: block;
    animation: interiorFadeUp var(--dur-entrance) var(--ease-smooth) forwards;
  }}

  .sim-sec1-grid {{
    display: grid;
    grid-template-columns: 1.15fr 0.85fr;
    gap: 22px;
    align-items: start;
  }}
  @media (max-width: 980px) {{
    .sim-sec1-grid {{ grid-template-columns: 1fr; }}
  }}
  /* ---------- PHONES: use the whole width, no sideways scroll ---------- */
  html, body {{ overflow-x: hidden; }}
  @media (max-width: 600px) {{
    .workspace-wrap {{ padding-left: 8px !important; padding-right: 8px !important; }}
    .workspace-card {{ padding: 16px 12px !important; border-radius: 16px; }}
    .empty-module-box {{ padding: 16px 10px !important; }}
    .ws-header-row {{ flex-wrap: wrap; gap: 10px; }}
    .ws-title {{ font-size: clamp(24px, 7.4vw, 34px); }}
    .psi-browser {{ margin-top: 18px; }}
    .psi-card {{ padding: 12px 12px; }}
    #flammy-bubble {{ max-width: calc(100vw - 24px); font-size: 13px; }}
  }}

  .ctrl-row {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 14px;
  }}

  .field-label {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: var(--font-ui);
    font-size: 12px;
    font-weight: 500;
    color: var(--paper-200);
    margin-bottom: 6px;
  }}
  .field-val {{
    font-family: var(--font-data);
    font-size: 13px;
    font-weight: 700;
    color: var(--glow-100);
  }}

  select, option {{
    width: 100%;
    background: var(--space-900);
    color: var(--paper-50);
    border: 1px solid var(--space-700);
    border-radius: 8px;
    padding: 9px 12px;
    font-family: var(--font-ui);
    font-size: 13.5px;
    font-weight: 500;
    outline: none;
    cursor: pointer;
    transition: border-color var(--dur-fast) var(--ease-smooth);
  }}
  select:hover, select:focus {{
    border-color: rgba(111, 163, 216, 0.55);
  }}

  .sliders-box {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 14px;
  }}
  .slider-group {{
    margin-bottom: 14px;
  }}
  .slider-group:last-child {{
    margin-bottom: 0;
  }}

  input[type="range"] {{
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    background: var(--space-700);
    border-radius: 999px;
    outline: none;
    cursor: grab;
  }}
  input[type="range"]:active {{
    cursor: grabbing;
  }}
  input[type="range"]::-webkit-slider-thumb {{
    -webkit-appearance: none;
    appearance: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--sky-600);
    border: 2px solid var(--glow-100);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.55);
    transition: transform var(--dur-fast) var(--ease-smooth), background var(--dur-fast) var(--ease-smooth);
  }}
  input[type="range"]::-webkit-slider-thumb:hover {{
    transform: scale(1.12);
    background: var(--sky-400);
  }}
  input[type="range"]::-webkit-slider-thumb:active {{
    transform: scale(0.95);
  }}

  .toggle-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--space-700);
    font-size: 13px;
    font-weight: 500;
    color: var(--paper-200);
    cursor: pointer;
    user-select: none;
  }}
  .toggle-row input[type="checkbox"] {{
    accent-color: var(--sky-600);
    width: 15px;
    height: 15px;
    cursor: pointer;
  }}

  .tgrid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    margin-bottom: 14px;
  }}
  .tcard {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 12px 14px;
    transition: border-color var(--dur-hover) var(--ease-smooth),
                transform var(--dur-hover) var(--ease-smooth);
  }}
  .tcard:hover {{
    transform: translate3d(0, -2px, 0);
    border-color: rgba(111, 163, 216, 0.35);
  }}
  .tcard-lbl {{
    font-family: var(--font-ui);
    font-size: 11.5px;
    font-weight: 600;
    color: var(--paper-200);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
  }}
  .tcard-val {{
    font-family: var(--font-data);
    font-size: 22px;
    font-weight: 600;
    color: var(--paper-50);
    white-space: nowrap;
    letter-spacing: -0.02em;
  }}
  .tcard-sub {{
    font-family: var(--font-ui);
    font-size: 11px;
    font-weight: 500;
    color: var(--sky-200);
    margin-top: 2px;
    white-space: nowrap;
  }}

  .svg-card {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 8px 12px;
    margin-bottom: 12px;
  }}

  .banner {{
    font-family: var(--font-ui);
    font-size: 13.5px;
    font-weight: 600;
    letter-spacing: 0.01em;
    border-left: 4px solid;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 12px;
    line-height: 1.5;
  }}
  .banner.low    {{ color: var(--glow-100);  border-color: var(--sky-400);   background: rgba(18, 48, 110, 0.38); }}
  .banner.medium {{ color: var(--flare-200); border-color: var(--flare-400); background: rgba(140, 42, 8, 0.30); }}
  .banner.high   {{ color: var(--paper-50);  border-color: var(--flare-500); background: rgba(140, 42, 8, 0.52); }}

  .insight-box {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 14px 16px;
    font-size: 13px;
    font-weight: 400;
    line-height: 1.55;
    color: var(--paper-200);
  }}
  .insight-box b {{
    color: var(--paper-50);
    font-weight: 600;
  }}
  .insight-row {{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 10px;
  }}
  .insight-row:last-child {{ margin-bottom: 0; }}
  .tag {{
    font-family: var(--font-ui);
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.06em;
    padding: 3px 9px;
    border-radius: 4px;
    white-space: nowrap;
    margin-top: 2px;
    color: var(--space-900);
  }}

  .vis-box {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    overflow: hidden;
    padding: 6px;
  }}

  .phys-summary-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-top: 12px;
  }}
  .phys-pill {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 10px 12px;
    transition: border-color var(--dur-hover) var(--ease-smooth),
                transform var(--dur-hover) var(--ease-smooth);
  }}
  .phys-pill:hover {{
    transform: translate3d(0, -2px, 0);
    border-color: rgba(111, 163, 216, 0.35);
  }}
  .phys-pill-lbl {{
    font-family: var(--font-ui);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--paper-200);
    margin-bottom: 3px;
  }}
  .phys-pill-val {{
    font-family: var(--font-data);
    font-size: 13px;
    font-weight: 600;
    color: var(--paper-50);
  }}

  .eclss-box {{
    margin-top: 12px;
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 14px 16px;
  }}
  .eclss-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .eclss-title {{
    font-family: var(--font-ui);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--sky-400);
  }}
  .eclss-sub {{
    font-size: 13px;
    font-weight: 500;
    color: var(--paper-200);
    margin-top: 3px;
  }}
  .eclss-sub b {{
    color: var(--paper-50);
  }}
  .eclss-trigger-btn {{
    background: var(--sky-600);
    color: var(--paper-50);
    border: 1px solid var(--sky-400);
    border-radius: 8px;
    padding: 9px 16px;
    font-family: var(--font-ui);
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    cursor: pointer;
  }}
  .eclss-trigger-btn:hover {{
    background: var(--sky-800);
    border-color: var(--glow-100);
    transform: translate3d(0, -1px, 0);
  }}
  .eclss-log {{
    display: none;
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--space-700);
  }}
  .eclss-step {{
    display: flex;
    align-items: flex-start;
    gap: 10px;
    font-size: 13px;
    line-height: 1.5;
    color: var(--paper-200);
    margin-bottom: 6px;
    opacity: 0.35;
    transition: opacity 0.25s ease, color 0.25s ease;
  }}
  .eclss-step.active {{
    opacity: 1;
    color: var(--paper-50);
  }}
  .eclss-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--space-500);
    margin-top: 6px;
    flex-shrink: 0;
  }}
  .eclss-step.active .eclss-dot {{
    background: var(--sky-400);
    box-shadow: 0 0 8px var(--sky-400);
  }}

  /* SVG Animations */
  .sb-breathe {{ animation: sb-b 3.4s ease-in-out infinite; }}
  .sb-float   {{ animation: sb-f 4.2s ease-in-out infinite; }}
  .pulse      {{ animation: sb-p 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: 50% 100%; }}
  .pulse-c    {{ animation: sb-p 2.2s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }}
  .smoke-0g   {{ animation: smk-0g 3.2s ease-in-out infinite; }}
  .smoke-1g   {{ animation: smk-1g 2.4s ease-in-out infinite; }}
  @keyframes sb-b {{ 50% {{ transform: translateY(-3px); }} }}
  @keyframes sb-f {{ 50% {{ transform: translateY(-8px); }} }}
  @keyframes sb-p {{ 50% {{ transform: scale(1.06); }} }}
  @keyframes smk-0g {{ 0%, 100% {{ transform: translate(0, 0); opacity: 0.35; }} 50% {{ transform: translate(-10px, -6px); opacity: 0.65; }} }}
  @keyframes smk-1g {{ 0%, 100% {{ transform: translateY(0); opacity: 0.35; }} 50% {{ transform: translateY(-12px); opacity: 0.65; }} }}

  /* =========================================================================
     ACCESSIBILITY: RESPECT `prefers-reduced-motion`
     ========================================================================= */
  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }}
    .orb-slot {{
      opacity: 1 !important;
    }}
  }}

  /* =========================================================================
     FLAMMY COMPANION: microgravity spherical flame that follows the visitor
     ========================================================================= */
  #flammy-buddy {{
    position: absolute; top: 0; left: 0; z-index: 900;
    width: 76px; height: 76px;
    transform: translate3d(-200px, -200px, 0);
    transition: transform 720ms var(--ease-smooth), opacity 320ms var(--ease-smooth);
    opacity: 0; pointer-events: none;
  }}
  #flammy-buddy.on {{ opacity: 1; pointer-events: auto; }}
  #flammy-buddy-body {{
    all: unset; display: block; width: 76px; height: 76px; cursor: pointer; border-radius: 50%;
    animation: flammyBob 3.6s ease-in-out infinite;
  }}
  #flammy-buddy-body:focus-visible {{ outline: 2px solid var(--sky-400); outline-offset: 4px; }}
  #flammy-buddy.flying #flammy-buddy-body {{ animation-duration: 1.2s; }}
  #flammy-buddy-body svg {{ width: 100%; height: 100%; overflow: visible; display: block; }}
  .fb-close svg {{ width: 10px; height: 10px; display: block; }}
  .fl-glow  {{ transform-box: fill-box; transform-origin: center; animation: flammyGlow 2.8s ease-in-out infinite; }}
  .fl-shell {{ transform-box: fill-box; transform-origin: 50% 60%; animation: flammyFlicker 1.9s ease-in-out infinite; }}
  .fl-eyes  {{ transform-box: fill-box; transform-origin: center; animation: flammyBlink 5.2s infinite; }}
  .fl-look  {{ transition: transform 220ms var(--ease-out); }}
  @keyframes flammyBob     {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-6px); }} }}
  @keyframes flammyGlow    {{ 0%,100% {{ transform: scale(1); opacity: .75; }} 50% {{ transform: scale(1.07); opacity: 1; }} }}
  @keyframes flammyFlicker {{ 0%,100% {{ transform: scale(1,1); }} 30% {{ transform: scale(1.03,.97); }} 65% {{ transform: scale(.98,1.03); }} }}
  @keyframes flammyBlink   {{ 0%,92%,100% {{ transform: scaleY(1); }} 95% {{ transform: scaleY(.1); }} }}

  #flammy-bubble {{
    position: absolute; bottom: 58px; right: 70px;
    width: max-content; max-width: min(320px, calc(100vw - 120px));
    background: #101216; color: var(--paper-50);
    border: 1px solid var(--space-700); border-radius: 14px 14px 4px 14px;
    padding: 12px 14px 13px;
    font: 400 13.5px/1.5 var(--font-ui); text-wrap: pretty;
    box-shadow: 0 14px 34px rgba(0, 0, 0, 0.55), 0 2px 6px rgba(0, 0, 0, 0.4);
    opacity: 0; transform: translate3d(8px, 6px, 0) scale(.96); transform-origin: 100% 100%;
    transition: opacity 260ms var(--ease-smooth), transform 340ms var(--ease-smooth), border-color 260ms;
    pointer-events: none;
  }}
  #flammy-buddy.bubble-right #flammy-bubble {{ right: auto; left: 70px; border-radius: 14px 14px 14px 4px; transform-origin: 0 100%; }}
  #flammy-bubble.show {{ opacity: 1; transform: none; pointer-events: auto; }}
  .fb-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 5px; padding-right: 22px; }}
  .fb-name {{ font: 600 12px var(--font-ui); color: var(--sky-200); letter-spacing: .02em; }}
  .fb-level {{ font: 600 10.5px var(--font-ui); letter-spacing: .05em; text-transform: uppercase;
              padding: 2px 7px; border-radius: 999px; background: rgba(111, 163, 216, .16); color: var(--sky-200); }}
  .fb-level.amber {{ background: rgba(255, 138, 42, .16); color: var(--flare-200); }}
  .fb-level.red   {{ background: rgba(242, 96, 15, .22); color: #FFD9BD; }}
  .fb-level:empty {{ display: none; }}
  .fb-title {{ font-weight: 600; color: var(--glow-100); margin-bottom: 3px; text-wrap: balance; }}
  .fb-text {{ color: #C4C3BE; }}
  .fb-action {{ margin-top: 7px; padding-top: 7px; border-top: 1px solid var(--space-700); color: var(--paper-50); }}
  .fb-action b {{ color: var(--sky-200); font-weight: 600; }}
  .fb-close {{
    all: unset; position: absolute; top: 9px; right: 9px; width: 20px; height: 20px; border-radius: 6px;
    display: grid; place-items: center; cursor: pointer; color: #8A909A;
  }}
  .fb-close:hover {{ color: var(--paper-50); background: var(--space-700); }}
  .fb-close:focus-visible {{ outline: 2px solid var(--sky-400); }}
  .fb-dots span {{ display: inline-block; width: 5px; height: 5px; margin-right: 4px; border-radius: 50%;
                  background: var(--sky-400); animation: flammyDot 1s ease-in-out infinite; }}
  .fb-dots span:nth-child(2) {{ animation-delay: .15s; }} .fb-dots span:nth-child(3) {{ animation-delay: .3s; }}
  @keyframes flammyDot {{ 0%,100% {{ opacity: .25; }} 50% {{ opacity: 1; }} }}

  @media (prefers-reduced-motion: reduce) {{
    #flammy-buddy {{ transition: opacity 200ms linear; }}
    #flammy-buddy-body, .fl-glow, .fl-shell, .fl-eyes, .fb-dots span {{ animation: none; }}
  }}
{IA_CHAT_CSS}
{LIB_CSS}
{SAFETY_CSS}
{THEORY_CSS}
</style>
</head>
<body>

<!-- SUBTLE SLOW-SHIFTING ATMOSPHERIC GRADIENT BACKDROP -->
<div id="ambient-gradient-backdrop"></div>

<!-- FLIP IMMERSIVE BUBBLE ZOOM PORTAL -->
<div id="bubble-zoom-portal"></div>

<!-- =========================================================================
     VIEW 0: DUAL-VIDEO HARDWARE CROSSFADE COVER (Loops from t = 8.0s forever)
     ========================================================================= -->
<div id="view-cover" class="os-view active">
  <div class="cover-stage">


    <div class="cover-video-viewport">
      <video id="flama-vid-a" class="cover-vid-layer" style="opacity:1;" muted playsinline preload="auto" data-src="{video_data_uri}"></video>
      <video id="flama-vid-b" class="cover-vid-layer" style="opacity:0;" muted playsinline preload="auto" data-src="{video_data_uri}"></video>
    </div>

    <button id="si-enter-console-btn" class="cover-init-btn press-able">INITIALIZE</button>
  </div>
</div>

<!-- =========================================================================
     TOP-LEFT FLAMA LOGO (BLUISH MICROGRAVITY FLAME SPHERE) + HAMBURGER MENU
     ========================================================================= -->
<div id="top-nav-bar" class="top-nav-row">
  <div class="top-left-brand-group">
    <button id="flama-logo-home" class="flama-logo-home-btn press-able" title="FLAMA — Return to Command Hub">
      {flama_top_left_logo_svg}
    </button>

    <button id="hamburger-toggle" class="hamburger-btn press-able" title="Navigation Menu">
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
    </button>
  </div>

  <div id="hamburger-menu" class="hamburger-dropdown">
    <button id="menu-btn-hub" class="menu-item active">
      <span>00 / Command Hub</span><span>●</span>
    </button>
    <button id="menu-btn-investigations" class="menu-item">
      <span>01 / Most Relevant Investigations</span><span>→</span>
    </button>
    <button id="menu-btn-mechanisms" class="menu-item">
      <span>02 / Safety Mechanisms</span><span>→</span>
    </button>
    <button id="menu-btn-simulations" class="menu-item">
      <span>03 / Simulations</span><span>→</span>
    </button>
    <button id="menu-btn-relations" class="menu-item">
      <span>04 / Experiment Relations</span><span>→</span>
    </button>
    <button id="menu-btn-cover" class="menu-item">
      <span>↺ Cover Screen</span><span>↗</span>
    </button>
  </div>
</div>

<!-- =========================================================================
     VIEW 1: COMMAND HUB (Cosmic Trail + Command Bar + 4 Formal Static Orbs)
     ========================================================================= -->
<div id="view-hub" class="os-view">
  <div class="hub-stage">

    <div class="cosmic-comet-stage">
      <svg viewBox="0 0 1320 175" style="width:100%;height:100%;overflow:visible;">
        <defs>
          <linearGradient id="fineIonBlue" x1="0%" y1="50%" x2="100%" y2="50%">
            <stop offset="0%"   stop-color="#07080A" stop-opacity="0"/>
            <stop offset="10%"  stop-color="#12306E" stop-opacity="0.35"/>
            <stop offset="38%"  stop-color="#2F63B0" stop-opacity="0.80"/>
            <stop offset="68%"  stop-color="#6FA3D8" stop-opacity="0.95"/>
            <stop offset="88%"  stop-color="#E8F1FA" stop-opacity="0.98"/>
            <stop offset="100%" stop-color="#07080A" stop-opacity="0"/>
          </linearGradient>

          <linearGradient id="fineDustOrange" x1="0%" y1="50%" x2="100%" y2="50%">
            <stop offset="0%"   stop-color="#07080A" stop-opacity="0"/>
            <stop offset="14%"  stop-color="#8C2A08" stop-opacity="0.35"/>
            <stop offset="45%"  stop-color="#F2600F" stop-opacity="0.88"/>
            <stop offset="72%"  stop-color="#FF8A2A" stop-opacity="0.95"/>
            <stop offset="90%"  stop-color="#FFC27A" stop-opacity="0.98"/>
            <stop offset="100%" stop-color="#07080A" stop-opacity="0"/>
          </linearGradient>

          <linearGradient id="fineWhiteCore" x1="0%" y1="50%" x2="100%" y2="50%">
            <stop offset="0%"   stop-color="#07080A" stop-opacity="0"/>
            <stop offset="45%"  stop-color="#BCD6EE" stop-opacity="0.35"/>
            <stop offset="78%"  stop-color="#F4F3EF" stop-opacity="1.0"/>
            <stop offset="92%"  stop-color="#FFC27A" stop-opacity="0.92"/>
            <stop offset="100%" stop-color="#07080A" stop-opacity="0"/>
          </linearGradient>

          <radialGradient id="cometHeadGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stop-color="#F4F3EF" stop-opacity="1.0"/>
            <stop offset="35%"  stop-color="#E8F1FA" stop-opacity="0.9"/>
            <stop offset="68%"  stop-color="#6FA3D8" stop-opacity="0.45"/>
            <stop offset="100%" stop-color="#07080A" stop-opacity="0.0"/>
          </radialGradient>

          <filter id="fineGlow" x="-20%" y="-40%" width="140%" height="180%">
            <feGaussianBlur stdDeviation="4.5" result="blur"/>
            <feMerge>
              <feMergeNode in="blur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>

          <path id="cometMasterOrbit"
                d="M 15,138 C 330,18 680,154 1020,44 C 1145,8 1235,34 1305,22"/>
          <path id="cometSecondaryOrbit"
                d="M 25,108 C 370,162 720,16 1055,88 C 1165,112 1245,74 1305,58"/>
        </defs>

        <use href="#cometMasterOrbit" class="nebula-whisper"
             fill="none" stroke="url(#fineIonBlue)" stroke-width="8"
             filter="url(#fineGlow)" stroke-linecap="round"/>
        <use href="#cometSecondaryOrbit" class="nebula-whisper"
             fill="none" stroke="url(#fineDustOrange)" stroke-width="6"
             filter="url(#fineGlow)" stroke-linecap="round"/>

        <use href="#cometMasterOrbit"
             fill="none" stroke="url(#fineIonBlue)" stroke-width="0.85" opacity="0.42"/>
        <use href="#cometSecondaryOrbit"
             fill="none" stroke="url(#fineDustOrange)" stroke-width="0.75" opacity="0.38"/>
        <path d="M 40,124 C 350,52 700,126 1035,64 C 1155,42 1240,54 1305,40"
              fill="none" stroke="url(#fineWhiteCore)" stroke-width="0.6" stroke-dasharray="3 6" opacity="0.32"/>

        <use href="#cometMasterOrbit" class="fine-stream-blue"
             fill="none" stroke="url(#fineIonBlue)" stroke-width="1.9"
             filter="url(#fineGlow)" stroke-linecap="round"/>

        <use href="#cometSecondaryOrbit" class="fine-stream-orange"
             fill="none" stroke="url(#fineDustOrange)" stroke-width="1.6"
             filter="url(#fineGlow)" stroke-linecap="round"/>

        <path class="fine-Sec-filament"
              d="M 40,124 C 350,52 700,126 1035,64 C 1155,42 1240,54 1305,40"
              fill="none" stroke="url(#fineIonBlue)" stroke-width="1.1"
              stroke-linecap="round" opacity="0.75"/>

        <use href="#cometMasterOrbit" class="fine-stream-white"
             fill="none" stroke="url(#fineWhiteCore)" stroke-width="2.2"
             filter="url(#fineGlow)" stroke-linecap="round"/>

        <g>
          <circle r="13" fill="url(#cometHeadGlow)"/>
          <ellipse rx="9" ry="2.2" fill="#E8F1FA" filter="url(#fineGlow)"/>
          <circle r="2.6" fill="#F4F3EF"/>
          <animateMotion dur="12s" repeatCount="indefinite" rotate="auto">
            <mpath href="#cometMasterOrbit"/>
          </animateMotion>
        </g>

        <g>
          <circle r="7" fill="#FF8A2A" opacity="0.45" filter="url(#fineGlow)"/>
          <circle r="2.0" fill="#FFC27A"/>
          <animateMotion dur="15s" repeatCount="indefinite" rotate="auto">
            <mpath href="#cometSecondaryOrbit"/>
          </animateMotion>
        </g>

        <g class="dust-twinkle-a">
          <circle cx="145"  cy="98" r="1.3" fill="#E8F1FA"/>
          <circle cx="335"  cy="74" r="1.6" fill="#6FA3D8" filter="url(#fineGlow)"/>
          <circle cx="525"  cy="88" r="1.4" fill="#FFC27A"/>
          <circle cx="715"  cy="92" r="1.8" fill="#F4F3EF" filter="url(#fineGlow)"/>
          <circle cx="910"  cy="68" r="1.5" fill="#FF8A2A"/>
          <circle cx="1115" cy="36" r="1.6" fill="#E8F1FA" filter="url(#fineGlow)"/>
        </g>
        <g class="dust-twinkle-b">
          <circle cx="235"  cy="112" r="1.1" fill="#FFC27A"/>
          <circle cx="430"  cy="66"  r="1.4" fill="#F4F3EF"/>
          <circle cx="620"  cy="78"  r="1.5" fill="#6FA3D8" filter="url(#fineGlow)"/>
          <circle cx="815"  cy="82"  r="1.3" fill="#F2600F"/>
          <circle cx="1015" cy="52"  r="1.7" fill="#FFC27A" filter="url(#fineGlow)"/>
          <circle cx="1210" cy="44"  r="1.2" fill="#6FA3D8"/>
        </g>
      </svg>
    </div>

    <!-- CENTER COMMAND BAR -->
    <div class="command-center-wrap">
      <div class="command-bar-shell">
        <input id="hub-cmd-input" class="cmd-input" type="text"
               placeholder="Describe an on-board scenario or ask the AI (or press the mic)…">
        <button id="hub-voice-btn" class="voice-btn press-able" title="Voice Command">
          <svg class="anim-icon" viewBox="0 0 24 24" style="width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;">
            <rect x="9" y="2" width="6" height="11" rx="3"/>
            <path d="M5 10a7 7 0 0 0 14 0"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
            <line x1="9" y1="21" x2="15" y2="21"/>
          </svg>
        </button>
      </div>

      {IA_CHAT_HTML}

      <div id="hub-cmd-drawer" class="cmd-response-drawer">
        <div class="cmd-resp-head">
          <span id="hub-cmd-status">FLAMA SI // PREDICTIVE SCENARIO SYNTHESIS</span>
          <button id="hub-cmd-close" class="cmd-resp-close press-able">✕</button>
        </div>
        <div id="hub-cmd-output"></div>
      </div>
    </div>

    <!-- 4 CIRCULAR BUBBLES (Static at rest, formal -4px / 1.025 hover) -->
    <div class="circular-orbs-row">
      <!-- Bubble 1 (Left): MOST RELEVANT INVESTIGATIONS -->
      <div class="orb-slot slot-1">
        <div id="orb-investigations" class="floating-orb" tabindex="0" role="button" data-target="investigations">
          <span class="orb-title">Most Relevant<br>Investigations</span>
        </div>
      </div>

      <!-- Bubble 2: SAFETY MECHANISMS -->
      <div class="orb-slot slot-2">
        <div id="orb-mechanisms" class="floating-orb" tabindex="0" role="button" data-target="mechanisms">
          <span class="orb-title">Safety<br>Mechanisms</span>
        </div>
      </div>

      <!-- Bubble 3: SIMULATIONS -->
      <div class="orb-slot slot-3">
        <div id="orb-simulations" class="floating-orb" tabindex="0" role="button" data-target="simulations">
          <span class="orb-title">Simulations</span>
        </div>
      </div>

      <!-- Bubble 4 (Right): EXPERIMENT RELATIONS -->
      <div class="orb-slot slot-4">
        <div id="orb-relations" class="floating-orb" tabindex="0" role="button" data-target="relations">
          <span class="orb-title">Experiment<br>Relations</span>
        </div>
      </div>
    </div>

  </div>
</div>

<!-- =========================================================================
     BUBBLE 1 VIEW: MOST RELEVANT INVESTIGATIONS (With Experiment Observers)
     ========================================================================= -->
<div id="view-investigations" class="os-view">
  <div class="workspace-wrap">
    <div class="workspace-card stagger-item" style="--stagger-idx: 0;">
      <div class="ws-header-row stagger-item" style="--stagger-idx: 1;">
        <div>
          <div class="ws-tag">NASA PSI ARCHIVE</div>
          <div class="ws-title">Most Relevant Investigations</div>
        </div>
        <button class="switch-bubble-btn press-able btn-back-hub">← Command Hub</button>
      </div>
      <div class="empty-module-box stagger-item reveal-on-scroll" style="--stagger-idx: 2;">
        <div class="empty-module-code">MODULE 01 // FLIGHT-PROGRAM OBSERVERS — TAP TO INSPECT WITH FLAMMY</div>
        <div class="exp-pills-row">
          {EXP_BUTTONS_HTML}
        </div>
        <!-- Flammy Experiment Output Box (Populated live via HTTP/SSE) -->
        <div id="flammy-exp-advisory-box" class="insight-box" style="display:none;max-width:860px;width:100%;text-align:left;"></div>
        <!-- PSI Investigation Browser: the full local archive, filtered + ranked vs the live sim -->
        {_PSI_BROWSER_HTML}
      </div>
    </div>
  </div>
</div>

<!-- =========================================================================
     BUBBLE 2 VIEW: SAFETY MECHANISMS (Empty for now)
     ========================================================================= -->
<div id="view-mechanisms" class="os-view">
  <div class="workspace-wrap">
    <div class="workspace-card stagger-item" style="--stagger-idx: 0;">
      <div class="ws-header-row stagger-item" style="--stagger-idx: 1;">
        <div>
          <div class="ws-tag">ECLSS &amp; FIRE PROTECTION</div>
          <div class="ws-title">Safety Mechanisms</div>
        </div>
        <button class="switch-bubble-btn press-able btn-back-hub">← Command Hub</button>
      </div>
      <div class="stagger-item" style="--stagger-idx: 2;">
        {SAFETY_HTML}
      </div>
    </div>
  </div>
</div>

<!-- =========================================================================
     BUBBLE 3 VIEW: SIMULATIONS (Section 01: Sackboy Simulation | Section 02: Empty)
     ========================================================================= -->
<div id="view-simulations" class="os-view">
  <div class="workspace-wrap">
    <div class="workspace-card stagger-item" style="--stagger-idx: 0;">
      <div class="ws-header-row stagger-item" style="--stagger-idx: 1;">
        <div>
          <div class="ws-tag">INTERACTIVE MICROGRAVITY SIMULATION ZONE</div>
          <div class="ws-title">Simulations</div>
        </div>
        <button class="switch-bubble-btn press-able btn-back-hub">← Command Hub</button>
      </div>

      <!-- 3D CABIN FIRE SIMULATOR (the only Simulations workspace) -->
      <div id="sim-sec-2" class="sim-subview active">
        {SIM3D_HTML}
      </div>

    </div>
  </div>
</div>

<!-- =========================================================================
     BUBBLE 4 VIEW: EXPERIMENT RELATIONS (Empty for now)
     ========================================================================= -->
<div id="view-relations" class="os-view">
  <div class="workspace-wrap">
    <div class="workspace-card stagger-item" style="--stagger-idx: 0;">
      <div class="ws-header-row stagger-item" style="--stagger-idx: 1;">
        <div>
          <div class="ws-tag">CROSS-INVESTIGATION CORRELATIONS</div>
          <div class="ws-title">Experiment Relations</div>
        </div>
        <button class="switch-bubble-btn press-able btn-back-hub">← Command Hub</button>
      </div>
      <div class="stagger-item" style="--stagger-idx: 2;">
        {THEORY_HTML}
      </div>
    </div>
  </div>
</div>


<!-- FLAMMY COMPANION (follows the visitor across views; speaks advisories) -->
<div id="flammy-buddy" aria-live="polite">
  <div id="flammy-bubble" role="status">
    <button class="fb-close" type="button" aria-label="Dismiss Flammy's message">
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 1l8 8M9 1L1 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
    </button>
    <div class="fb-head"><span class="fb-name">Flammy</span><span class="fb-level"></span></div>
    <div class="fb-content"></div>
  </div>
  <button id="flammy-buddy-body" type="button" aria-label="Flammy, your fire-safety companion. Show the last tip.">
    <svg viewBox="0 0 76 76" aria-hidden="true">
      <defs>
        <!-- Electric-blue microgravity flame: dense core, brighter rim, wide soft halo -->
        <radialGradient id="flHalo" cx="50%" cy="50%" r="50%">
          <stop offset="42%" stop-color="#0B3BFF" stop-opacity="0.9"/>
          <stop offset="62%" stop-color="#0A2FD0" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="#020A3A" stop-opacity="0"/>
        </radialGradient>
        <radialGradient id="flBody" cx="50%" cy="54%" r="52%">
          <stop offset="0%"  stop-color="#0A2FCF"/>
          <stop offset="58%" stop-color="#0B36E4"/>
          <stop offset="82%" stop-color="#1048F5"/>
          <stop offset="93%" stop-color="#2E7BFF"/>
          <stop offset="100%" stop-color="#4C9BFF" stop-opacity="0.7"/>
        </radialGradient>
        <filter id="flSoft" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="0.55"/>
        </filter>
        <filter id="flEyeGlow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="1.6" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <circle class="fl-glow" cx="38" cy="38" r="37" fill="url(#flHalo)"/>
      <circle class="fl-shell" cx="38" cy="38" r="21.5" fill="url(#flBody)" filter="url(#flSoft)"/>
      <g class="fl-look">
        <g class="fl-eyes" filter="url(#flEyeGlow)">
          <ellipse cx="31.2" cy="37" rx="4.6" ry="7.6" fill="#FFFFFF"/>
          <ellipse cx="44.8" cy="37" rx="4.6" ry="7.6" fill="#FFFFFF"/>
        </g>
      </g>
    </svg>
  </button>
</div>

{FLAMMY_ENGINE_JS}
<script>
(function() {{

  const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // =========================================================================
  // FLAMMY SENTINEL CLIENT (Steps 4 & 5: Non-blocking SSE + HTTP Bridge)
  // =========================================================================
  const SIGNAL_PALETTE = {{
    blue:  {{ main: "#6FA3D8", core: "#E8F1FA", edge: "#2F63B0", bg: "rgba(18, 48, 110, 0.55)", text: "#07080A" }},
    amber: {{ main: "#FF8A2A", core: "#FFC27A", edge: "#8C2A08", bg: "rgba(140, 42, 8, 0.45)",  text: "#07080A" }},
    red:   {{ main: "#F2600F", core: "#FFC27A", edge: "#8C2A08", bg: "rgba(140, 42, 8, 0.68)",  text: "#F4F3EF" }},
  }};

  function mapMaterialForFlammy(matName) {{
    const low = (matName || "").toLowerCase();
    if (low.includes("cotton") || low.includes("nomex") || low.includes("fabric")) return ["fabric", matName];
    if (low.includes("webbing") || low.includes("kevlar")) return ["webbing", matName];
    return ["polymer", matName];
  }}

  function formatAdvisoryHTML(a) {{
    if (!a) return "";
    const sig = (a.signal || "blue").toLowerCase();
    const pal = SIGNAL_PALETTE[sig] || SIGNAL_PALETTE.blue;
    const assumedBadge = a.assumed_gravity
      ? `<span style="font-family:var(--font-ui);font-size:10.5px;color:#BCD6EE;opacity:0.82;margin-left:8px;">[Assumed gravity: ${{(a.context && a.context.gravity) || 'micro'}}]</span>`
      : "";
    const expHeader = a.experiment
      ? `<div style="margin-bottom:6px;color:#E8F1FA;font-family:var(--font-ui);font-size:11.5px;"><b>EXPERIMENT:</b> ${{a.experiment.name}} — ${{a.experiment.note}}</div>`
      : "";
    const actionsList = (a.actions || []).slice(0, 4).map((act) => `<li style="margin-left:16px;margin-bottom:2px;">${{act}}</li>`).join("");
    const fireSteps = (a.if_fire && a.if_fire.steps ? a.if_fire.steps : []).slice(0, 4).map((st) => `<li style="margin-left:16px;margin-bottom:2px;">${{st}}</li>`).join("");
    const classNotes = (a.if_fire && a.if_fire.class_notes && a.if_fire.class_notes.length)
      ? `<div style="margin-top:4px;font-size:12px;color:#FFC27A;">${{a.if_fire.class_notes.join(" ")}}</div>`
      : "";
    const srcBtn = (lib, label) =>
      `<button type="button" class="flama-src" data-lib="${{lib}}" style="all:unset;cursor:pointer;color:#6FA3D8;text-decoration:underline;margin-right:10px;font-family:var(--font-ui);font-size:11px;">${{label}}</button>`;
    const sourcesLinks = (a.sources || []).map((s) =>
      (s.lib ? srcBtn(s.lib, `[${{s.name}}]`) : `<span style="margin-right:10px;font-size:11px;">[${{s.name}}]</span>`) +
      (s.tables || []).map((t, i) => srcBtn(t, (s.tables.length > 1 ? `table ${{i + 1}}` : "table"))).join("")
    ).join(" ");

    return `
      ${{expHeader}}
      <div style="margin-bottom:6px;">
        <b style="color:${{pal.main}};font-family:var(--font-ui);">[${{sig.toUpperCase()}} · ${{(a.level || 'info').toUpperCase()}}] ${{a.headline}}</b>${{assumedBadge}}
        <div style="margin-top:2px;color:#F4F3EF;">${{a.summary}}</div>
      </div>
      ${{actionsList ? `<div style="margin-bottom:6px;"><b style="color:#BCD6EE;font-family:var(--font-ui);font-size:11px;">RECOMMENDED ACTIONS:</b><ul style="margin-top:3px;">${{actionsList}}</ul></div>` : ""}}
      ${{fireSteps ? `<div style="margin-bottom:6px;"><b style="color:#FFC27A;font-family:var(--font-ui);font-size:11px;">IF FIRE (${{(a.if_fire && a.if_fire.label) || ''}}):</b><ul style="margin-top:3px;">${{fireSteps}}</ul>${{classNotes}}</div>` : ""}}
      ${{sourcesLinks ? `<div style="margin-top:6px;">${{sourcesLinks}}</div>` : ""}}
      <div style="margin-top:6px;font-size:11px;color:#7D828C;font-style:italic;">${{a.disclaimer || ""}}</div>
    `;
  }}

  function applyFlammyAdvisoryToUI(a, options = {{}}) {{
    if (!a) return;
    if (a.repeat && !options.forceShow) return;

    const sig = (a.signal || "blue").toLowerCase();
    const pal = SIGNAL_PALETTE[sig] || SIGNAL_PALETTE.blue;

    // 1) Update Top-Left Flame Sphere & Simulation Bubble ring color
    const stopCore = document.getElementById("flammy-stop-core");
    const stopMid  = document.getElementById("flammy-stop-mid");
    const stopEdge = document.getElementById("flammy-stop-edge");
    const logoRing = document.getElementById("flammy-logo-ring");
    const logoBtn  = document.getElementById("flama-logo-home");
    const simOrb   = document.getElementById("orb-simulations");

    if (stopCore) stopCore.setAttribute("stop-color", pal.core);
    if (stopMid)  stopMid.setAttribute("stop-color", pal.main);
    if (stopEdge) stopEdge.setAttribute("stop-color", pal.edge);
    if (logoRing) logoRing.setAttribute("stroke", pal.main);
    if (logoBtn)  logoBtn.style.borderColor = pal.main;
    if (simOrb)   simOrb.style.borderColor  = pal.main;
    document.querySelectorAll(".flammy-petal").forEach((p) => p.setAttribute("stroke", pal.main));

    // 2) Update Simulation Workspace Flammy row
    const simRow  = document.getElementById("flammy-sim-row");
    const simTag  = document.getElementById("flammy-sim-tag");
    const simBody = document.getElementById("flammy-sim-body");
    if (simRow && simTag && simBody) {{
      simRow.style.display = "flex";
      simTag.style.background = pal.main;
      simTag.style.color = pal.text;
      simTag.textContent = `FLAMMY · ${{sig.toUpperCase()}}`;
      simBody.innerHTML = formatAdvisoryHTML(a);
    }}

    // 3) If event came from Question or Experiment, also show in Command Drawer / Experiment Box
    if (a.event_type === "question" || options.openDrawer) {{
      const drawer = document.getElementById("hub-cmd-drawer");
      const output = document.getElementById("hub-cmd-output");
      const status = document.getElementById("hub-cmd-status");
      if (drawer && output && status) {{
        status.textContent = `FLAMMY SENTINEL // SIGNAL: ${{sig.toUpperCase()}} (${{(a.level || '').toUpperCase()}})`;
        status.style.color = pal.main;
        drawer.style.borderLeftColor = pal.main;
        output.innerHTML = formatAdvisoryHTML(a);
        drawer.classList.add("open");
      }}
    }}
    if (a.event_type === "experiment") {{
      const expBox = document.getElementById("flammy-exp-advisory-box");
      if (expBox) {{
        expBox.style.display = "block";
        expBox.style.borderLeft = `4px solid ${{pal.main}}`;
        expBox.innerHTML = formatAdvisoryHTML(a);
      }}
    }}
    syncIframeHeight();
    if (window.flammyBuddy) window.flammyBuddy.onAdvisory(a, options);
  }}

  window.flamaPostFlammy = (payload, options) => postFlammyEvent(payload, options || {{}});
  // Flammy runs in the browser (flammy_engine.js): works on any host, no local port or mixed content.
  function postFlammyEvent(payload, options = {{}}) {{
    try {{
      if (!window.FlammyEngine) return;
      const a = window.FlammyEngine.observe(payload);
      if (a) applyFlammyAdvisoryToUI(a, options);
    }} catch (err) {{
      console.warn("Flammy engine error", err);
    }}
  }}

  // =========================================================================
  // 2. DISCREET LOW-OPACITY RIPPLE EFFECT FROM EXACT CLICK POINT
  // =========================================================================
  function createDiscreetRipple(e, targetEl) {{
    if (prefersReducedMotion) return;
    const rect = targetEl.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const x = (e.clientX || (rect.left + rect.width / 2)) - rect.left - size / 2;
    const y = (e.clientY || (rect.top  + rect.height / 2)) - rect.top  - size / 2;

    const ripple = document.createElement("span");
    ripple.className = "click-ripple";
    ripple.style.width  = `${{size}}px`;
    ripple.style.height = `${{size}}px`;
    ripple.style.left   = `${{x}}px`;
    ripple.style.top    = `${{y}}px`;
    targetEl.appendChild(ripple);
    setTimeout(() => ripple.remove(), 540);
  }}

  document.querySelectorAll("button, .floating-orb").forEach((el) => {{
    el.addEventListener("pointerdown", (e) => createDiscreetRipple(e, el));
  }});

  // =========================================================================
  // 4. INTERSECTION OBSERVER FOR SCROLL / VIEW REVEALS
  // =========================================================================
  const revealObserver = ("IntersectionObserver" in window)
    ? new IntersectionObserver((entries) => {{
        entries.forEach((entry) => {{
          if (entry.isIntersecting) {{
            entry.target.classList.add("is-visible");
          }}
        }});
      }}, {{ threshold: 0.12 }})
    : null;

  document.querySelectorAll(".reveal-on-scroll").forEach((el) => {{
    if (revealObserver) revealObserver.observe(el);
    else el.classList.add("is-visible");
  }});

  // =========================================================================
  // 3. FLIP IMMERSIVE BUBBLE ZOOM ENGINE (Smooth 580ms, Zero Bounce)
  // =========================================================================
  const zoomPortal = document.getElementById("bubble-zoom-portal");
  const topNavBar  = document.getElementById("top-nav-bar");
  const views = {{
    cover:          document.getElementById("view-cover"),
    hub:            document.getElementById("view-hub"),
    investigations: document.getElementById("view-investigations"),
    mechanisms:     document.getElementById("view-mechanisms"),
    simulations:    document.getElementById("view-simulations"),
    relations:      document.getElementById("view-relations"),
  }};
  const menuBtns = {{
    hub:            document.getElementById("menu-btn-hub"),
    investigations: document.getElementById("menu-btn-investigations"),
    mechanisms:     document.getElementById("menu-btn-mechanisms"),
    simulations:    document.getElementById("menu-btn-simulations"),
    relations:      document.getElementById("menu-btn-relations"),
  }};

  let activeViewKey   = "cover";
  let lastOpenedOrbId = "orb-simulations";
  let isTransitioning = false;

  function triggerHubLoadEntrance() {{
    const slots = document.querySelectorAll(".orb-slot");
    slots.forEach((s) => {{
      s.classList.remove("entered");
      void s.offsetWidth;
      s.classList.add("entered");
    }});
  }}

  function triggerStaggerChildren(viewEl) {{
    if (!viewEl) return;
    viewEl.querySelectorAll(".stagger-item").forEach((item, idx) => {{
      item.classList.remove("stagger-in");
      item.style.setProperty("--stagger-idx", idx);
      void item.offsetWidth;
      item.classList.add("stagger-in");
    }});
    viewEl.querySelectorAll(".reveal-on-scroll").forEach((el) => el.classList.add("is-visible"));
  }}

  function activateViewDOM(target) {{
    Object.keys(views).forEach((k) => {{
      views[k].classList.toggle("active", k === target);
      views[k].classList.remove("zoom-blur-out");
    }});
    Object.keys(menuBtns).forEach((k) => {{
      menuBtns[k].classList.toggle("active", k === target);
    }});
    topNavBar.classList.toggle("visible", target !== "cover");
    document.body.style.background = target === "cover" ? "#000000" : "#07080A";
    activeViewKey = target;

    if (target === "hub") {{
      triggerHubLoadEntrance();
    }} else if (target !== "cover") {{
      triggerStaggerChildren(views[target]);
    }}
    setTimeout(syncIframeHeight, 40);
    setTimeout(syncIframeHeight, 300);
    if (window.flammyBuddy) window.flammyBuddy.onView(target);
  }}

  function zoomIntoBubble(orbEl, targetViewKey) {{
    if (isTransitioning) return;
    lastOpenedOrbId = orbEl.id;

    if (prefersReducedMotion || !zoomPortal || !zoomPortal.animate) {{
      activateViewDOM(targetViewKey);
      return;
    }}

    isTransitioning = true; clearTimeout(window.__flamaTw); window.__flamaTw = setTimeout(() => {{ isTransitioning = false; }}, 1600);  // never lock navigation if an animation is paused (hidden tab)
    const rect = orbEl.getBoundingClientRect();
    const cx   = rect.left + rect.width / 2;
    const cy   = rect.top  + rect.height / 2;
    const maxDim = Math.hypot(window.innerWidth, window.innerHeight) * 1.40;
    const scaleTarget = Math.max(12, maxDim / Math.max(rect.width, 1));

    zoomPortal.style.width  = `${{rect.width}}px`;
    zoomPortal.style.height = `${{rect.height}}px`;
    zoomPortal.style.left   = `${{cx - rect.width / 2}}px`;
    zoomPortal.style.top    = `${{cy - rect.height / 2}}px`;
    zoomPortal.style.opacity = "1";

    views.hub.classList.add("zoom-blur-out");

    const portalAnim = zoomPortal.animate([
      {{ transform: "scale(1)", opacity: 0.96 }},
      {{ transform: `scale(${{(scaleTarget * 0.58).toFixed(1)}})`, opacity: 0.94, offset: 0.62 }},
      {{ transform: `scale(${{scaleTarget.toFixed(1)}})`, opacity: 0 }}
    ], {{
      duration: 580,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
      fill: "forwards"
    }});

    setTimeout(() => {{
      activateViewDOM(targetViewKey);
    }}, 250);

    portalAnim.onfinish = () => {{
      zoomPortal.style.opacity = "0";
      zoomPortal.style.transform = "scale(0)";
      isTransitioning = false;
    }};
  }}

  function zoomOutToHub() {{
    if (isTransitioning) return;

    if (prefersReducedMotion || activeViewKey === "hub" || activeViewKey === "cover" || !zoomPortal || !zoomPortal.animate) {{
      activateViewDOM("hub");
      return;
    }}

    isTransitioning = true; clearTimeout(window.__flamaTw); window.__flamaTw = setTimeout(() => {{ isTransitioning = false; }}, 1600);  // never lock navigation if an animation is paused (hidden tab)
    const currentViewEl = views[activeViewKey];

    if (currentViewEl && currentViewEl.animate) {{
      currentViewEl.animate([
        {{ transform: "scale(1)", opacity: 1, filter: "blur(0px)" }},
        {{ transform: "scale(0.95)", opacity: 0, filter: "blur(6px)" }}
      ], {{
        duration: 240,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)"
      }});
    }}

    setTimeout(() => {{
      activateViewDOM("hub");
      const targetOrb = document.getElementById(lastOpenedOrbId);
      if (!targetOrb) {{
        isTransitioning = false;
        return;
      }}

      const rect = targetOrb.getBoundingClientRect();
      const cx   = rect.left + rect.width / 2;
      const cy   = rect.top  + rect.height / 2;
      const maxDim = Math.hypot(window.innerWidth, window.innerHeight) * 1.30;
      const startScale = Math.max(10, maxDim / Math.max(rect.width, 1));

      zoomPortal.style.width  = `${{rect.width}}px`;
      zoomPortal.style.height = `${{rect.height}}px`;
      zoomPortal.style.left   = `${{cx - rect.width / 2}}px`;
      zoomPortal.style.top    = `${{cy - rect.height / 2}}px`;
      zoomPortal.style.opacity = "1";

      const revAnim = zoomPortal.animate([
        {{ transform: `scale(${{startScale.toFixed(1)}})`, opacity: 0.55 }},
        {{ transform: "scale(1)", opacity: 0.85, offset: 0.82 }},
        {{ transform: "scale(1)", opacity: 0 }}
      ], {{
        duration: 540,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "forwards"
      }});

      revAnim.onfinish = () => {{
        zoomPortal.style.opacity = "0";
        isTransitioning = false;
      }};
    }}, 200);
  }}

  // =========================================================================
  // DUAL-VIDEO HARDWARE CROSSFADE ENGINE (Infinite Loop from t = 8.0s to End)
  // =========================================================================
  const vidA      = document.getElementById("flama-vid-a");
  const vidB      = document.getElementById("flama-vid-b");
  const fileInput = document.getElementById("custom-video-input");

  let crossfading = false;
  const TARGET_LOOP_START = 8.0;   // same loop as the team's cover (octamartinn/NASA-SPACE-APPS)
  const CROSSFADE_SEC     = 0.50;

  function getLoopStart(dur) {{
    if (!dur || isNaN(dur)) return TARGET_LOOP_START;
    return dur > TARGET_LOOP_START + 0.35 ? TARGET_LOOP_START : Math.max(0.0, dur * 0.55);
  }}

  // The background layer is parked at the loop start AHEAD of time; the crossfade only starts once that
  // layer can really play (decoded frame ready). Both layers share ONE in-memory copy of the file, so the
  // seeks are instant, like the old embedded video, but the page stays light and the browser caches it.
  const PREPARE_SEC = 1.2;
  const near = (v, t) => Math.abs(v.currentTime - t) < 0.06;
  function parkAt(v, t) {{ if (!near(v, t) && !v.seeking) v.currentTime = t; }}

  function monitorDualVideoLoop() {{
    checkLoop();
    requestAnimationFrame(monitorDualVideoLoop);
  }}
  setInterval(checkLoop, 100);   // animation frames are throttled when the window is not in front

  function checkLoop() {{
    // the visible layer is read from the screen itself, so no state variable can drift out of sync
    const fg = vidB.style.opacity === "1" ? vidB : vidA;
    const bg = fg === vidA ? vidB : vidA;

    if (fg && bg && fg.readyState >= 2 && fg.duration > 0) {{
      const dur = fg.duration;
      const loopStart = getLoopStart(dur);
      const triggerTime = Math.max(loopStart + 0.15, dur - CROSSFADE_SEC);

      if (!crossfading && fg.currentTime >= triggerTime - PREPARE_SEC) parkAt(bg, loopStart);
      const bgReady = bg.readyState >= 3 && !bg.seeking && near(bg, loopStart);
      if (!crossfading && fg.currentTime >= triggerTime && bgReady) {{
        crossfading = true;
        const swap = () => {{
          bg.style.opacity = "1";
          fg.style.opacity = "0";
          setTimeout(() => {{
            fg.pause();
            parkAt(fg, loopStart);
            crossfading = false;
          }}, CROSSFADE_SEC * 1000 + 40);
        }};
        // start the fade when the layer really plays, or after 150 ms at most (a play() promise can stay pending)
        let started = false;
        const go = () => {{ if (!started) {{ started = true; swap(); }} }};
        bg.addEventListener("playing", go, {{ once: true }});
        setTimeout(go, 150);
        bg.play().catch(() => {{}});
      }}
    }}
  }}

  function startVideos(url) {{
    crossfading = false;
    vidA.style.opacity = "1";
    vidB.style.opacity = "0";
    vidA.addEventListener("loadedmetadata", () => {{
      vidA.currentTime = 0.0;
      vidA.play().catch(() => {{}});
    }}, {{ once: true }});
    vidB.addEventListener("loadedmetadata", () => {{
      vidB.pause();
      vidB.currentTime = getLoopStart(vidB.duration);
    }}, {{ once: true }});
    vidA.src = url;
    vidB.src = url;
    vidA.play().catch(() => {{}});
  }}

  function initCoverVideos() {{
    const src = vidA && vidA.dataset.src;
    if (!src) return;
    // if the background layer was not ready when the clip ended, the visible one simply loops itself
    [vidA, vidB].forEach((v) => {{
      v.addEventListener("ended", () => {{
        if (v.style.opacity !== "1") {{ v.pause(); return; }}   // the fading-out layer just stops
        v.currentTime = getLoopStart(v.duration);
        v.play().catch(() => {{}});
      }});
    }});
    fetch(src).then((r) => {{ if (!r.ok) throw new Error(r.status); return r.blob(); }})
      .then((b) => startVideos(URL.createObjectURL(b)))
      .catch(() => startVideos(src));   // fallback: stream it directly
  }}

  initCoverVideos();
  requestAnimationFrame(monitorDualVideoLoop);

  if (fileInput) fileInput.addEventListener("change", (e) => {{
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    startVideos(URL.createObjectURL(file));
  }});

  // =========================================================================
  // NAVIGATION WIRING & EXPERIMENT OBSERVATION HOOKS (Step 3)
  // =========================================================================
  const hamToggle = document.getElementById("hamburger-toggle");
  const hamMenu   = document.getElementById("hamburger-menu");
  const logoHome  = document.getElementById("flama-logo-home");

  hamToggle.addEventListener("click", (e) => {{
    e.stopPropagation();
    hamMenu.classList.toggle("open");
  }});
  document.addEventListener("click", (e) => {{
    if (!hamMenu.contains(e.target) && e.target !== hamToggle) {{
      hamMenu.classList.remove("open");
    }}
  }});

  logoHome.addEventListener("click", () => {{
    document.getElementById("hub-cmd-drawer").classList.remove("open");
    zoomOutToHub();
  }});

  document.getElementById("si-enter-console-btn").addEventListener("click", () => {{
    activateViewDOM("hub");
  }});

  menuBtns.hub.addEventListener("click",            () => {{ hamMenu.classList.remove("open"); zoomOutToHub(); }});
  menuBtns.investigations.addEventListener("click", () => {{ hamMenu.classList.remove("open"); activateViewDOM("investigations"); }});
  menuBtns.mechanisms.addEventListener("click",     () => {{ hamMenu.classList.remove("open"); activateViewDOM("mechanisms"); }});
  menuBtns.simulations.addEventListener("click",    () => {{ hamMenu.classList.remove("open"); activateViewDOM("simulations"); }});
  menuBtns.relations.addEventListener("click",      () => {{ hamMenu.classList.remove("open"); activateViewDOM("relations"); }});
  document.getElementById("menu-btn-cover").addEventListener("click", () => {{
    hamMenu.classList.remove("open");
    activateViewDOM("cover");
  }});

  document.querySelectorAll(".btn-back-hub").forEach((btn) => {{
    btn.addEventListener("click", () => zoomOutToHub());
  }});

  document.querySelectorAll(".floating-orb").forEach((orb) => {{
    orb.addEventListener("click", () => {{
      const targetKey = orb.getAttribute("data-target");
      if (targetKey) zoomIntoBubble(orb, targetKey);
    }});
    orb.addEventListener("keydown", (e) => {{
      if (e.key === "Enter" || e.key === " ") {{
        e.preventDefault();
        const targetKey = orb.getAttribute("data-target");
        if (targetKey) zoomIntoBubble(orb, targetKey);
      }}
    }});
  }});

  // Hook: When the user opens an experiment (curated pill ids or any "psi-xx" id)
  document.querySelectorAll(".exp-observe-btn").forEach((btn) => {{
    btn.addEventListener("click", () => {{
      const expId = btn.getAttribute("data-exp");
      if (expId) {{
        if (window.flammyBuddy) window.flammyBuddy.inspect(btn, btn.textContent.trim());
        postFlammyEvent({{ type: "experiment", experiment: expId }}, {{ forceShow: true }});
      }}
    }});
  }});

  // =========================================================================
  // PSI INVESTIGATION BROWSER (Bubble 1): live filter + relevance vs the sim
  // =========================================================================
  const PSI_DB = {_PSI_DB_JSON};
  const psiList = document.getElementById("psi-card-list");
  if (psiList && Array.isArray(PSI_DB) && PSI_DB.length) {{
    const psiSearch = document.getElementById("psi-search");
    const psiSort   = document.getElementById("psi-sort");
    const psiCount  = document.getElementById("psi-count");
    let psiFuel = "all";
    let psiRankDebounce = null;

    function psiSimState() {{
      const o2El = document.getElementById("s3-o2"), gEl = document.getElementById("s3-g"), mEl = null;
      const o2 = o2El ? parseFloat(o2El.value) : 21.0;
      const g  = gEl ? parseFloat(gEl.value) : 0.0;
      const mat = ((mEl && mEl.value) || "").toLowerCase();
      const regime = g <= 0.02 ? "micro" : (g < 0.98 ? "partial" : "earth");
      return {{ o2: o2, g: g, mat: mat, regime: regime }};
    }}

    function psiScore(c, s) {{
      let sc = 0; const why = [];
      if (s.regime === "micro" && c.gravity === "micro") {{ sc += 2; why.push("0G DATA"); }}
      if (s.regime === "partial") {{
        if (c.partial_analog) {{ sc += 3; why.push("PARTIAL-G ANALOG"); }}
        else if (c.gravity === "micro") {{ sc += 1; why.push("0G BOUND"); }}
      }}
      if (s.regime === "earth" && c.gravity === "ground") {{ sc += 2; why.push("GROUND STUDY"); }}
      const fabricSel = s.mat.includes("cotton") || s.mat.includes("fabric") || s.mat.includes("nomex");
      const solidSel = fabricSel || ["pmma", "poly", "acrylic", "peek", "ptfe", "silicone", "kapton"].some((k) => s.mat.includes(k));
      if (fabricSel && c.mats.indexOf("fabric") >= 0) {{ sc += 3; why.push("FABRIC TESTED"); }}
      else if (solidSel && c.fuel === "solid") {{ sc += 2; why.push("SOLID FUEL"); }}
      if (s.o2 >= 30 && c.o2max && c.o2max >= s.o2) {{ sc += 2; why.push("UP TO " + c.o2max + "% O2"); }}
      if (c.flow) {{ sc += 1; why.push("FLOW STUDY"); }}
      sc += Math.min(c.tables, 3) * 0.2 + Math.min(c.rows / 500.0, 1) * 0.4;
      return {{ sc: sc, why: why }};
    }}

    function renderPsiCards() {{
      const s = psiSimState();
      const q = ((psiSearch && psiSearch.value) || "").toLowerCase().trim();
      const items = PSI_DB
        .filter((c) => (psiFuel === "all" || c.fuel === psiFuel) && (!q || c.kw.indexOf(q) >= 0))
        .map((c) => ({{ c: c, r: psiScore(c, s) }}));
      const mode = psiSort ? psiSort.value : "relevance";
      if (mode === "accession") items.sort((a, b) => a.c.num - b.c.num);
      else if (mode === "tables") items.sort((a, b) => (b.c.rows + b.c.tables * 50) - (a.c.rows + a.c.tables * 50));
      else items.sort((a, b) => (b.r.sc - a.r.sc) || (a.c.num - b.c.num));
      psiCount.textContent = items.length + " / " + PSI_DB.length + " INVESTIGATIONS · RANKED FOR " +
        s.regime.toUpperCase() + " · " + s.o2.toFixed(1) + "% O2 · " + (s.mat ? s.mat.toUpperCase() : "ANY MATERIAL");
      psiList.innerHTML = items.map((it) => {{
        const c = it.c, r = it.r;
        const badges = [
          '<span class="psi-badge psi-fuel-' + c.fuel + '">' + c.fuel.toUpperCase() + "</span>",
          (mode === "relevance" && r.sc > 0.9 ? '<span class="psi-badge psi-rel">MATCH ' + r.sc.toFixed(1) + "</span>" : ""),
          r.why.slice(0, 2).map((w) => '<span class="psi-badge">' + w + "</span>").join(""),
        ].join("");
        return '<div class="psi-card">' +
          '<div class="psi-card-top"><span class="psi-acc">' + c.acc + "</span>" + badges + "</div>" +
          '<div class="psi-name">' + (c.acr ? "<b>" + c.acr + "</b> — " : "") + c.name + "</div>" +
          '<div class="psi-blurb">' + c.blurb + "</div>" +
          '<div class="psi-meta"><span>' + (c.hardware || "—") + "</span>" +
          "<span>" + c.tables + (c.tables === 1 ? " TABLE" : " TABLES") + " · " + c.rows + " ROWS</span>" +
          (c.doi ? "<span>DOI " + c.doi + "</span>" : "") + "</div>" +
          '<div class="psi-meta"><button type="button" class="flama-src psi-lib" data-lib="' + c.lib + '">Open record</button>' +
          (c.table_libs || []).map((t, i) => '<button type="button" class="flama-src psi-lib" data-lib="' + t + '">' + ((c.table_libs.length > 1) ? "Table " + (i + 1) : "Open data table") + "</button>").join("") + "</div>" +
          '<div class="psi-actions"><button class="switch-bubble-btn press-able psi-observe" data-exp="' + c.id + '">INSPECT WITH FLAMMY →</button></div>' +
          "</div>";
      }}).join("");
      syncIframeHeight();
    }}

    psiList.addEventListener("click", (ev) => {{
      const btn = ev.target.closest(".psi-observe");
      if (!btn) return;
      if (window.flammyBuddy) {{
        const card = btn.closest(".psi-card"), acc = card && card.querySelector(".psi-acc");
        window.flammyBuddy.inspect(btn, acc ? acc.textContent : "this investigation");
      }}
      postFlammyEvent({{ type: "experiment", experiment: btn.getAttribute("data-exp") }}, {{ forceShow: true }});
    }});
    function libraryMode(on) {{
      psiList.hidden = on;
      document.getElementById("psi-chips").hidden = on;
      psiCount.hidden = on;
      if (psiSearch) psiSearch.placeholder = on ? "SEARCH DATABASE FILES — INVESTIGATION, TABLE, FILE NAME..." : "SEARCH PSI ARCHIVE — TITLE, HARDWARE, FUEL, DOI...";
      if (window.flamaLibrary) {{
        if (on) {{ window.flamaLibrary.filter(psiSearch ? psiSearch.value : ""); window.flamaLibrary.show(); }}
        else window.flamaLibrary.hide();
      }}
    }}
    window.flamaLibraryMode = (on) => {{ if (psiSort) psiSort.value = on ? "library" : "relevance"; libraryMode(on); }};
    if (psiSearch) psiSearch.addEventListener("input", () => {{
      if (psiSort && psiSort.value === "library") {{ if (window.flamaLibrary) window.flamaLibrary.filter(psiSearch.value); }}
      else renderPsiCards();
    }});
    if (psiSort) psiSort.addEventListener("change", () => {{
      const lib = psiSort.value === "library";
      libraryMode(lib);
      if (!lib) renderPsiCards();
    }});
    document.querySelectorAll(".psi-chip").forEach((ch) => ch.addEventListener("click", () => {{
      psiFuel = ch.getAttribute("data-fuel");
      document.querySelectorAll(".psi-chip").forEach((x) => x.classList.toggle("active", x === ch));
      renderPsiCards();
    }}));
    window.addEventListener("flama:sim-atmosphere", () => {{
      if (psiRankDebounce) clearTimeout(psiRankDebounce);
      psiRankDebounce = setTimeout(() => {{ if (!psiSort || psiSort.value !== "library") renderPsiCards(); }}, 180);
    }});
    ["s3-o2", "s3-g"].forEach((id) => {{
      const el = document.getElementById(id);
      if (el) el.addEventListener(id === "mc-material" ? "change" : "input", () => {{
        if (psiRankDebounce) clearTimeout(psiRankDebounce);
        psiRankDebounce = setTimeout(renderPsiCards, 180);
      }});
    }});
    renderPsiCards();
  }}

  // =========================================================================
  // COMMAND BAR & VOICE RECORDING ENGINE (Hooked to Flammy Question / Experiment)
  // =========================================================================
  const cmdInput  = document.getElementById("hub-cmd-input");
  const voiceBtn  = document.getElementById("hub-voice-btn");
  const cmdDrawer = document.getElementById("hub-cmd-drawer");
  const cmdOutput = document.getElementById("hub-cmd-output");
  const cmdClose  = document.getElementById("hub-cmd-close");

  function executeCommandQuery(rawQuery) {{
    const q = (rawQuery || "").trim();
    if (!q) return;
    const ql = q.toLowerCase();

    const expMatch = ql.match(/^\\/?(fm2|luci|sofie|flare|saffire|cir)$/);
    if (expMatch) {{
      postFlammyEvent({{ type: "experiment", experiment: expMatch[1] }}, {{ openDrawer: true, forceShow: true }});
      return;
    }}

    if (ql === "/investigations") {{ zoomIntoBubble(document.getElementById("orb-investigations"), "investigations"); return; }}
    if (ql === "/mechanisms")     {{ zoomIntoBubble(document.getElementById("orb-mechanisms"), "mechanisms"); return; }}
    if (ql === "/simulations")    {{ zoomIntoBubble(document.getElementById("orb-simulations"), "simulations"); return; }}
    if (ql === "/relations")      {{ zoomIntoBubble(document.getElementById("orb-relations"), "relations"); return; }}

    // Free text = an operational scenario for the AI (voz/ + citations). The AI relates it to the
    // closest PSI investigation; Flammy reviews the question + answer when the turn completes.
    cmdInput.value = "";
    if (window.flamaChat) {{
      window.flamaChat.preguntar(q);
    }} else {{
      postFlammyEvent({{ type: "question", question: q, answer: "" }}, {{ forceShow: true }});
    }}
  }}

  cmdInput.addEventListener("keydown", (e) => {{
    if (e.key === "Enter") {{
      e.preventDefault();
      executeCommandQuery(cmdInput.value);
    }}
  }});
  cmdClose.addEventListener("click", () => {{
    cmdDrawer.classList.remove("open");
    syncIframeHeight();
  }});

  voiceBtn.addEventListener("click", () => {{
    if (window.flamaChat) window.flamaChat.alternarMicro();
  }});

  // Flammy keeps its recommendations: every scenario (typed or spoken) + the AI answer
  window.addEventListener("flama:pregunta", (e) => {{
    const d = e.detail || {{}};
    postFlammyEvent({{ type: "question", question: d.pregunta || "", answer: d.respuesta || "" }}, {{ forceShow: true }});
  }});
  // Any internal source button (Flammy advisories, PSI cards...) opens that database file in the library
  document.addEventListener("click", (e) => {{
    const b = e.target.closest(".flama-src[data-lib]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    window.dispatchEvent(new CustomEvent("flama:abrir-archivo", {{ detail: {{ archivo: b.dataset.lib }} }}));
  }}, true);

  // AI citation -> preview the exact database file in the library (Bubble 1)
  window.addEventListener("flama:abrir-archivo", (e) => {{
    const d = e.detail || {{}};
    if (!d.archivo) return;
    activateViewDOM("investigations");
    const box = document.getElementById("psi-search");
    if (box) box.value = "";
    if (window.flamaLibraryMode) window.flamaLibraryMode(true);
    if (window.flamaLibrary) {{
      window.flamaLibrary.open(d.archivo, {{ columns: d.columnas || [], excerpt: d.extracto || "" }}).then(() => {{
        const v = document.getElementById("lib-view");
        if (v && window.flammyBuddy) window.flammyBuddy.scrollParentTo(v, 16);
      }});
    }}
  }});
  // "Open in the PSI archive" from a citation chip
  window.addEventListener("flama:abrir-psi", (e) => {{
    const acc = ((e.detail || {{}}).accesion || "").trim();
    activateViewDOM("investigations");
    const box = document.getElementById("psi-search");
    if (box && acc) {{
      box.value = acc;
      box.dispatchEvent(new Event("input"));
      setTimeout(() => {{
        const card = [...document.querySelectorAll(".psi-card")].find((c) => (c.querySelector(".psi-acc") || {{}}).textContent === acc);
        if (card && window.flammyBuddy) {{ window.flammyBuddy.scrollParentTo(card, 24); }}
      }}, 120);
    }}
  }});

  // Iframe auto-height (used by every bubble)
  function setAppVh() {{
    let h = window.innerHeight;
    try {{ h = window.parent.innerHeight || h; }} catch (e) {{}}
    document.documentElement.style.setProperty("--app-vh", h + "px");
  }}
  setAppVh();
  try {{
    window.parent.addEventListener("resize", setAppVh);
    // Streamlit replaces this iframe on reload: drop the listener so the parent keeps no dead callbacks
    window.addEventListener("pagehide", () => {{ try {{ window.parent.removeEventListener("resize", setAppVh); }} catch (e) {{}} }});
  }} catch (e) {{}}
  function syncIframeHeight() {{
    if (window.frameElement) {{
      const h = document.body.scrollHeight;
      if (h > 200) window.frameElement.style.height = (h + 20) + "px";
    }}
  }}

  window.addEventListener("resize", syncIframeHeight);
  if (window.ResizeObserver) {{
    // Deferred to the next frame: resizing the iframe inside the observer callback re-triggered it
    let resizeQueued = false;
    new ResizeObserver(() => {{
      if (resizeQueued) return;
      resizeQueued = true;
      requestAnimationFrame(() => {{ resizeQueued = false; syncIframeHeight(); }});
    }}).observe(document.body);
  }}
  syncIframeHeight();
}})();

  // =========================================================================
  // FLAMMY COMPANION — follows the visitor, speaks tips and exact advisories
  // =========================================================================
  window.flammyBuddy = (function () {{
    const root   = document.getElementById("flammy-buddy");
    const body   = document.getElementById("flammy-buddy-body");
    const bubble = document.getElementById("flammy-bubble");
    const lvlEl  = bubble.querySelector(".fb-level");
    const content = bubble.querySelector(".fb-content");
    const look = root.querySelector(".fl-look");
    const SIZE = 76, PAD = 22;
    const VIEW_TIPS = {{
      hub: ["Command hub", "Pick a bubble to start. I'll follow you around and flag any fire risk I spot."],
      investigations: ["PSI archive", "All 24 PSI investigations, ranked against the atmosphere set in the 3D simulator. Hit Inspect with Flammy on any card and I'll brief you."],
      mechanisms: ["Safety mechanisms", "Six PSI studies ranked by how directly they prevent, detect or suppress a fire. Open a card for its evidence and FLAMA Score."],
      simulations: ["3D cabin simulator", "Pick a habitat or move the sliders: I re-check the atmosphere each time you settle, and again when you ignite."],
      relations: ["Theory Lab", "Hypotheses the AI found across the PSI archive, each backed by 10+ investigations quoted word for word. Open one to see the evidence for and against."],
    }};
    let anchorEl = null, hideTimer = null, rafPending = false, lastMsg = null, lastSimSignal = null;
    const seenViews = new Set();
    const reduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

    function parentScroller() {{
      try {{
        const pd = window.parent && window.parent.document;
        return (pd && (pd.querySelector('[data-testid="stMain"]') || pd.scrollingElement)) || null;
      }} catch (e) {{ return null; }}
    }}

    // Visible slice of this (non-scrolling, auto-height) iframe, in its own document coordinates.
    function visibleBand() {{
      const docH = document.documentElement.scrollHeight;
      try {{
        if (window.frameElement) {{
          const r = window.frameElement.getBoundingClientRect();
          const vh = window.parent.innerHeight;
          const top = Math.max(0, -r.top);
          return {{ top: top, bottom: Math.min(docH, Math.max(top + 200, vh - r.top)) }};
        }}
      }} catch (e) {{}}
      return {{ top: window.scrollY, bottom: window.scrollY + window.innerHeight }};
    }}

    function place(x, y) {{
      const w = document.documentElement.clientWidth;
      x = Math.max(8, Math.min(x, w - SIZE - 8));
      const bw = bubble.offsetWidth || 260;
      const fitsR = x + 70 + bw <= w - 8, fitsL = x + 6 - bw >= 8;
      const lado = x < 340 ? (fitsR ? "r" : fitsL ? "l" : "c") : (fitsL ? "l" : fitsR ? "r" : "c");
      root.classList.toggle("bubble-right", lado === "r");
      bubble.style.left = lado === "c" ? (Math.max(8, Math.min(x + SIZE / 2 - bw / 2, w - bw - 8)) - x) + "px" : "";
      bubble.style.right = lado === "c" ? "auto" : "";
      root.style.transform = `translate3d(${{Math.round(x)}}px, ${{Math.round(y)}}px, 0)`;
    }}

    function reposition() {{
      rafPending = false;
      if (!root.classList.contains("on")) return;
      const band = visibleBand();
      const w = document.documentElement.clientWidth;
      // Keep the speech bubble (drawn above Flammy) inside the visible slice.
      const minTop = band.top + Math.max(12, (bubble.classList.contains("show") ? bubble.offsetHeight : 0) - 46);
      if (anchorEl && anchorEl.offsetParent !== null) {{
        const r = anchorEl.getBoundingClientRect();
        const inView = r.bottom > band.top + 40 && r.top < band.bottom - 40;
        if (inView) {{
          const y = Math.min(Math.max(r.top - SIZE * 0.35, minTop), band.bottom - SIZE - 12);
          place(r.right - SIZE * 0.55, y);
          return;
        }}
      }}
      place(w - SIZE - PAD, band.bottom - SIZE - PAD);
    }}
    function schedule() {{ if (!rafPending) {{ rafPending = true; requestAnimationFrame(reposition); }} }}

    function fly(el) {{
      anchorEl = el || null;
      root.classList.add("flying");
      setTimeout(() => root.classList.remove("flying"), 760);
      schedule();
    }}

    function esc(t) {{ const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }}

    function show(html, level, signal, ms) {{
      lvlEl.textContent = level || "";
      lvlEl.className = "fb-level" + (signal && signal !== "blue" ? " " + signal : "");
      bubble.style.borderColor = signal === "red" ? "#8C2A08" : signal === "amber" ? "#7A4A1F" : "var(--space-700)";
      content.innerHTML = html;
      bubble.classList.add("show");
      schedule();
      clearTimeout(hideTimer);
      if (ms) hideTimer = setTimeout(hide, ms);
    }}
    function hide() {{ bubble.classList.remove("show"); clearTimeout(hideTimer); }}

    function tip(title, text, ms) {{
      lastMsg = {{ html: `<div class="fb-title">${{esc(title)}}</div><div class="fb-text">${{esc(text)}}</div>`, level: "", signal: "blue" }};
      show(lastMsg.html, "", "blue", ms || 7000);
    }}

    function advisoryHTML(a) {{
      const exp = a.experiment ? `<div class="fb-text" style="margin-bottom:4px;">${{esc(a.experiment.name)}}</div>` : "";
      const act = (a.actions && a.actions[0]) ? `<div class="fb-action"><b>Do this:</b> ${{esc(a.actions[0])}}</div>` : "";
      return `${{exp}}<div class="fb-title">${{esc(a.headline)}}</div><div class="fb-text">${{esc(a.summary)}}</div>${{act}}`;
    }}

    function onAdvisory(a, options) {{
      if (!a || !root.classList.contains("on")) return;
      const sig = (a.signal || "blue").toLowerCase();
      const level = (a.level || "info");
      const html = advisoryHTML(a);
      if (a.event_type === "experiment") {{
        lastMsg = {{ html, level, signal: sig }};
        fly(document.getElementById("flammy-exp-advisory-box"));
        setTimeout(() => show(html, level, sig, 16000), reduced ? 0 : 520);
      }} else if (a.event_type === "simulation") {{
        if (!(options && options.forceShow) && sig === lastSimSignal) return;
        lastSimSignal = sig;
        lastMsg = {{ html, level, signal: sig }};
        const row = document.getElementById("flammy-sim-row");
        fly(row && row.offsetParent !== null ? row : null);
        setTimeout(() => show(html, level, sig, 11000), reduced ? 0 : 520);
      }} else {{
        lastMsg = {{ html, level, signal: sig }};
        fly(null);
        show(html, level, sig, 11000);
      }}
    }}

    function inspect(btn, label) {{
      // 1) Bring the top of the bubble into view so the briefing reads without scrolling back.
      const card = btn.closest(".workspace-card") || document.getElementById("view-investigations");
      scrollParentTo(card, 12);
      // 2) Fly to where the briefing will appear and show a thinking state.
      fly(document.getElementById("flammy-exp-advisory-box").style.display === "none"
          ? card.querySelector(".exp-pills-row") || card
          : document.getElementById("flammy-exp-advisory-box"));
      show(`<div class="fb-text">Reading ${{esc(label)}}&nbsp;</div><div class="fb-dots" aria-hidden="true"><span></span><span></span><span></span></div>`, "", "blue", 0);
    }}

    function onView(target) {{
      if (target === "cover") {{ root.classList.remove("on"); hide(); return; }}
      root.classList.add("on");
      anchorEl = null; hide(); schedule();
      if (!seenViews.has(target) && VIEW_TIPS[target]) {{
        seenViews.add(target);
        setTimeout(() => tip(VIEW_TIPS[target][0], VIEW_TIPS[target][1]), reduced ? 0 : 650);
      }}
    }}

    function scrollParentTo(el, offset) {{
      if (!el) return;
      const sc = parentScroller();
      try {{
        if (sc && window.frameElement) {{
          const delta = window.frameElement.getBoundingClientRect().top + el.getBoundingClientRect().top - (offset || 0);
          const target = Math.max(0, Math.min(sc.scrollTop + delta, sc.scrollHeight - sc.clientHeight));
          sc.scrollTo({{ top: target, behavior: reduced ? "auto" : "smooth" }});
          // Smooth scrolling can stall (background tab, competing layout); guarantee arrival.
          setTimeout(() => {{ if (Math.abs(sc.scrollTop - target) > 4) sc.scrollTo({{ top: target, behavior: "auto" }}); schedule(); }}, 1100);
          return;
        }}
      }} catch (e) {{}}
      el.scrollIntoView({{ behavior: reduced ? "auto" : "smooth", block: "start" }});
    }}

    // Eyes follow the pointer.
    document.addEventListener("mousemove", (e) => {{
      if (!root.classList.contains("on") || reduced) return;
      const r = body.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
      const d = Math.hypot(dx, dy) || 1, k = Math.min(1, d / 220) * 2.6;
      look.style.transform = `translate(${{(dx / d * k).toFixed(2)}}px, ${{(dy / d * k).toFixed(2)}}px)`;
    }}, {{ passive: true }});

    body.addEventListener("click", () => {{
      if (bubble.classList.contains("show")) {{ hide(); return; }}
      if (lastMsg) show(lastMsg.html, lastMsg.level, lastMsg.signal, 12000);
      else tip("Flammy", "I watch your simulations and experiments and warn you about fire risk.");
    }});
    bubble.querySelector(".fb-close").addEventListener("click", hide);
    bubble.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    bubble.addEventListener("mouseleave", () => {{ if (bubble.classList.contains("show")) hideTimer = setTimeout(hide, 6000); }});
    document.addEventListener("keydown", (e) => {{ if (e.key === "Escape") hide(); }});

    const sc = parentScroller();
    if (sc) {{
      sc.addEventListener("scroll", schedule, {{ passive: true }});
      window.addEventListener("pagehide", () => {{ try {{ sc.removeEventListener("scroll", schedule); }} catch (e) {{}} }});
    }}
    try {{
      window.parent.addEventListener("resize", schedule, {{ passive: true }});
      window.addEventListener("pagehide", () => {{ try {{ window.parent.removeEventListener("resize", schedule); }} catch (e) {{}} }});
    }} catch (e) {{}}
    window.addEventListener("resize", schedule, {{ passive: true }});
    if (window.ResizeObserver) new ResizeObserver(schedule).observe(document.body);

    return {{ onAdvisory, onView, inspect, scrollParentTo, tip, hide }};
  }})();
  if (typeof activeViewKey !== "undefined" && activeViewKey) window.flammyBuddy.onView(activeViewKey);
</script>
{IA_CHAT_JS}
{LIB_JS}
{SAFETY_JS}
{THEORY_JS}
</body>
</html>"""
    components.html(html_doc, height=820, scrolling=False)
