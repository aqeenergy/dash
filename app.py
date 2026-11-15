"""FLAMA — Flame in Freefall (Entry point).

Run: .venv\\Scripts\\python.exe -m streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from ui_components import render_live_mission_control

st.set_page_config(
    page_title="FLAMA — Flame in Freefall",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """<style>
    header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], #MainMenu, footer, .stDeployButton {
        display: none !important;
        height: 0px !important;
    }
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        padding-left: 0rem !important;
        padding-right: 0rem !important;
        max-width: 100% !important;
    }
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #07080A !important;
        color: #F4F3EF !important;
        overflow-x: hidden;
    }
    </style>""",
    unsafe_allow_html=True,
)

render_live_mission_control()