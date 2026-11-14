"""chat_module.py — NotebookLM-style scenario chat & predictive analyzer for Artemis-SI."""

from __future__ import annotations

from typing import Iterable

import streamlit as st

import predictive_engine
from ui_components import PALETTE, read_environment

ENGINE_LABEL: str = predictive_engine.ENGINE_LABEL
ENGINE_IS_LLM: bool = predictive_engine.ENGINE_IS_LLM

_HISTORY_KEY = "chat_history"

QUICK_SCENARIOS = [
    "Short-circuit on a polyethylene wiring panel near an active 10 cm/s HVAC ventilation duct in a lunar rover.",
    "Overheating lithium-ion battery harness insulated with Nomex during pre-EVA oxygen enrichment.",
    "Liquid fuel droplet leak inside the Combustion Integrated Rack — evaluate CO2 vs. Fine Water Mist suppression.",
    "Evaluate partial-gravity flame spread risk and 3-year material degradation for a lunar habitat airlock.",
]


def _env_line(env: dict) -> str:
    return (
        f"G {env['gravity_g']:.2f} g · O2 {env['o2_pct']:.1f} % · P {env['pressure_kpa']:.1f} kPa "
        f"· {env['material'].upper()} · RISK {env['risk_level'].upper()}"
    )


def _environment_strip() -> None:
    env = read_environment()
    if env:
        st.markdown(
            '<div style="margin-bottom:10px;">'
            '<span class="asi-chip">ACTIVE TELEMETRY</span>'
            f'<span class="asi-chip">G {env["gravity_g"]:.2f} g</span>'
            f'<span class="asi-chip">O2 {env["o2_pct"]:.1f} %</span>'
            f'<span class="asi-chip">P {env["pressure_kpa"]:.1f} kPa</span>'
            f'<span class="asi-chip">{env["material"].upper()}</span>'
            f'<span class="asi-chip warn">RISK {env["risk_level"].upper()}</span>'
            "</div>",
            unsafe_allow_html=True,
        )


def _as_chunks(result: str | Iterable[str]) -> Iterable[str]:
    return [result] if isinstance(result, str) else result


def _render_citations_expander(passages: list[dict]) -> None:
    if not passages:
        return
    p = PALETTE
    with st.expander(f"📚 View Retrieved NASA PSI Evidence Passages ({len(passages)} sources cited)"):
        for ch in passages:
            st.markdown(
                f'<div style="border-left:3px solid {p["accent"]};padding:6px 12px;margin:6px 0;background:{p["panel"]};border-radius:4px;">'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:12px;font-weight:600;color:{p["accent"]};">'
                f'[{ch["chunk_id"]}] {ch["experiment"]} — {ch["title"]} '
                f'<span style="color:{p["muted"]};font-weight:400;">({ch["gravity_tag"]} · {ch["o2_range"]})</span></div>'
                f'<div style="font-size:13px;color:{p["ink"]};margin-top:4px;">{ch["content"]}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )


def render_chat() -> None:
    """Render NotebookLM Scenario Workspace with Quick Scenarios and Source Evidence Cards."""
    st.subheader("Artemis-SI Scenario & Predictive Analysis Workspace")
    _environment_strip()

    history: list[dict] = st.session_state.setdefault(_HISTORY_KEY, [])

    # Quick scenario preset buttons for fast hackathon demos
    st.caption("QUICK MISSION SCENARIOS (Click to run predictive RAG analysis or type your own below):")
    q_cols = st.columns(2)
    triggered_scenario: str | None = None
    for idx, q_text in enumerate(QUICK_SCENARIOS):
        if q_cols[idx % 2].button(f"▶ {q_text[:68]}...", key=f"quick_scen_{idx}", use_container_width=True):
            triggered_scenario = q_text

    head_l, head_r = st.columns([6, 1])
    head_l.caption(f"SCENARIO LOG · ENGINE: {ENGINE_LABEL}")
    if head_r.button("CLEAR LOG", key="chat_clear", use_container_width=True) and history:
        history.clear()
        st.rerun()

    for msg in history:
        with st.chat_message(msg["role"]):
            if msg.get("env_line"):
                st.caption(msg["env_line"] + (f" · {msg['mode']}" if msg.get("mode") else ""))
            st.markdown(msg["content"])
            if msg.get("passages"):
                _render_citations_expander(msg["passages"])

    typed_scenario = st.chat_input(
        "Propose an operational scenario or ask a fire safety question (e.g. short-circuit near vent duct)...",
        key="scenario_chat",
    )
    scenario = triggered_scenario or typed_scenario
    if not scenario:
        return

    env = read_environment() or {
        "material": "Nomex (meta-aramid)",
        "gravity_g": 0.16,
        "o2_pct": 34.0,
        "pressure_kpa": 56.5,
        "ppo2_kpa": 19.2,
        "limit_pct": 27.0,
        "margin_pct": -7.0,
        "risk_level": "High",
        "severity": 0.95,
    }

    line = _env_line(env)
    history.append({"role": "user", "content": scenario, "env_line": line, "mode": None})
    with st.chat_message("user"):
        st.caption(line)
        st.markdown(scenario)

    with st.chat_message("assistant"):
        st.caption(f"{line} · {ENGINE_LABEL}")
        try:
            text = st.write_stream(_as_chunks(predictive_engine.analyze_scenario(scenario, env, history)))
            if not isinstance(text, str):
                text = "".join(map(str, text))
            passages = st.session_state.get("last_retrieved_passages", [])
            _render_citations_expander(passages)
        except Exception as e:
            text = f"**ENGINE ERROR** — {type(e).__name__}: {e}"
            passages = []
            st.error(text)

    history.append({
        "role": "assistant",
        "content": text,
        "env_line": line,
        "mode": ENGINE_LABEL,
        "passages": passages,
    })