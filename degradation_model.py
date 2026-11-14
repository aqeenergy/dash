"""degradation_model.py — Material Aging & Autoignition Decay module for FLAMA."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st

from ui_components import MATERIALS, PALETTE, _inject_css, read_environment

TAU_REF_YEARS = 3.5
RISK_EFOLD_C = 80.0
_LEO_THERMAL_REF = 16.0 * (160.0 / 100.0) ** 2
_INTERNAL_THERMAL_FACTOR = 0.05
_BANNER_YEAR = 3.0


@dataclass(frozen=True)
class AgingEnvironment:
    name: str
    thermal_cycles_per_day: float
    delta_t_c: float
    uv_sun_fraction: float


ENVIRONMENTS: dict[str, AgingEnvironment] = {
    e.name: e
    for e in (
        AgingEnvironment("LEO (ISS ORBIT)", 16.0, 160.0, 0.60),
        AgingEnvironment("LUNAR SURFACE", 1.0 / 29.5, 270.0, 0.50),
        AgingEnvironment("MARS SURFACE", 1.0, 90.0, 0.25),
        AgingEnvironment("DEEP SPACE TRANSIT", 0.0, 5.0, 1.00),
    )
}


@dataclass(frozen=True)
class AgingProps:
    ait_c: float
    thermal_sens: float
    uv_sens: float
    max_drop_c: float


AGING_PROPS: dict[str, AgingProps] = {
    "Polyethylene (PE)": AgingProps(350.0, 0.70, 0.90, 45.0),
    "PMMA (acrylic)": AgingProps(430.0, 0.60, 0.70, 40.0),
    "Cotton fabric": AgingProps(400.0, 0.50, 0.80, 42.0),
    "Polycarbonate": AgingProps(480.0, 0.50, 0.60, 32.0),
    "Nomex (meta-aramid)": AgingProps(500.0, 0.40, 0.50, 24.0),
    "Silicone rubber": AgingProps(450.0, 0.35, 0.25, 18.0),
    "PEEK": AgingProps(570.0, 0.30, 0.30, 14.0),
    "Kapton (polyimide)": AgingProps(520.0, 0.25, 0.20, 12.0),
    "PTFE (Teflon)": AgingProps(530.0, 0.15, 0.10, 6.0),
}


def _resolve_env(environment: str | AgingEnvironment) -> AgingEnvironment:
    return environment if isinstance(environment, AgingEnvironment) else ENVIRONMENTS[environment]


def degradation_rate(material_name: str, environment: str | AgingEnvironment, exposed: bool = True) -> float:
    props, env = AGING_PROPS[material_name], _resolve_env(environment)
    thermal_norm = env.thermal_cycles_per_day * (env.delta_t_c / 100.0) ** 2 / _LEO_THERMAL_REF
    uv_norm = env.uv_sun_fraction
    if not exposed:
        thermal_norm *= _INTERNAL_THERMAL_FACTOR
        uv_norm = 0.0
    return props.thermal_sens * thermal_norm + props.uv_sens * uv_norm


def degradation_curve(
    material_name: str,
    environment: str | AgingEnvironment,
    mission_years: float = 5.0,
    exposed: bool = True,
    points: int = 61,
) -> pd.DataFrame:
    if mission_years <= 0:
        raise ValueError("mission_years must be positive")
    props = AGING_PROPS[material_name]
    r = degradation_rate(material_name, environment, exposed)
    year = np.linspace(0.0, mission_years, max(points, 2))
    drop = props.max_drop_c * (1.0 - np.exp(-r * year / TAU_REF_YEARS))
    mult = np.exp(drop / RISK_EFOLD_C)
    return pd.DataFrame(
        {
            "year": year,
            "ait_c": props.ait_c - drop,
            "ait_drop_c": drop,
            "risk_multiplier": mult,
            "risk_increase_pct": (mult - 1.0) * 100.0,
        }
    )


def ignition_risk_summary(df: pd.DataFrame, at_year: float) -> dict:
    y = float(np.clip(at_year, df["year"].iloc[0], df["year"].iloc[-1]))
    out = {"year": y}
    for col in ("ait_c", "ait_drop_c", "risk_multiplier", "risk_increase_pct"):
        out[col] = float(np.interp(y, df["year"], df[col]))
    return out


def environment_for_gravity(gravity_g: float) -> str | None:
    if gravity_g <= 0.01:
        return "LEO (ISS ORBIT)"
    if gravity_g <= 0.25:
        return "LUNAR SURFACE"
    if gravity_g <= 0.60:
        return "MARS SURFACE"
    return None


def summary_for_gravity(material_name: str, gravity_g: float, years: tuple[float, ...] = (3.0, 5.0)) -> str:
    env_name = environment_for_gravity(gravity_g)
    if env_name is None:
        return "Terrestrial conditions (1 g): space radiation and vacuum thermal cycling do not apply."
    df = degradation_curve(material_name, env_name, mission_years=max(years), exposed=True)
    rows = []
    for y in years:
        s = ignition_risk_summary(df, y)
        rows.append(
            f"- Year {s['year']:.0f}: Autoignition threshold drops to {s['ait_c']:.0f} °C "
            f"({-s['ait_drop_c']:+.0f} °C), raising ignition risk by {s['risk_increase_pct']:+.0f}%."
        )
    return f"Material aging projection ({env_name}, initial threshold {df['ait_c'].iloc[0]:.0f} °C):\n" + "\n".join(rows)


def _aging_figure(df: pd.DataFrame, material: str):
    import plotly.graph_objects as go

    p = PALETTE
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["year"],
            y=df["ait_c"],
            name="Autoignition Temperature (°C)",
            line=dict(color=p["accent"], width=3),
            hovertemplate="Year %{x:.1f} · %{y:.1f} °C<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["year"],
            y=df["risk_increase_pct"],
            name="Ignition Risk Increase (%)",
            yaxis="y2",
            line=dict(color=p["danger"], width=3, dash="dot"),
            hovertemplate="Year %{x:.1f} · +%{y:.1f}% risk<extra></extra>",
        )
    )
    if df["year"].iloc[-1] >= _BANNER_YEAR:
        fig.add_vline(
            x=_BANNER_YEAR,
            line_dash="dot",
            line_color=p["muted"],
            opacity=0.5,
            annotation_text="YEAR 3",
            annotation_font_color=p["muted"],
        )
    fig.update_layout(
        title=dict(text=f"{material.upper()} — AUTOIGNITION TEMPERATURE DECAY OVER TIME", font=dict(size=16)),
        paper_bgcolor=p["bg"],
        plot_bgcolor=p["bg"],
        font=dict(family="Cormorant Garamond, Georgia, serif", color=p["ink"], size=15),
        xaxis=dict(title="Mission Duration (Years)", gridcolor=p["edge"], zeroline=False),
        yaxis=dict(title="Autoignition Temperature (°C)", gridcolor=p["edge"], zeroline=False),
        yaxis2=dict(title="Ignition Risk Increase (%)", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
        legend=dict(orientation="h", y=1.14, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=56, b=10),
        height=380,
        hovermode="x unified",
    )
    return fig


def render_aging_panel(material: str | None = None, *, key: str = "aging") -> pd.DataFrame:
    _inject_css()
    st.subheader("Material Aging & Autoignition Risk Over Time")

    mats = list(MATERIALS)
    env_snapshot = read_environment()
    c1, c2 = st.columns(2)
    if material is None:
        default_idx = mats.index(env_snapshot["material"]) if env_snapshot and env_snapshot["material"] in mats else 4
        material = c1.selectbox("Material", mats, index=default_idx, key=f"{key}_mat")
    env_name = c2.selectbox("Mission Environment", list(ENVIRONMENTS), key=f"{key}_env")
    c3, c4 = st.columns([3, 2])
    years = c3.slider("Mission Duration (Years)", 1.0, 5.0, 5.0, 0.25, key=f"{key}_years")
    exposed = c4.toggle(
        "Direct Space Exposure (UV & Thermal Cycles)",
        value=True,
        key=f"{key}_exp",
        help="On: exposed to solar UV and full temperature swings. Off: protected inside the pressurized cabin.",
    )

    df = degradation_curve(material, env_name, years, exposed)
    end = ignition_risk_summary(df, years)
    probe = ignition_risk_summary(df, min(_BANNER_YEAR, years))
    env = ENVIRONMENTS[env_name]
    cycles = env.thermal_cycles_per_day * 365.25 * years

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Day 1 Autoignition", f"{df['ait_c'].iloc[0]:.0f} °C")
    m2.metric(f"Year {years:g} Autoignition", f"{end['ait_c']:.0f} °C", delta=f"{-end['ait_drop_c']:.1f} °C")
    m3.metric(
        "Ignition Risk Increase",
        f"+{end['risk_increase_pct']:.0f}%",
        delta=f"x{end['risk_multiplier']:.2f} multiplier",
        delta_color="inverse",
    )
    m4.metric("Thermal Cycles", f"{cycles:,.0f}")

    pct = probe["risk_increase_pct"]
    cls = "asi-low" if pct < 15 else "asi-medium" if pct < 40 else "asi-high"
    st.markdown(
        f'<div class="asi-banner {cls}">{material.upper()}: SAFE ON DAY 1 — '
        f'AUTOIGNITION RISK INCREASES BY +{pct:.0f}% AFTER {probe["year"]:.0f} YEARS '
        f'({env_name}, {"EXTERNAL EXPOSURE" if exposed else "INTERNAL CABIN"})</div>',
        unsafe_allow_html=True,
    )

    st.plotly_chart(_aging_figure(df, material), config={"displayModeBar": False}, use_container_width=True)
    return df