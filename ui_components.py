"""ui_components.py — FLAMA // Dual-Video 8.0s Infinite Burn Loop, Cosmic Trail & Circular Orbs.

Video Loop Logic:
  - Plays the full intro ignition once (0.0s -> 8.0s).
  - From 8.0s to the end (~10.0s), alternates two hardware-accelerated <video> layers
    (vidA & vidB) pre-buffered at t = 8.0s with a smooth 0.55s crossfade so the
    blue microgravity flame sphere stays burning forever without cuts or seek lag.
"""

from __future__ import annotations

import base64
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Physical Constants & Tunable Assumptions
# ---------------------------------------------------------------------------
PPO2_TARGET_KPA = 21.3
PPO2_MIN_KPA = 18.0
PPO2_MAX_KPA = 23.5
CABIN_P_MIN_KPA = 56.5
CABIN_P_MAX_KPA = 101.325
SAFETY_MARGIN_PCT = 3.0
LOW_G_PENALTY_PCT = 2.0
KPA_PER_PSI = 6.894757
N2_MOLAR_KG = 0.028014
R_GAS = 8.314462

# 60-25-10-5 Space Telemetry Palette
PALETTE = {
    "space_900": "#07080A",
    "space_800": "#101216",
    "space_700": "#1A1D23",
    "space_500": "#3A3F48",
    "paper_50": "#F4F3EF",
    "paper_200": "#D9D8D3",
    "glow_100": "#E8F1FA",
    "sky_200": "#BCD6EE",
    "sky_400": "#6FA3D8",
    "sky_600": "#2F63B0",
    "sky_800": "#12306E",
    "sky_950": "#0A1838",
    "flare_200": "#FFC27A",
    "flare_400": "#FF8A2A",
    "flare_500": "#F2600F",
    "flare_800": "#8C2A08",
    # Legacy aliases
    "bg": "#07080A",
    "panel": "#101216",
    "panel_soft": "#0B0D11",
    "sackboy": "#3A2216",
    "sackboy_edge": "#8C6D53",
    "edge": "#1A1D23",
    "ink": "#F4F3EF",
    "muted": "#D9D8D3",
    "accent": "#6FA3D8",
    "safe": "#6FA3D8",
    "caution": "#FF8A2A",
    "danger": "#F2600F",
    "blue_0g": "#6FA3D8",
    "blue_core": "#E8F1FA",
}

RISK_LEVELS = ("Low", "Medium", "High")
_RISK_ALIASES = {
    "low": "Low", "nominal": "Low",
    "medium": "Medium", "caution": "Medium",
    "high": "High", "critical": "High",
}
RISK_LABEL = {"Low": "NOMINAL", "Medium": "CAUTION", "High": "CRITICAL"}
RISK_COLOR = {
    "Low": PALETTE["sky_400"],
    "Medium": PALETTE["flare_400"],
    "High": PALETTE["flare_500"],
}

GRAVITY_PRESETS = {
    "0 g · ORBITAL (ISS)": 0.0,
    "0.16 g · LUNAR": 0.16,
    "0.38 g · MARTIAN": 0.38,
    "1 g · TERRESTRIAL": 1.0,
}

MISSION_PRESETS = {
    "Custom Configuration": None,
    "ISS Standard (0.00g · 21% O₂ · 101.3 kPa)": {
        "g": 0.00, "o2": 21.0, "hold": False, "p": 101.3,
    },
    "Lunar Gateway (0.00g · 32% O₂ · 70.3 kPa)": {
        "g": 0.00, "o2": 32.0, "hold": False, "p": 70.3,
    },
    "Artemis Lunar Base / Rover (0.16g · 34% O₂ · 56.5 kPa)": {
        "g": 0.16, "o2": 34.0, "hold": False, "p": 56.5,
    },
    "Mars Surface Habitat (0.38g · 34% O₂ · 56.5 kPa)": {
        "g": 0.38, "o2": 34.0, "hold": False, "p": 56.5,
    },
    "EVA Spacesuit (0.16g · 100% O₂ · 29.6 kPa)": {
        "g": 0.16, "o2": 100.0, "hold": False, "p": 29.6,
    },
}


@dataclass(frozen=True)
class Material:
    name: str
    loi_pct: float


MATERIALS: dict[str, Material] = {
    m.name: m
    for m in (
        Material("Polyethylene (PE)", 17.4),
        Material("PMMA (acrylic)", 17.3),
        Material("Cotton fabric", 18.4),
        Material("Polycarbonate", 26.0),
        Material("Nomex (meta-aramid)", 29.0),
        Material("Silicone rubber", 30.0),
        Material("PEEK", 35.0),
        Material("Kapton (polyimide)", 37.0),
        Material("PTFE (Teflon)", 95.0),
    )
}


@dataclass(frozen=True)
class SweetSpot:
    o2_pct: float
    pressure_kpa: float
    n2_kpa: float


@dataclass(frozen=True)
class O2Assessment:
    material: str
    gravity_g: float
    o2_pct: float
    pressure_kpa: float
    ppo2_kpa: float
    limit_pct: float
    margin_pct: float
    risk_level: str
    severity: float
    physiology: str
    sweet_spot: SweetSpot | None
    headline: str
    advice: str


# ---------------------------------------------------------------------------
# Automatic 3D Cover Video Loader (`D:\nasa_dashboard\flama_cover.mp4` or `video_1.mp4`)
# ---------------------------------------------------------------------------
def _load_cover_video_b64() -> str:
    """Load the user's 3D cover video from D:\\nasa_dashboard\\ or Downloads/Desktop."""
    proj_dir = Path(__file__).resolve().parent

    # Priority 1: Explicit named files in project root or assets/
    priority_files = [
        proj_dir / "flama_cover.mp4",
        proj_dir / "video_1.mp4",
        proj_dir / "assets" / "flama_cover.mp4",
        proj_dir / "assets" / "video_1.mp4",
    ]
    for pf in priority_files:
        if pf.exists() and pf.is_file():
            try:
                return base64.b64encode(pf.read_bytes()).decode("ascii")
            except Exception:
                pass

    # Priority 2: Newest .mp4 in D:\nasa_dashboard\ or subfolders
    local_mp4s = list(proj_dir.glob("*.mp4")) + list(proj_dir.glob("assets/*.mp4")) + list(proj_dir.glob("video/*.mp4"))
    if local_mp4s:
        best = max(local_mp4s, key=lambda p: p.stat().st_mtime)
        try:
            return base64.b64encode(best.read_bytes()).decode("ascii")
        except Exception:
            pass

    # Priority 3: Fallback check in Downloads / Desktop
    home = Path.home()
    for d in (home / "Downloads", home / "Desktop", home / "Videos"):
        if not d.exists():
            continue
        try:
            matches = [
                p for p in d.glob("*.mp4")
                if any(k in p.name.lower() for k in ("video_1", "flama", "23.30.03", "whatsapp", "flame"))
            ]
            if matches:
                best = max(matches, key=lambda p: p.stat().st_mtime)
                return base64.b64encode(best.read_bytes()).decode("ascii")
        except Exception:
            continue

    return ""


# ---------------------------------------------------------------------------
# Pure Physics Helpers
# ---------------------------------------------------------------------------
def normalize_risk(risk_level: str) -> str:
    try:
        return _RISK_ALIASES[str(risk_level).strip().lower()]
    except KeyError:
        raise ValueError(f"risk_level must be Low, Medium or High (got: {risk_level!r})") from None


def flammability_limit(material: Material, gravity_g: float) -> float:
    factor = max(0.0, min(1.0, (0.98 - gravity_g) / 0.30)) if gravity_g < 0.98 else 0.0
    return material.loi_pct - LOW_G_PENALTY_PCT * factor


def n2_mass_kg(n2_kpa: float, volume_m3: float, temp_k: float = 295.0) -> float:
    return max(n2_kpa, 0.0) * 1000 * volume_m3 * N2_MOLAR_KG / (R_GAS * temp_k)


def find_sweet_spot(
    material: Material,
    gravity_g: float,
    safety_margin: float = SAFETY_MARGIN_PCT,
) -> SweetSpot | None:
    x_fire = flammability_limit(material, gravity_g) - safety_margin
    x_max = 100 * PPO2_TARGET_KPA / CABIN_P_MIN_KPA
    x_min = math.floor(100 * PPO2_TARGET_KPA / CABIN_P_MAX_KPA * 2) / 2
    x = math.floor(min(x_fire, x_max) * 2) / 2
    if x < x_min:
        return None
    p = min(PPO2_TARGET_KPA / (x / 100), CABIN_P_MAX_KPA)
    return SweetSpot(o2_pct=x, pressure_kpa=p, n2_kpa=p - PPO2_TARGET_KPA)


def _fmt(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}"


def _severity(margin: float, safety_margin: float) -> float:
    if margin <= 0:
        return min(1.0, 0.62 + 0.38 * min(-margin, 8.0) / 8.0)
    if margin < safety_margin:
        return 0.30 + 0.30 * (1.0 - margin / safety_margin)
    return max(0.08, 0.30 - 0.22 * min(margin - safety_margin, 12.0) / 12.0)


def assess_o2(
    material_name: str,
    o2_pct: float,
    pressure_kpa: float,
    gravity_g: float = 0.0,
    volume_m3: float = 100.0,
    safety_margin: float = SAFETY_MARGIN_PCT,
) -> O2Assessment:
    del volume_m3
    material = MATERIALS[material_name]
    limit = flammability_limit(material, gravity_g)
    margin = limit - o2_pct
    ppo2 = pressure_kpa * o2_pct / 100
    sweet = find_sweet_spot(material, gravity_g, safety_margin)

    if margin <= 0:
        risk, label = "High", "CRITICAL FIRE HAZARD"
    elif margin < safety_margin:
        risk, label = "Medium", "CAUTION BUFFER"
    else:
        risk, label = "Low", "NOMINAL ENVELOPE"

    physiology = "hypoxia" if ppo2 < PPO2_MIN_KPA else "hyperoxia" if ppo2 > PPO2_MAX_KPA else "ok"
    headline = f"{_fmt(o2_pct)}% O₂ · {material.name} — {label}"

    parts: list[str] = []
    if sweet is None:
        parts.append(
            f"**Unsafe material in breathable air:** {material.name} ignites above **{_fmt(limit)}% O₂**, "
            f"so it remains flammable even in normal Earth air (21% O₂). Replace this material or shield it behind a fire barrier."
        )
    else:
        if o2_pct > sweet.o2_pct + 0.25:
            parts.append(
                f"**Recommended oxygen level: {_fmt(sweet.o2_pct)}% O₂.** Lowering oxygen from {_fmt(o2_pct)}% down to "
                f"**{_fmt(sweet.o2_pct)}% O₂** stops {material.name} from sustaining a fire while keeping the cabin air completely breathable."
            )
        elif o2_pct < sweet.o2_pct - 0.25:
            parts.append(
                f"**Safe to increase oxygen up to {_fmt(sweet.o2_pct)}% O₂.** {material.name} has extra safety margin here, "
                f"allowing higher oxygen concentration and lower cabin pressure to speed up spacewalk preparation."
            )
        else:
            parts.append(
                f"**Ideal oxygen level ({_fmt(sweet.o2_pct)}% O₂).** This setting provides the best balance between "
                f"fire prevention for {material.name} and comfortable crew breathing."
            )

    if physiology == "hypoxia":
        parts.append("**Low oxygen warning (Hypoxia):** Not enough breathable oxygen for the crew. Increase O₂ percentage or cabin pressure.")
    elif physiology == "hyperoxia":
        parts.append("**High oxygen warning (Hyperoxia):** Too much breathable oxygen for long missions. Lower cabin pressure or O₂ percentage.")

    return O2Assessment(
        material=material.name, gravity_g=gravity_g, o2_pct=o2_pct, pressure_kpa=pressure_kpa,
        ppo2_kpa=ppo2, limit_pct=limit, margin_pct=margin, risk_level=risk,
        severity=_severity(margin, safety_margin), physiology=physiology,
        sweet_spot=sweet, headline=headline, advice="\n\n".join(parts),
    )


def _inject_css() -> None:
    p = PALETTE
    st.markdown(
        f"""<style>
        .asi-banner {{
            font-family: 'IBM Plex Mono', monospace !important;
            font-size: 13.5px;
            font-weight: 600;
            border-left: 4px solid;
            border-radius: 6px;
            padding: 11px 16px;
            margin: 10px 0;
        }}
        .asi-low    {{ color: {p['glow_100']};  border-color: {p['sky_400']};   background: rgba(18, 48, 110, 0.35); }}
        .asi-medium {{ color: {p['flare_200']}; border-color: {p['flare_400']}; background: rgba(140, 42, 8, 0.30); }}
        .asi-high   {{ color: {p['paper_50']};  border-color: {p['flare_500']}; background: rgba(140, 42, 8, 0.50); }}
        </style>""",
        unsafe_allow_html=True,
    )


def read_environment(key: str = "env") -> dict | None:
    if f"{key}_snapshot" not in st.session_state:
        a = assess_o2("Nomex (meta-aramid)", 34.0, 56.5, 0.16, 100.0, SAFETY_MARGIN_PCT)
        st.session_state[f"{key}_snapshot"] = {
            "material": a.material, "gravity_g": a.gravity_g, "o2_pct": a.o2_pct,
            "pressure_kpa": a.pressure_kpa, "ppo2_kpa": a.ppo2_kpa, "limit_pct": a.limit_pct,
            "margin_pct": a.margin_pct, "risk_level": a.risk_level, "severity": a.severity,
        }
    return st.session_state.get(f"{key}_snapshot")


# ---------------------------------------------------------------------------
# Sackboy SVG Helper (No head stitches, full brown body, black eyes, zipper)
# ---------------------------------------------------------------------------
_FLAME_PATH = "M0,0 C-22,-12 -15,-46 0,-74 C15,-46 22,-12 0,0Z"


def _sackboy_figure(group_id: str, x: float, y: float, pose: str = "stand", gravity_g: float = 0.0) -> str:
    body_fill = "#3A2216"
    body_stroke = "#8C6D53"
    float_factor = max(0.0, min(1.0, (0.35 - gravity_g) / 0.35))
    anim_cls = "sb-float" if gravity_g <= 0.05 else "sb-breathe"
    tilt = -7.0 * float_factor if pose != "retreat" else (-10.0 - 4.0 * float_factor)

    if pose == "operate":
        limbs = (
            f'<path d="M-12,4 Q-22,18 -16,31" stroke="{body_stroke}" stroke-width="11" stroke-linecap="round" fill="none"/>'
            f'<path d="M-12,4 Q-22,18 -16,31" stroke="{body_fill}" stroke-width="8.5" stroke-linecap="round" fill="none"/>'
            f'<path d="M12,4 Q24,14 33,18" stroke="{body_stroke}" stroke-width="11" stroke-linecap="round" fill="none"/>'
            f'<path d="M12,4 Q24,14 33,18" stroke="{body_fill}" stroke-width="8.5" stroke-linecap="round" fill="none"/>'
            f'<path d="M-8,36 L-13,66" stroke="{body_stroke}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M-8,36 L-13,66" stroke="{body_fill}" stroke-width="9.5" stroke-linecap="round"/>'
            f'<path d="M8,36 L12,66" stroke="{body_stroke}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M8,36 L12,66" stroke="{body_fill}" stroke-width="9.5" stroke-linecap="round"/>'
            f'<rect x="29" y="12" width="11" height="24" rx="3" fill="#2F63B0" stroke="#F4F3EF" stroke-width="1.4"/>'
            f'<path d="M40,16 L52,12" stroke="#F4F3EF" stroke-width="2.6" stroke-linecap="round"/>'
            f'<polygon points="52,12 165,-14 165,22" fill="url(#mistGrad)" opacity="0.55"/>'
        )
    elif pose == "retreat":
        limbs = (
            f'<path d="M-12,4 Q-26,-4 -22,-16" stroke="{body_stroke}" stroke-width="11" stroke-linecap="round" fill="none"/>'
            f'<path d="M-12,4 Q-26,-4 -22,-16" stroke="{body_fill}" stroke-width="8.5" stroke-linecap="round" fill="none"/>'
            f'<path d="M12,4 Q26,12 22,26" stroke="{body_stroke}" stroke-width="11" stroke-linecap="round" fill="none"/>'
            f'<path d="M12,4 Q26,12 22,26" stroke="{body_fill}" stroke-width="8.5" stroke-linecap="round" fill="none"/>'
            f'<path d="M-8,36 L-20,64" stroke="{body_stroke}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M-8,36 L-20,64" stroke="{body_fill}" stroke-width="9.5" stroke-linecap="round"/>'
            f'<path d="M8,36 L20,62" stroke="{body_stroke}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M8,36 L20,62" stroke="{body_fill}" stroke-width="9.5" stroke-linecap="round"/>'
        )
    else:
        limbs = (
            f'<path d="M-12,4 Q-21,18 -17,32" stroke="{body_stroke}" stroke-width="11" stroke-linecap="round" fill="none"/>'
            f'<path d="M-12,4 Q-21,18 -17,32" stroke="{body_fill}" stroke-width="8.5" stroke-linecap="round" fill="none"/>'
            f'<path d="M12,4 Q21,18 17,32" stroke="{body_stroke}" stroke-width="11" stroke-linecap="round" fill="none"/>'
            f'<path d="M12,4 Q21,18 17,32" stroke="{body_fill}" stroke-width="8.5" stroke-linecap="round" fill="none"/>'
            f'<path d="M-8,36 L-10,66" stroke="{body_stroke}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M-8,36 L-10,66" stroke="{body_fill}" stroke-width="9.5" stroke-linecap="round"/>'
            f'<path d="M8,36 L10,66" stroke="{body_stroke}" stroke-width="12" stroke-linecap="round"/>'
            f'<path d="M8,36 L10,66" stroke="{body_fill}" stroke-width="9.5" stroke-linecap="round"/>'
        )

    zipper_teeth = "".join(
        f'<line x1="-3" y1="{y_t}" x2="3" y2="{y_t}" stroke="#9E958B" stroke-width="1.5"/>'
        for y_t in range(4, 36, 4)
    )
    zipper = (
        f'<line x1="0" y1="0" x2="0" y2="36" stroke="#18120E" stroke-width="3.2"/>'
        f'{zipper_teeth}'
        f'<rect x="-3.2" y="4" width="6.4" height="5" rx="1.2" fill="#C4BCB3" stroke="#18120E" stroke-width="0.8"/>'
        f'<polygon points="-2.5,9 2.5,9 4.2,21 -4.2,21" fill="#B5ABA0" stroke="#18120E" stroke-width="0.9"/>'
        f'<rect x="-1.6" y="13" width="3.2" height="5" rx="0.8" fill="#22140D"/>'
    )

    eyes = (
        f'<circle cx="-9" cy="-22" r="4.8" fill="#0B0908" stroke="#24160E" stroke-width="1"/>'
        f'<circle cx="-10.5" cy="-23.6" r="1.5" fill="#F4F3EF" opacity="0.9"/>'
        f'<circle cx="9" cy="-22" r="4.8" fill="#0B0908" stroke="#24160E" stroke-width="1"/>'
        f'<circle cx="7.5" cy="-23.6" r="1.5" fill="#F4F3EF" opacity="0.9"/>'
    )

    return (
        f'<g id="{group_id}" transform="translate({x} {y:.1f}) rotate({tilt:.1f})"><g class="{anim_cls}">'
        f'{limbs}'
        f'<rect x="-14" y="-2" width="28" height="40" rx="10" fill="{body_fill}" stroke="{body_stroke}" stroke-width="2.2"/>'
        f'{zipper}'
        f'<rect x="-22" y="-42" width="44" height="37" rx="14" fill="{body_fill}" stroke="{body_stroke}" stroke-width="2.2"/>'
        f'{eyes}'
        f'</g></g>'
    )


# ---------------------------------------------------------------------------
# Unified Dual-Video 8.0s Loop Cover + Top-Left Flame Sphere + Fine Cosmic Trail
# ---------------------------------------------------------------------------
def render_live_mission_control() -> None:
    """Render the Dual-Video 8.0s Loop Cover, Top-Left Microgravity Flame Logo, and Hub."""
    read_environment()
    video_b64 = _load_cover_video_b64()

    materials_dict = {name: mat.loi_pct for name, mat in MATERIALS.items()}
    presets_dict = {k: v for k, v in MISSION_PRESETS.items() if v is not None}

    # LAYER 1 (BACKGROUND): Space-900 (#07080A) & Sky-950 (#0A1838) Cabin Viewport
    iss_background_layer = """
      <defs>
        <radialGradient id="blue0gGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#E8F1FA" stop-opacity="0.95"/>
          <stop offset="38%" stop-color="#6FA3D8" stop-opacity="0.80"/>
          <stop offset="72%" stop-color="#2F63B0" stop-opacity="0.45"/>
          <stop offset="100%" stop-color="#0A1838" stop-opacity="0.0"/>
        </radialGradient>
        <radialGradient id="suppressCloudGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#E8F1FA" stop-opacity="0.92"/>
          <stop offset="45%" stop-color="#BCD6EE" stop-opacity="0.65"/>
          <stop offset="80%" stop-color="#6FA3D8" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="#12306E" stop-opacity="0.0"/>
        </radialGradient>
        <linearGradient id="mistGrad" x1="0%" y1="50%" x2="100%" y2="50%">
          <stop offset="0%" stop-color="#E8F1FA" stop-opacity="0.65"/>
          <stop offset="100%" stop-color="#6FA3D8" stop-opacity="0.0"/>
        </linearGradient>
      </defs>

      <rect width="560" height="320" rx="8" fill="#07080A"/>
      <line x1="110" y1="64" x2="110" y2="256" stroke="#1A1D23" stroke-width="1.5"/>
      <line x1="275" y1="64" x2="275" y2="256" stroke="#1A1D23" stroke-width="1.5"/>
      <line x1="495" y1="64" x2="495" y2="256" stroke="#1A1D23" stroke-width="1.5"/>
      <line x1="36" y1="152" x2="255" y2="152" stroke="#1A1D23" stroke-width="3" stroke-linecap="round"/>
      <circle cx="46" cy="152" r="3.5" fill="#2F63B0"/>
      <circle cx="245" cy="152" r="3.5" fill="#2F63B0"/>

      <g transform="translate(64 104)">
        <circle r="29" fill="#07080A" stroke="#1A1D23" stroke-width="3"/>
        <path d="M-25,12 Q0,-4 25,12" fill="none" stroke="#6FA3D8" stroke-width="2" opacity="0.85"/>
        <path d="M-23,14 Q0,-1 23,14" fill="none" stroke="#FF8A2A" stroke-width="1.2" opacity="0.75"/>
        <path d="M-23,15 Q0,0 23,15 L19,23 L-19,23 Z" fill="#0A1838" opacity="0.9"/>
        <circle cx="-10" cy="-10" r="1.2" fill="#F4F3EF" opacity="0.9"/>
        <circle cx="12" cy="-6" r="1" fill="#F4F3EF" opacity="0.8"/>
        <circle cx="4" cy="-16" r="1.3" fill="#BCD6EE" opacity="0.9"/>
      </g>
      <text x="64" y="146" text-anchor="middle" font-size="9" font-weight="600" fill="#3A3F48" letter-spacing="1.0">ORBITAL LIMB</text>

      <line x1="16" y1="256" x2="544" y2="256" stroke="#1A1D23" stroke-width="2"/>

      <g transform="translate(342 98)">
        <rect x="0" y="0" width="126" height="158" rx="6" fill="#101216" stroke="#1A1D23" stroke-width="2"/>
        <rect x="8" y="8" width="110" height="18" rx="3" fill="#07080A" stroke="#1A1D23" stroke-width="1"/>
        <text x="63" y="20" text-anchor="middle" font-size="9.5" font-weight="600" fill="#D9D8D3" letter-spacing="1.0">CIR · RACK 04</text>
        <rect id="asi-chamber-frame" x="14" y="32" width="98" height="74" rx="4" fill="#07080A" stroke="#1A1D23" stroke-width="1.8"/>
        <rect x="55" y="32" width="16" height="6" rx="1" fill="#2F63B0"/>
        <line x1="63" y1="90" x2="63" y2="106" stroke="#3A3F48" stroke-width="3"/>
        <rect x="47" y="86" width="32" height="5" rx="1" fill="#D9D8D3"/>
        <line x1="18" y1="120" x2="108" y2="120" stroke="#1A1D23" stroke-width="2"/>
        <line x1="18" y1="130" x2="108" y2="130" stroke="#1A1D23" stroke-width="2"/>
        <line x1="18" y1="140" x2="108" y2="140" stroke="#1A1D23" stroke-width="2"/>
        <circle cx="24" cy="149" r="3" fill="#6FA3D8"/>
        <circle cx="34" cy="149" r="3" fill="#2F63B0"/>
        <text x="108" y="152" text-anchor="end" font-size="9" font-weight="600" fill="#3A3F48">ECLSS BUS</text>
      </g>
    """

    # LAYER 2 (MIDDLE): Crew, Flame Scenes & Automated Suppression Cloud
    scene_low = (
        f'<g id="asi-scene-low" style="opacity:0;transition:opacity 0.25s ease;">'
        f'<circle cx="405" cy="164" r="16" fill="none" stroke="#6FA3D8" stroke-width="2.5"/>'
        f'<path d="M398,164 l5,5 l10,-11" fill="none" stroke="#6FA3D8" stroke-width="3" stroke-linecap="round"/>'
        f'{_sackboy_figure("asi-sb-low", 178, 184.0, "stand", 0.16)}'
        f'</g>'
    )

    scene_med = (
        f'<g id="asi-scene-med" style="opacity:0;transition:opacity 0.25s ease;">'
        f'<g transform="translate(405 168)">'
        f'<g id="asi-med-0g" style="opacity:0.4;">'
        f'<circle r="28" fill="url(#blue0gGlow)" class="pulse-c"/>'
        f'<circle r="14" fill="#6FA3D8" opacity="0.75" class="pulse-c"/>'
        f'<circle r="6" fill="#E8F1FA"/>'
        f'</g>'
        f'<g id="asi-med-1g" style="opacity:0.6;">'
        f'<ellipse id="asi-med-ellipse" rx="24" ry="30" fill="rgba(255,194,122,0.18)" stroke="#FFC27A" stroke-width="2" class="pulse-c"/>'
        f'<ellipse rx="13" ry="17" fill="rgba(255,138,42,0.72)" class="pulse-c"/>'
        f'<circle r="5" fill="#F4F3EF"/>'
        f'</g>'
        f'</g>'
        f'{_sackboy_figure("asi-sb-med", 178, 184.0, "operate", 0.16)}'
        f'</g>'
    )

    fire_0g = (
        '<g id="asi-fire-0g" style="opacity:0.3;transition:opacity 0.08s linear;">'
        '<circle cx="0" cy="-32" r="44" fill="url(#blue0gGlow)" class="pulse-c"/>'
        '<circle cx="-11" cy="-27" r="22" fill="#6FA3D8" opacity="0.80" class="pulse-c"/>'
        '<circle cx="11" cy="-36" r="20" fill="#BCD6EE" opacity="0.85" class="pulse-c"/>'
        '<circle cx="0" cy="-32" r="12" fill="#E8F1FA" opacity="0.96"/>'
        '<circle cx="-22" cy="-70" r="5.5" fill="#3A3F48" opacity="0.50" class="smoke-0g"/>'
        '<circle cx="8" cy="-78" r="7" fill="#3A3F48" opacity="0.45" class="smoke-0g"/>'
        '<circle cx="24" cy="-86" r="6" fill="#3A3F48" opacity="0.50" class="smoke-0g"/>'
        '</g>'
    )
    fire_1g = (
        f'<g id="asi-fire-1g" style="opacity:0.7;transition:opacity 0.08s linear;">'
        f'<g transform="translate(-26 0) scale(1.32)"><path d="{_FLAME_PATH}" fill="#F2600F" opacity="0.88" class="pulse"/></g>'
        f'<g transform="translate(2 0) scale(1.72)"><path d="{_FLAME_PATH}" fill="#F2600F" opacity="0.96" class="pulse"/></g>'
        f'<g transform="translate(28 0) scale(1.26)"><path d="{_FLAME_PATH}" fill="#FF8A2A" opacity="0.88" class="pulse"/></g>'
        f'<g transform="translate(2 0) scale(1.10)"><path d="{_FLAME_PATH}" fill="#FFC27A" opacity="0.92" class="pulse"/></g>'
        f'<g transform="translate(2 0) scale(0.65)"><path d="{_FLAME_PATH}" fill="#F4F3EF" opacity="0.95"/></g>'
        f'<circle cx="0" cy="-86" r="6.5" fill="#3A3F48" opacity="0.50" class="smoke-1g"/>'
        f'<circle cx="12" cy="-100" r="8" fill="#3A3F48" opacity="0.45" class="smoke-1g"/>'
        f'</g>'
    )

    scene_high = (
        f'<g id="asi-scene-high" style="opacity:1;transition:opacity 0.25s ease;">'
        f'<g id="asi-flame-scaler" transform="translate(405 202) scale(1.08)" style="transition:transform 0.35s ease;">{fire_0g}{fire_1g}</g>'
        f'{_sackboy_figure("asi-sb-high", 152, 184.0, "retreat", 0.16)}'
        f'</g>'
    )

    suppression_cloud = (
        '<g id="asi-suppress-cloud" style="opacity:0;transition:opacity 0.35s ease;">'
        '<polygon points="405,134 362,200 448,200" fill="url(#mistGrad)" transform="rotate(90 405 167)" opacity="0.85"/>'
        '<circle cx="405" cy="170" r="42" fill="url(#suppressCloudGrad)" class="pulse-c"/>'
        '<circle cx="388" cy="162" r="24" fill="#E8F1FA" opacity="0.55" class="pulse-c"/>'
        '<circle cx="422" cy="174" r="26" fill="#6FA3D8" opacity="0.45" class="pulse-c"/>'
        '</g>'
    )

    # LAYER 3 (FOREGROUND HUD)
    iss_foreground_hud = """
      <rect x="16" y="42" width="528" height="22" rx="4" fill="#101216" stroke="#1A1D23" stroke-width="1.5"/>
      <text id="asi-duct-txt" x="28" y="57" font-size="10" font-weight="600" fill="#D9D8D3" letter-spacing="0.8">CABIN VENTILATION DUCT · FORCED AIRFLOW</text>

      <g transform="translate(324 44)">
        <rect id="asi-smoke-box" width="216" height="18" rx="3" fill="#07080A" stroke="#1A1D23" stroke-width="1.2"/>
        <circle id="asi-smoke-led" cx="12" cy="9" r="4" fill="#6FA3D8"/>
        <text id="asi-smoke-txt" x="23" y="13" font-size="9.5" font-weight="600" fill="#F4F3EF" letter-spacing="0.6">SAME SENSOR: STANDBY</text>
      </g>

      <rect id="asi-svg-badge-rect" x="16" y="10" width="160" height="24" rx="4" fill="#8C2A08" stroke="#F2600F" stroke-width="1.2"/>
      <text id="asi-svg-badge-text" x="96" y="26" text-anchor="middle" font-size="11" font-weight="700" fill="#F4F3EF" letter-spacing="1.2">RISK · CRITICAL</text>

      <rect x="354" y="10" width="190" height="24" rx="4" fill="#101216" stroke="#1A1D23"/>
      <text id="asi-svg-grav-text" x="449" y="26" text-anchor="middle" font-size="10.5" font-weight="600" fill="#BCD6EE" letter-spacing="0.9">0.16G BUOYANT PLUME</text>

      <rect x="16" y="274" width="528" height="32" rx="4" fill="#101216" stroke="#1A1D23" stroke-width="1"/>
      <text id="asi-svg-caption" x="280" y="294" text-anchor="middle" font-size="11" font-weight="600" letter-spacing="1.0" fill="#F4F3EF">CRITICAL — O₂ ABOVE FLAMMABILITY LIMIT, RAPID FLAME SPREAD</text>
    """

    # Top-Left FLAMA Bluish Microgravity Flame Sphere Logo (Returns to Hub on click)
    flama_top_left_logo_svg = """
      <svg viewBox="0 0 48 48" style="width:32px;height:32px;display:block;overflow:visible;">
        <defs>
          <radialGradient id="logoSphereOuter" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stop-color="#E8F1FA" stop-opacity="0.95"/>
            <stop offset="45%"  stop-color="#6FA3D8" stop-opacity="0.88"/>
            <stop offset="80%"  stop-color="#2F63B0" stop-opacity="0.60"/>
            <stop offset="100%" stop-color="#0A1838" stop-opacity="0.0"/>
          </radialGradient>
        </defs>
        <circle cx="24" cy="24" r="19" fill="url(#logoSphereOuter)" class="pulse-c"/>
        <circle cx="24" cy="24" r="14" fill="#12306E" stroke="#6FA3D8" stroke-width="1.2"/>
        <!-- Internal Cellular Microgravity Flame Petals (matching video_1.mp4 at t=8s) -->
        <path d="M 24,24 C 18,16 14,18 14,24 C 14,30 18,32 24,24 Z" fill="none" stroke="#6FA3D8" stroke-width="1.3" opacity="0.85"/>
        <path d="M 24,24 C 30,16 34,18 34,24 C 34,30 30,32 24,24 Z" fill="none" stroke="#6FA3D8" stroke-width="1.3" opacity="0.85"/>
        <path d="M 24,24 C 18,14 22,10 24,10 C 26,10 30,14 24,24 Z" fill="none" stroke="#E8F1FA" stroke-width="1.2" opacity="0.90"/>
        <path d="M 24,24 C 18,34 22,38 24,38 C 26,38 30,34 24,24 Z" fill="none" stroke="#6FA3D8" stroke-width="1.2" opacity="0.85"/>
        <circle cx="24" cy="24" r="2.2" fill="#E8F1FA"/>
      </svg>
    """

    # 4 Pure Graphic SVGs for the 4 Strictly Round Bubbles (ZERO TEXT INSIDE)
    orb_1_dashboard_svg = """
      <svg viewBox="0 0 100 100" style="width:66px;height:66px;display:block;overflow:visible;">
        <defs>
          <linearGradient id="orb1Arc" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#6FA3D8"/>
            <stop offset="55%" stop-color="#E8F1FA"/>
            <stop offset="100%" stop-color="#FF8A2A"/>
          </linearGradient>
        </defs>
        <circle cx="50" cy="50" r="38" fill="none" stroke="rgba(188,214,238,0.16)" stroke-width="5"/>
        <path d="M 23 77 A 38 38 0 1 1 77 77" fill="none" stroke="url(#orb1Arc)" stroke-width="5.5" stroke-linecap="round"/>
        <circle cx="50" cy="50" r="24" fill="none" stroke="rgba(111,163,216,0.3)" stroke-width="1.5" stroke-dasharray="3 3"/>
        <line id="orb1-needle" x1="50" y1="50" x2="70" y2="30" stroke="#F4F3EF" stroke-width="3" stroke-linecap="round"/>
        <circle cx="50" cy="50" r="5.5" fill="#F2600F" stroke="#F4F3EF" stroke-width="1.5"/>
      </svg>
    """

    orb_2_simulation_svg = """
      <svg viewBox="0 0 100 100" style="width:66px;height:66px;display:block;overflow:visible;">
        <defs>
          <radialGradient id="orb2Blue" cx="50%" cy="52%" r="48%">
            <stop offset="0%" stop-color="#E8F1FA" stop-opacity="0.98"/>
            <stop offset="45%" stop-color="#6FA3D8" stop-opacity="0.90"/>
            <stop offset="100%" stop-color="#12306E" stop-opacity="0.0"/>
          </radialGradient>
        </defs>
        <path d="M 22,56 C 18,78 36,88 50,88 C 64,88 82,78 78,56 C 82,36 68,22 62,16 C 64,32 56,38 50,24 C 44,38 36,32 38,16 C 32,22 18,36 22,56 Z"
              fill="#F2600F" opacity="0.88" class="pulse"/>
        <path d="M 26,60 C 24,76 38,84 50,84 C 62,84 76,76 74,60 C 74,46 62,36 50,28 C 38,36 26,46 26,60 Z"
              fill="#FFC27A" opacity="0.75"/>
        <circle cx="50" cy="58" r="24" fill="url(#orb2Blue)" class="pulse-c"/>
        <path d="M 36,64 C 34,48 44,38 50,26 C 56,38 66,48 64,64 C 62,74 56,78 50,78 C 44,78 38,74 36,64 Z"
              fill="#6FA3D8" opacity="0.92"/>
        <path d="M 43,66 C 42,54 47,46 50,38 C 53,46 58,54 57,66 Z" fill="#E8F1FA" opacity="0.95"/>
      </svg>
    """

    orb_3_aging_svg = """
      <svg viewBox="0 0 100 100" style="width:62px;height:62px;display:block;overflow:visible;">
        <polygon points="50,16 80,33 80,67 50,84 20,67 20,33" fill="none" stroke="#6FA3D8" stroke-width="2" opacity="0.7"/>
        <polygon points="50,28 69,39 69,61 50,72 31,61 31,39" fill="none" stroke="#FFC27A" stroke-width="1.5" stroke-dasharray="4 3" opacity="0.8"/>
        <path d="M 22 64 Q 38 34, 50 52 T 78 36" fill="none" stroke="#FF8A2A" stroke-width="2.8" stroke-linecap="round"/>
        <circle cx="22" cy="64" r="3.5" fill="#E8F1FA"/>
        <circle cx="50" cy="52" r="3.5" fill="#FFC27A"/>
        <circle cx="78" cy="36" r="3.5" fill="#F2600F"/>
      </svg>
    """

    orb_4_archive_svg = """
      <svg viewBox="0 0 100 100" style="width:62px;height:62px;display:block;overflow:visible;">
        <circle cx="50" cy="50" r="14" fill="rgba(111,163,216,0.25)" stroke="#E8F1FA" stroke-width="2"/>
        <ellipse cx="50" cy="50" rx="38" ry="15" fill="none" stroke="#6FA3D8" stroke-width="1.8" transform="rotate(-28 50 50)"/>
        <ellipse cx="50" cy="50" rx="38" ry="15" fill="none" stroke="#FFC27A" stroke-width="1.5" stroke-dasharray="5 4" transform="rotate(32 50 50)"/>
        <circle cx="78" cy="35" r="4" fill="#FF8A2A"/>
        <circle cx="24" cy="62" r="3.5" fill="#E8F1FA"/>
      </svg>
    """

    preset_options_html = '<option value="Custom Configuration">Custom Configuration</option>' + "".join(
        f'<option value="{html.escape(k)}">{html.escape(k)}</option>' for k in presets_dict
    )
    material_options_html = "".join(
        f'<option value="{html.escape(k)}" {"selected" if k == "Nomex (meta-aramid)" else ""}>{html.escape(k)}</option>'
        for k in materials_dict
    )

    video_data_uri = f"data:video/mp4;base64,{video_b64}" if video_b64 else ""

    html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

  :root {{
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
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-variant-numeric: tabular-nums !important;
  }}

  body {{
    background: #000000;
    color: var(--paper-50);
    font-family: 'IBM Plex Sans', -apple-system, sans-serif;
    overflow-x: hidden;
    padding: 0;
  }}

  .os-view {{
    display: none;
  }}
  .os-view.active {{
    display: block;
    animation: viewFade 0.45s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  }}
  @keyframes viewFade {{
    from {{ opacity: 0; transform: translateY(6px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}

  /* =========================================================================
     VIEW 0: DUAL-VIDEO HARDWARE CROSSFADE COVER (Loops from t = 8.0s forever)
     ========================================================================= */
  .cover-stage {{
    position: relative;
    width: 100%;
    min-height: 92vh;
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
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: var(--paper-200);
    cursor: pointer;
    z-index: 20;
    opacity: 0.38;
    transition: opacity 0.2s ease, border-color 0.2s ease;
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

  /* INITIALIZE Button positioned lower down below the video's FLAMA wordmark */
  .cover-init-btn {{
    margin-top: 44px;
    background: rgba(16, 18, 22, 0.85);
    color: var(--paper-50);
    border: 1px solid rgba(111, 163, 216, 0.48);
    border-radius: 999px;
    padding: 13px 48px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13.5px;
    font-weight: 600;
    letter-spacing: 0.30em;
    text-transform: uppercase;
    cursor: pointer;
    box-shadow: 0 0 28px rgba(47, 99, 176, 0.25), inset 0 1px 1px rgba(232, 241, 250, 0.15);
    transition: all 0.22s ease;
    z-index: 10;
  }}
  .cover-init-btn:hover {{
    background: var(--flare-500);
    border-color: var(--paper-50);
    color: var(--paper-50);
    transform: translateY(-2px) scale(1.04);
    box-shadow: 0 0 36px rgba(242, 96, 15, 0.65);
  }}

  /* =========================================================================
     TOP-LEFT FLAMA LOGO (BLUISH MICROGRAVITY FLAME SPHERE) + MENU
     ========================================================================= */
  .top-nav-row {{
    display: none;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px 0 20px;
    background: var(--space-900);
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
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, rgba(18, 48, 110, 0.65) 0%, rgba(16, 18, 22, 0.95) 75%);
    border: 1.5px solid rgba(111, 163, 216, 0.42);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.7), 0 0 16px rgba(111, 163, 216, 0.22);
    transition: transform 0.22s cubic-bezier(0.22, 1, 0.36, 1),
                border-color 0.22s ease,
                box-shadow 0.22s ease;
  }}
  .flama-logo-home-btn:hover {{
    transform: scale(1.09);
    border-color: var(--glow-100);
    box-shadow: 0 8px 26px rgba(0, 0, 0, 0.85), 0 0 24px rgba(111, 163, 216, 0.55);
  }}

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
    transition: border-color 0.16s ease, background 0.16s ease;
  }}
  .hamburger-btn:hover {{
    border-color: var(--sky-400);
    background: var(--sky-950);
  }}
  .hamburger-line {{
    width: 16px;
    height: 1.8px;
    background: var(--paper-200);
    border-radius: 2px;
  }}

  .hamburger-dropdown {{
    display: none;
    position: absolute;
    top: 62px;
    left: 20px;
    width: 225px;
    background: var(--space-800);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    box-shadow: 0 16px 36px rgba(0, 0, 0, 0.85);
    z-index: 9999;
    padding: 6px;
  }}
  .hamburger-dropdown.open {{
    display: block;
    animation: menuSlide 0.15s ease forwards;
  }}
  @keyframes menuSlide {{
    from {{ opacity: 0; transform: translateY(-5px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  .menu-item {{
    width: 100%;
    text-align: left;
    background: transparent;
    color: var(--paper-200);
    border: none;
    border-radius: 6px;
    padding: 9px 12px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: background 0.14s, color 0.14s;
  }}
  .menu-item:hover {{
    background: var(--space-700);
    color: var(--glow-100);
  }}
  .menu-item.active {{
    background: var(--sky-600);
    color: var(--paper-50);
  }}

  /* =========================================================================
     VIEW 1: COMMAND HUB (Long Fine Cosmic Trail + Command Bar + 4 Round Orbs)
     ========================================================================= */
  .hub-stage {{
    position: relative;
    min-height: 84vh;
    background: var(--space-900);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 16px 32px 16px;
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
    animation: fineFlow1 11s cubic-bezier(0.4, 0, 0.2, 1) infinite;
  }}
  .fine-stream-orange {{
    stroke-dasharray: 340 1060;
    animation: fineFlow2 13s linear infinite;
  }}
  .fine-stream-white {{
    stroke-dasharray: 220 1180;
    animation: fineFlow1 11s cubic-bezier(0.4, 0, 0.2, 1) 0.12s infinite;
  }}
  .fine-Sec-filament {{
    stroke-dasharray: 280 1120;
    animation: fineFlowRev 16s linear infinite;
  }}
  .nebula-whisper {{
    animation: whisperPulse 8s ease-in-out infinite;
  }}
  .dust-twinkle-a {{
    animation: dustFloat 7s ease-in-out infinite;
  }}
  .dust-twinkle-b {{
    animation: dustFloat 9s ease-in-out 2.5s infinite;
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
    0%, 100% {{ opacity: 0.22; }}
    50%      {{ opacity: 0.48; }}
  }}
  @keyframes dustFloat {{
    0%, 100% {{ transform: translate(0px, 0px); opacity: 0.30; }}
    50%      {{ transform: translate(16px, -4px); opacity: 0.90; }}
  }}

  .command-center-wrap {{
    width: 100%;
    max-width: 740px;
    margin: 0 auto 46px auto;
    position: relative;
    z-index: 10;
  }}
  .command-bar-shell {{
    display: flex;
    align-items: center;
    background: #232529;
    border: 1px solid #35383F;
    border-radius: 16px;
    height: 54px;
    padding: 0 14px 0 22px;
    box-shadow: 0 16px 42px rgba(0, 0, 0, 0.78);
    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
  }}
  .command-bar-shell:focus-within {{
    background: #26292E;
    border-color: var(--sky-400);
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.85), 0 0 22px rgba(111, 163, 216, 0.20);
  }}
  .cmd-input {{
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    color: var(--paper-50);
    font-family: 'IBM Plex Sans', -apple-system, sans-serif;
    font-size: 15px;
    font-weight: 400;
  }}
  .cmd-input::placeholder {{
    color: #8E929B;
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
    transition: color 0.18s ease, background 0.18s ease, transform 0.18s ease;
  }}
  .voice-btn:hover {{
    color: var(--paper-50);
    background: rgba(255, 255, 255, 0.07);
    transform: scale(1.06);
  }}
  .voice-btn.recording {{
    background: var(--flare-500);
    color: var(--paper-50);
    animation: micPulse 1.2s ease-in-out infinite;
  }}
  @keyframes micPulse {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(242, 96, 15, 0.65); }}
    50%      {{ box-shadow: 0 0 0 10px rgba(242, 96, 15, 0.0); }}
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
    animation: viewFade 0.22s ease forwards;
  }}
  .cmd-resp-head {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: 'IBM Plex Mono', monospace;
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
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    cursor: pointer;
  }}

  /* 4 Strictly Round Floating Bubbles Below (50% radius, Pure Images, Zero Text) */
  .circular-orbs-row {{
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 38px;
    flex-wrap: wrap;
    z-index: 10;
  }}
  .floating-orb {{
    width: 116px;
    height: 116px;
    aspect-ratio: 1 / 1;
    border-radius: 50% !important;
    background: radial-gradient(circle at 32% 28%, rgba(18, 48, 110, 0.52) 0%, rgba(16, 18, 22, 0.96) 72%);
    border: 1.5px solid rgba(111, 163, 216, 0.32);
    box-shadow:
      0 20px 40px rgba(0, 0, 0, 0.78),
      inset 0 2px 5px rgba(232, 241, 250, 0.18);
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
    user-select: none;
    transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1),
                border-color 0.28s ease,
                box-shadow 0.28s ease;
  }}
  .floating-orb.orb-1 {{ animation: orbFloat1 4.6s ease-in-out infinite; }}
  .floating-orb.orb-2 {{ animation: orbFloat2 5.2s ease-in-out 0.5s infinite; }}
  .floating-orb.orb-3 {{ animation: orbFloat1 5.0s ease-in-out 1.1s infinite; }}
  .floating-orb.orb-4 {{ animation: orbFloat2 5.6s ease-in-out 1.6s infinite; }}

  @keyframes orbFloat1 {{
    0%, 100% {{ transform: translateY(0px); }}
    50%      {{ transform: translateY(-10px); }}
  }}
  @keyframes orbFloat2 {{
    0%, 100% {{ transform: translateY(-4px); }}
    50%      {{ transform: translateY(8px); }}
  }}

  .floating-orb.interactive {{
    cursor: pointer;
  }}
  .floating-orb.interactive:hover {{
    animation-play-state: paused;
    transform: translateY(-10px) scale(1.08);
    border-color: var(--glow-100);
    box-shadow:
      0 24px 48px rgba(0, 0, 0, 0.88),
      0 0 28px rgba(111, 163, 216, 0.45),
      inset 0 2px 6px rgba(232, 241, 250, 0.35);
  }}
  .floating-orb.passive {{
    cursor: default;
    opacity: 0.78;
    border-color: rgba(58, 63, 72, 0.65);
    background: radial-gradient(circle at 32% 28%, rgba(26, 29, 35, 0.75) 0%, rgba(11, 13, 17, 0.96) 75%);
  }}

  /* =========================================================================
     VIEW 2 & VIEW 3: TELEMETRY DASHBOARD & SIMULATION WORKSPACES
     ========================================================================= */
  .workspace-wrap {{
    background: var(--space-900);
    padding: 8px 16px 28px 16px;
  }}
  .workspace-card {{
    background: var(--space-800);
    border: 1px solid var(--space-700);
    border-radius: 14px;
    padding: 22px 24px;
    max-width: 1380px;
    margin: 0 auto;
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
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--sky-400);
    margin-bottom: 4px;
  }}
  .ws-title {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 22px;
    font-weight: 700;
    color: var(--paper-50);
    letter-spacing: -0.01em;
  }}
  .switch-bubble-btn {{
    background: var(--space-900);
    color: var(--paper-200);
    border: 1px solid var(--space-700);
    border-radius: 8px;
    padding: 7px 14px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: all 0.16s ease;
  }}
  .switch-bubble-btn:hover {{
    background: var(--sky-600);
    border-color: var(--sky-400);
    color: var(--paper-50);
  }}

  .dash-two-col {{
    display: grid;
    grid-template-columns: 1.05fr 0.95fr;
    gap: 24px;
    align-items: start;
  }}
  @media (max-width: 960px) {{
    .dash-two-col {{ grid-template-columns: 1fr; }}
  }}

  .ctrl-row {{
    display: grid;
    grid-template-columns: 1.35fr 1fr;
    gap: 14px;
    margin-bottom: 14px;
  }}

  .field-label {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    font-weight: 500;
    color: var(--paper-200);
    margin-bottom: 6px;
  }}
  .field-val {{
    font-family: 'IBM Plex Mono', monospace;
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
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 13.5px;
    font-weight: 500;
    outline: none;
    cursor: pointer;
    transition: border-color 0.15s;
  }}
  select:hover, select:focus {{
    border-color: var(--sky-400);
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
    box-shadow: 0 0 10px rgba(111, 163, 216, 0.45);
    transition: transform 0.08s ease;
  }}
  input[type="range"]::-webkit-slider-thumb:hover {{
    transform: scale(1.14);
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
  }}
  .tcard-lbl {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--paper-200);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }}
  .tcard-val {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 23px;
    font-weight: 700;
    color: var(--paper-50);
    white-space: nowrap;
  }}
  .tcard-sub {{
    font-family: 'IBM Plex Mono', monospace;
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
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.04em;
    border-left: 4px solid;
    border-radius: 6px;
    padding: 11px 14px;
    margin-bottom: 12px;
  }}
  .banner.low    {{ color: var(--glow-100);  border-color: var(--sky-400);   background: rgba(18, 48, 110, 0.38); }}
  .banner.medium {{ color: var(--flare-200); border-color: var(--flare-400); background: rgba(140, 42, 8, 0.30); }}
  .banner.high   {{ color: var(--paper-50);  border-color: var(--flare-500); background: rgba(140, 42, 8, 0.52); }}

  .insight-box {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 14px 16px;
    font-size: 13.5px;
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
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.06em;
    padding: 3px 9px;
    border-radius: 4px;
    white-space: nowrap;
    margin-top: 2px;
    color: var(--space-900);
  }}

  .sim-layout {{
    max-width: 1060px;
    margin: 0 auto;
  }}
  .vis-box {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    overflow: hidden;
    padding: 6px;
  }}
  .theater-dock {{
    display: grid;
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 14px 18px;
    margin-top: 14px;
    grid-template-columns: 1.2fr 1.2fr 1fr;
    gap: 18px;
    align-items: center;
  }}
  @media (max-width: 820px) {{
    .theater-dock {{ grid-template-columns: 1fr; }}
  }}

  .phys-summary-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-top: 12px;
  }}
  .phys-pill {{
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 10px 14px;
  }}
  .phys-pill-lbl {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--paper-200);
    margin-bottom: 3px;
  }}
  .phys-pill-val {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--paper-50);
  }}

  .eclss-box {{
    margin-top: 14px;
    background: var(--space-900);
    border: 1px solid var(--space-700);
    border-radius: 10px;
    padding: 14px 18px;
  }}
  .eclss-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .eclss-title {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--sky-400);
  }}
  .eclss-sub {{
    font-size: 13.5px;
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
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.16s ease;
  }}
  .eclss-trigger-btn:hover {{
    background: var(--flare-500);
    border-color: var(--flare-200);
    color: var(--paper-50);
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
    transition: all 0.25s ease;
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
</style>
</head>
<body>

<!-- =========================================================================
     VIEW 0: DUAL-VIDEO HARDWARE CROSSFADE COVER (Loops from t = 8.0s forever)
     ========================================================================= -->
<div id="view-cover" class="os-view active">
  <div class="cover-stage">

    <label class="video-loader-pill" title="Seleccionar archivo de vídeo .mp4">
      📁 Cargar vídeo .mp4
      <input id="custom-video-input" type="file" accept="video/mp4,video/*" style="display:none;">
    </label>

    <!-- Dual Hardware-Accelerated Video Layers for Seamless 8.0s -> 10.0s Infinite Loop -->
    <div class="cover-video-viewport">
      <video id="flama-vid-a" class="cover-vid-layer" style="opacity:1;" muted playsinline preload="auto" src="{video_data_uri}"></video>
      <video id="flama-vid-b" class="cover-vid-layer" style="opacity:0;" muted playsinline preload="auto" src="{video_data_uri}"></video>
    </div>

    <button id="si-enter-console-btn" class="cover-init-btn">INITIALIZE</button>
  </div>
</div>

<!-- =========================================================================
     TOP-LEFT FLAMA LOGO (BLUISH MICROGRAVITY FLAME SPHERE) + HAMBURGER MENU
     ========================================================================= -->
<div id="top-nav-bar" class="top-nav-row">
  <div class="top-left-brand-group">
    <button id="flama-logo-home" class="flama-logo-home-btn" title="FLAMA — Volver a inicio">
      {flama_top_left_logo_svg}
    </button>

    <button id="hamburger-toggle" class="hamburger-btn" title="Menú">
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
    </button>
  </div>

  <div id="hamburger-menu" class="hamburger-dropdown">
    <button id="menu-btn-hub" class="menu-item active">
      <span>00 / Command Hub</span><span>●</span>
    </button>
    <button id="menu-btn-dashboard" class="menu-item">
      <span>01 / Dashboard</span><span>→</span>
    </button>
    <button id="menu-btn-simulation" class="menu-item">
      <span>02 / Simulation</span><span>→</span>
    </button>
    <button id="menu-btn-cover" class="menu-item">
      <span>↺ Cover Screen</span><span>↗</span>
    </button>
  </div>
</div>

<!-- =========================================================================
     VIEW 1: COMMAND HUB (Long Fine Cosmic Trail + Command Bar + 4 Round Orbs)
     ========================================================================= -->
<div id="view-hub" class="os-view">
  <div class="hub-stage">

    <!-- LONGER, THINNER & SMOOTHER COSMIC COMET TRAIL (Blue, Orange & Warm White) -->
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
          <animateMotion dur="11s" repeatCount="indefinite" rotate="auto">
            <mpath href="#cometMasterOrbit"/>
          </animateMotion>
        </g>

        <g>
          <circle r="7" fill="#FF8A2A" opacity="0.45" filter="url(#fineGlow)"/>
          <circle r="2.0" fill="#FFC27A"/>
          <animateMotion dur="13s" repeatCount="indefinite" rotate="auto">
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

    <!-- CENTER COMMAND BAR (Clean: No '+' button, only input + voice mic on right) -->
    <div class="command-center-wrap">
      <div class="command-bar-shell">
        <input id="hub-cmd-input" class="cmd-input" type="text"
               placeholder="Escribe / para comandos">
        <button id="hub-voice-btn" class="voice-btn" title="Hablar por voz">
          <svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;">
            <rect x="9" y="2" width="6" height="11" rx="3"/>
            <path d="M5 10a7 7 0 0 0 14 0"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
            <line x1="9" y1="21" x2="15" y2="21"/>
          </svg>
        </button>
      </div>

      <div id="hub-cmd-drawer" class="cmd-response-drawer">
        <div class="cmd-resp-head">
          <span id="hub-cmd-status">FLAMA SI // PREDICTIVE SCENARIO SYNTHESIS</span>
          <button id="hub-cmd-close" class="cmd-resp-close">✕</button>
        </div>
        <div id="hub-cmd-output"></div>
      </div>
    </div>

    <!-- 4 STRICTLY ROUND FLOATING BUBBLES BELOW (Pure Images, Zero Text Inside) -->
    <div class="circular-orbs-row">
      <div id="orb-dashboard" class="floating-orb interactive orb-1">
        {orb_1_dashboard_svg}
      </div>

      <div id="orb-simulation" class="floating-orb interactive orb-2">
        {orb_2_simulation_svg}
      </div>

      <div class="floating-orb passive orb-3">
        {orb_3_aging_svg}
      </div>

      <div class="floating-orb passive orb-4">
        {orb_4_archive_svg}
      </div>
    </div>

  </div>
</div>

<!-- =========================================================================
     VIEW 2: DASHBOARD WORKSPACE
     ========================================================================= -->
<div id="view-dashboard" class="os-view">
  <div class="workspace-wrap">
    <div class="workspace-card">
      <div class="ws-header-row">
        <div>
          <div class="ws-tag">01 // ATMOSPHERIC TELEMETRY &amp; O₂ OPTIMIZER</div>
          <div class="ws-title">Dashboard — Mission &amp; Atmosphere Control</div>
        </div>
        <div style="display:flex;gap:8px;">
          <button id="btn-dash-to-hub" class="switch-bubble-btn">← Command Hub</button>
          <button id="btn-dash-to-sim" class="switch-bubble-btn">Simulation →</button>
        </div>
      </div>

      <div class="dash-two-col">
        <div>
          <div class="ctrl-row">
            <div>
              <div class="field-label"><span>Mission Cabin Preset (Auto-Load)</span></div>
              <select id="mc-preset">{preset_options_html}</select>
            </div>
            <div>
              <div class="field-label"><span>Cabin Material</span></div>
              <select id="mc-material">{material_options_html}</select>
            </div>
          </div>

          <div class="sliders-box">
            <div class="slider-group">
              <div class="field-label">
                <span>O<sub>2</sub> Concentration (% vol)</span>
                <span id="lbl-o2" class="field-val">34.0% O₂</span>
              </div>
              <input id="sl-o2" type="range" min="16.0" max="100.0" step="0.5" value="34.0">
            </div>

            <div class="slider-group">
              <div class="field-label">
                <span>Gravity Regime (0.00 ISS · 0.16 Moon · 0.38 Mars · 1.00 Earth)</span>
                <span id="lbl-g" class="field-val">0.16 g</span>
              </div>
              <input id="sl-g" type="range" min="0.00" max="1.00" step="0.01" value="0.16">
            </div>

            <div id="p-slider-wrap" class="slider-group" style="display:none;margin-top:12px;">
              <div class="field-label">
                <span>Total Cabin Pressure (kPa)</span>
                <span id="lbl-p" class="field-val">56.5 kPa (8.2 psi)</span>
              </div>
              <input id="sl-p" type="range" min="20.0" max="101.3" step="0.5" value="56.5">
            </div>

            <label class="toggle-row">
              <input id="chk-hold" type="checkbox" checked>
              <span>Keep breathable oxygen constant by automatically adjusting nitrogen</span>
            </label>
          </div>

          <div class="tgrid">
            <div class="tcard">
              <div class="tcard-lbl">Total Pressure</div>
              <div id="asi-val-p" class="tcard-val">62.6 <span style="font-size:13px;font-weight:500;color:#D9D8D3;">kPa</span></div>
              <div id="asi-sub-p" class="tcard-sub">9.1 psi total</div>
            </div>
            <div class="tcard">
              <div class="tcard-lbl">Breathable O₂</div>
              <div id="asi-val-ppo2" class="tcard-val">21.3 <span style="font-size:13px;font-weight:500;color:#D9D8D3;">kPa</span></div>
              <div class="tcard-sub">Ideal: 21.3 kPa</div>
            </div>
            <div class="tcard">
              <div class="tcard-lbl">Material Fire Limit</div>
              <div id="asi-val-limit" class="tcard-val">27.0<span style="font-size:13px;font-weight:500;color:#D9D8D3;">% O₂</span></div>
              <div class="tcard-sub">Burns above this %</div>
            </div>
            <div class="tcard">
              <div class="tcard-lbl">Safety Margin</div>
              <div id="asi-val-margin" class="tcard-val">-7.0 <span style="font-size:13px;font-weight:500;">pts</span></div>
              <div class="tcard-sub">Limit minus O₂</div>
            </div>
          </div>
        </div>

        <div>
          <div class="svg-card">
            <svg id="asi-zone-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 86"
                 style="width:100%;height:92px;display:block;font-family:'IBM Plex Mono',monospace;">
              <rect width="600" height="86" rx="6" fill="#07080A"/>
              <text x="52" y="42" text-anchor="end" fill="#D9D8D3" font-size="11" font-weight="600">15% O₂</text>
              <text x="546" y="42" text-anchor="start" fill="#D9D8D3" font-size="11" font-weight="600">100% O₂</text>

              <rect id="asi-zone-safe" x="60" y="26" width="60" height="24" rx="3" fill="#2F63B0"/>
              <rect id="asi-zone-caut" x="120" y="26" width="20" height="24" fill="#FF8A2A"/>
              <rect id="asi-zone-dang" x="140" y="26" width="398" height="24" rx="3" fill="#F2600F"/>

              <line id="asi-sweet-line" x1="110" y1="22" x2="110" y2="54" stroke="#E8F1FA" stroke-width="2" stroke-dasharray="3 3"/>
              <text id="asi-sweet-text" x="110" y="15" text-anchor="middle" fill="#E8F1FA" font-size="11" font-weight="600" letter-spacing="0.5">SAFE LIMIT: 24.0% O₂</text>

              <path id="asi-zone-pointer" d="M166,54 l-6,10 h12 z" fill="#F2600F"/>
              <text id="asi-zone-sel-text" x="166" y="79" text-anchor="middle" fill="#F4F3EF" font-size="11" font-weight="700" letter-spacing="0.5">CURRENT: 34.0% O₂</text>
            </svg>
          </div>

          <div id="asi-live-banner" class="banner high">34.0% O₂ · Nomex (meta-aramid) — CRITICAL FIRE HAZARD</div>

          <div class="insight-box">
            <div class="insight-row">
              <span id="asi-ins-sweet-tag" class="tag" style="background:#FF8A2A;">LOWER O₂</span>
              <div id="asi-ins-sweet-body"></div>
            </div>
            <div class="insight-row">
              <span id="asi-ins-phys-tag" class="tag" style="background:#6FA3D8;">BREATHING OK</span>
              <div id="asi-ins-phys-body"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- =========================================================================
     VIEW 3: SIMULATION WORKSPACE
     ========================================================================= -->
<div id="view-simulation" class="os-view">
  <div class="workspace-wrap">
    <div class="workspace-card sim-layout">
      <div class="ws-header-row">
        <div>
          <div class="ws-tag">02 // INTERACTIVE MICROGRAVITY SIMULATION ZONE</div>
          <div class="ws-title">Live Simulation — Hazard &amp; Flame Geometry</div>
        </div>
        <div style="display:flex;gap:8px;">
          <button id="btn-sim-to-hub" class="switch-bubble-btn">← Command Hub</button>
          <button id="btn-sim-to-dash" class="switch-bubble-btn">Dashboard →</button>
        </div>
      </div>

      <div class="vis-box">
        <svg id="asi-stickman-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 320"
             style="width:100%;height:420px;display:block;font-family:'IBM Plex Mono',monospace;">
          {iss_background_layer}
          {scene_low}
          {scene_med}
          {scene_high}
          {suppression_cloud}
          {iss_foreground_hud}
        </svg>
      </div>

      <div class="eclss-box">
        <div class="eclss-top">
          <div>
            <div class="eclss-title">STATION ECLSS / FDS CLOSED-LOOP SAFETY LINK</div>
            <div id="eclss-method-preview" class="eclss-sub">Ready: Auto-detects fire &amp; executes optimal suppression for this scenario</div>
          </div>
          <button id="btn-auto-suppress" class="eclss-trigger-btn">⚡ Simulate Fire &amp; Auto-Suppression</button>
        </div>

        <div id="eclss-log-panel" class="eclss-log">
          <div id="eclss-step-1" class="eclss-step">
            <div class="eclss-dot"></div>
            <div id="eclss-step-1-txt"></div>
          </div>
          <div id="eclss-step-2" class="eclss-step">
            <div class="eclss-dot"></div>
            <div id="eclss-step-2-txt"></div>
          </div>
          <div id="eclss-step-3" class="eclss-step">
            <div class="eclss-dot"></div>
            <div id="eclss-step-3-txt"></div>
          </div>
          <div id="eclss-step-4" class="eclss-step">
            <div class="eclss-dot"></div>
            <div id="eclss-step-4-txt"></div>
          </div>
        </div>
      </div>

      <div class="theater-dock">
        <div>
          <div class="field-label">
            <span>Live O<sub>2</sub> (% vol)</span>
            <span id="dock-lbl-o2" class="field-val">34.0% O₂</span>
          </div>
          <input id="dock-sl-o2" type="range" min="16.0" max="100.0" step="0.5" value="34.0">
        </div>
        <div>
          <div class="field-label">
            <span>Gravity (0g → 1g)</span>
            <span id="dock-lbl-g" class="field-val">0.16 g</span>
          </div>
          <input id="dock-sl-g" type="range" min="0.00" max="1.00" step="0.01" value="0.16">
        </div>
        <div>
          <div class="field-label"><span>Cabin Material</span></div>
          <select id="dock-material">{material_options_html}</select>
        </div>
      </div>

      <div class="phys-summary-grid">
        <div class="phys-pill">
          <div class="phys-pill-lbl">Flame Shape</div>
          <div id="asi-pill-geom" class="phys-pill-val">Partial-G Plume</div>
        </div>
        <div class="phys-pill">
          <div class="phys-pill-lbl">Auto-Suppression Agent</div>
          <div id="asi-pill-ox" class="phys-pill-val">CO₂ + Water Mist</div>
        </div>
        <div class="phys-pill">
          <div class="phys-pill-lbl">Rising Hot Gas</div>
          <div id="asi-pill-buoy" class="phys-pill-val">40% of Earth (0.16g)</div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
(function() {{
  const MATERIALS = {json.dumps(materials_dict)};
  const PRESETS = {json.dumps(presets_dict)};
  const COLORS = {json.dumps(RISK_COLOR)};
  const PAL = {json.dumps(PALETTE)};
  const SAFETY_MARGIN = {SAFETY_MARGIN_PCT};

  // =========================================================================
  // DUAL-VIDEO HARDWARE CROSSFADE ENGINE (Infinite Loop from t = 8.0s to End)
  // =========================================================================
  const vidA      = document.getElementById("flama-vid-a");
  const vidB      = document.getElementById("flama-vid-b");
  const fileInput = document.getElementById("custom-video-input");

  let activeLayer = "A";
  let crossfading = false;
  const TARGET_LOOP_START = 8.0; // Loop starts strictly at 8.0s as requested
  const CROSSFADE_SEC     = 0.50; // Smooth 0.50s overlap before the end of the clip

  function getLoopStart(dur) {{
    if (!dur || isNaN(dur)) return TARGET_LOOP_START;
    return dur > 8.35 ? TARGET_LOOP_START : Math.max(0.0, dur * 0.55);
  }}

  function monitorDualVideoLoop() {{
    const fg = activeLayer === "A" ? vidA : vidB;
    const bg = activeLayer === "A" ? vidB : vidA;

    if (fg && fg.readyState >= 2 && fg.duration > 0) {{
      const dur = fg.duration;
      const loopStart = getLoopStart(dur);
      const triggerTime = Math.max(loopStart + 0.15, dur - CROSSFADE_SEC);

      if (!crossfading && fg.currentTime >= triggerTime) {{
        crossfading = true;
        // Start standby layer from exactly 8.0s and crossfade smoothly
        bg.currentTime = loopStart;
        bg.play().catch(() => {{}});
        bg.style.opacity = "1";
        fg.style.opacity = "0";

        setTimeout(() => {{
          fg.pause();
          fg.currentTime = loopStart; // Pre-park old layer at 8.0s so zero seek lag next cycle
          activeLayer = activeLayer === "A" ? "B" : "A";
          crossfading = false;
        }}, CROSSFADE_SEC * 1000);
      }}
    }}
    requestAnimationFrame(monitorDualVideoLoop);
  }}

  function initCoverVideos() {{
    if (!vidA || !vidA.getAttribute("src")) return;
    activeLayer = "A";
    crossfading = false;
    vidA.style.opacity = "1";
    vidB.style.opacity = "0";

    vidA.addEventListener("loadedmetadata", () => {{
      vidA.currentTime = 0.0; // Play full ignition (0.0s -> 8.0s) once on startup
      vidA.play().catch(() => {{}});
    }}, {{ once: true }});

    vidB.addEventListener("loadedmetadata", () => {{
      vidB.pause();
      vidB.currentTime = getLoopStart(vidB.duration); // Pre-buffer standby layer at 8.0s
    }}, {{ once: true }});

    // Safety fallback if a tab was backgrounded and `ended` fires
    [vidA, vidB].forEach((v) => {{
      v.addEventListener("ended", () => {{
        v.currentTime = getLoopStart(v.duration);
        v.play().catch(() => {{}});
      }});
    }});

    vidA.play().catch(() => {{}});
  }}

  initCoverVideos();
  requestAnimationFrame(monitorDualVideoLoop);

  // Allow user to load any .mp4 file on the fly via the top-right pill
  fileInput.addEventListener("change", (e) => {{
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    vidA.src = url;
    vidB.src = url;
    initCoverVideos();
  }});

  // =========================================================================
  // VIEW NAVIGATION & TOP-LEFT BLUISH MICROGRAVITY FLAME SPHERE LOGO
  // =========================================================================
  const topNavBar = document.getElementById("top-nav-bar");
  const views = {{
    cover:      document.getElementById("view-cover"),
    hub:        document.getElementById("view-hub"),
    dashboard:  document.getElementById("view-dashboard"),
    simulation: document.getElementById("view-simulation"),
  }};
  const menuBtns = {{
    hub:        document.getElementById("menu-btn-hub"),
    dashboard:  document.getElementById("menu-btn-dashboard"),
    simulation: document.getElementById("menu-btn-simulation"),
  }};
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

  function switchView(target) {{
    Object.keys(views).forEach((k) => {{
      views[k].classList.toggle("active", k === target);
    }});
    Object.keys(menuBtns).forEach((k) => {{
      menuBtns[k].classList.toggle("active", k === target);
    }});
    topNavBar.classList.toggle("visible", target !== "cover");
    document.body.style.background = target === "cover" ? "#000000" : "#07080A";
    hamMenu.classList.remove("open");
    setTimeout(syncIframeHeight, 40);
    setTimeout(syncIframeHeight, 260);
  }}

  logoHome.addEventListener("click", () => {{
    document.getElementById("hub-cmd-drawer").classList.remove("open");
    switchView("hub");
  }});

  document.getElementById("si-enter-console-btn").addEventListener("click", () => {{
    switchView("hub");
  }});

  menuBtns.hub.addEventListener("click",        () => switchView("hub"));
  menuBtns.dashboard.addEventListener("click",  () => switchView("dashboard"));
  menuBtns.simulation.addEventListener("click", () => switchView("simulation"));
  document.getElementById("menu-btn-cover").addEventListener("click", () => switchView("cover"));

  document.getElementById("btn-dash-to-hub").addEventListener("click", () => switchView("hub"));
  document.getElementById("btn-dash-to-sim").addEventListener("click", () => switchView("simulation"));
  document.getElementById("btn-sim-to-hub").addEventListener("click",  () => switchView("hub"));
  document.getElementById("btn-sim-to-dash").addEventListener("click", () => switchView("dashboard"));

  document.getElementById("orb-dashboard").addEventListener("click",  () => switchView("dashboard"));
  document.getElementById("orb-simulation").addEventListener("click", () => switchView("simulation"));

  // -------------------------------------------------------------------------
  // COMMAND BAR & VOICE RECORDING ENGINE (On Hub)
  // -------------------------------------------------------------------------
  const cmdInput  = document.getElementById("hub-cmd-input");
  const voiceBtn  = document.getElementById("hub-voice-btn");
  const cmdDrawer = document.getElementById("hub-cmd-drawer");
  const cmdOutput = document.getElementById("hub-cmd-output");
  const cmdClose  = document.getElementById("hub-cmd-close");

  function executeCommandQuery(rawQuery) {{
    const q = (rawQuery || "").trim();
    if (!q) return;
    const ql = q.toLowerCase();

    if (ql === "/dashboard" || ql === "dashboard" || ql === "open dashboard") {{
      switchView("dashboard");
      return;
    }}
    if (ql === "/simulation" || ql === "simulation" || ql === "open simulation") {{
      switchView("simulation");
      return;
    }}

    const matName = elMat.value;
    const o2 = parseFloat(slO2.value);
    const g  = parseFloat(slG.value);
    const hold = chkHold.checked;
    const pKpa = hold ? Math.min(21.3 / (o2 / 100.0), 101.325) : parseFloat(slP.value);
    const strat = selectOptimalSuppression(matName, o2, g, pKpa);
    const lowGPenalty = g < 0.98 ? 2.0 * Math.max(0.0, Math.min(1.0, (0.98 - g) / 0.30)) : 0.0;
    const limit = (MATERIALS[matName] || 29.0) - lowGPenalty;
    const margin = limit - o2;

    cmdOutput.innerHTML = `
      <div style="margin-bottom:6px;color:#F4F3EF;"><b>Scenario Query:</b> "${{q}}"</div>
      <div style="margin-bottom:6px;">
        • <b>Immediate Diagnosis [BASS-01, SAFFIRE-IV]:</b> Evaluating <b>${{matName}}</b> at <b>${{o2.toFixed(1)}}% O₂</b>, <b>${{pKpa.toFixed(1)}} kPa</b>, and <b>${{g.toFixed(2)}}g</b>.
        Flammability limit is <b>${{limit.toFixed(1)}}% O₂</b> (Margin: <b style="color:${{margin <= 0 ? '#F2600F' : '#6FA3D8'}};">${{margin >= 0 ? '+' : ''}}${{margin.toFixed(1)}} pts</b>).
      </div>
      <div style="margin-bottom:6px;">
        • <b>Artemis Extrapolation [ACME-EFIELD]:</b> ${{g <= 0.02 ? 'In 0.00g microgravity, flame forms a ghostly blue diffusion sphere fed by ventilation drafts.' : 'Partial-gravity buoyancy (' + Math.round(Math.sqrt(g)*100) + '% of Earth) accelerates oxidizer transport to the pyrolysis base.'}}
      </div>
      <div>
        • <b>Autonomous ECLSS Protocol [FLEX-02]:</b> Cut overhead HVAC duct flow to 0 cm/s and deploy <b>${{strat.agentShort}}</b>.
      </div>
    `;
    cmdDrawer.classList.add("open");
    syncIframeHeight();
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

  let isRecording = false;
  let recognition = null;
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRec) {{
    try {{
      recognition = new SpeechRec();
      recognition.lang = "en-US";
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.onresult = (event) => {{
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {{
          transcript += event.results[i][0].transcript;
        }}
        cmdInput.value = transcript;
        if (event.results[event.results.length - 1].isFinal) {{
          voiceBtn.classList.remove("recording");
          isRecording = false;
          executeCommandQuery(transcript);
        }}
      }};
      recognition.onerror = () => {{
        if (isRecording) triggerSimulatedVoiceDictation();
      }};
      recognition.onend = () => {{
        voiceBtn.classList.remove("recording");
        isRecording = false;
      }};
    }} catch (err) {{
      recognition = null;
    }}
  }}

  function triggerSimulatedVoiceDictation() {{
    const sampleVoice = "Short-circuit on Nomex harness at 34% O2 in lunar gravity — evaluate suppression.";
    cmdInput.value = "";
    let idx = 0;
    const typeTimer = setInterval(() => {{
      idx += 3;
      cmdInput.value = sampleVoice.slice(0, idx);
      if (idx >= sampleVoice.length) {{
        clearInterval(typeTimer);
        voiceBtn.classList.remove("recording");
        isRecording = false;
        executeCommandQuery(sampleVoice);
      }}
    }}, 35);
  }}

  voiceBtn.addEventListener("click", () => {{
    if (isRecording) {{
      isRecording = false;
      voiceBtn.classList.remove("recording");
      if (recognition) {{
        try {{ recognition.stop(); }} catch (e) {{}}
      }}
      return;
    }}
    isRecording = true;
    voiceBtn.classList.add("recording");
    if (recognition) {{
      try {{
        recognition.start();
      }} catch (e) {{
        triggerSimulatedVoiceDictation();
      }}
    }} else {{
      triggerSimulatedVoiceDictation();
    }}
  }});

  // -------------------------------------------------------------------------
  // DASHBOARD & SIMULATION CONTROLS
  // -------------------------------------------------------------------------
  const btnSuppress = document.getElementById("btn-auto-suppress");
  const eclssLog    = document.getElementById("eclss-log-panel");

  const elPreset   = document.getElementById("mc-preset");
  const elMat      = document.getElementById("mc-material");
  const slO2       = document.getElementById("sl-o2");
  const slG        = document.getElementById("sl-g");
  const slP        = document.getElementById("sl-p");
  const chkHold    = document.getElementById("chk-hold");
  const wrapP      = document.getElementById("p-slider-wrap");

  const dockSlO2   = document.getElementById("dock-sl-o2");
  const dockSlG    = document.getElementById("dock-sl-g");
  const dockMat    = document.getElementById("dock-material");
  const dockLblO2  = document.getElementById("dock-lbl-o2");
  const dockLblG   = document.getElementById("dock-lbl-g");

  const lblO2 = document.getElementById("lbl-o2");
  const lblG  = document.getElementById("lbl-g");
  const lblP  = document.getElementById("lbl-p");

  let suppressTimers = [];

  function clearSuppressionTimers() {{
    suppressTimers.forEach((t) => clearTimeout(t));
    suppressTimers = [];
    document.getElementById("asi-suppress-cloud").style.opacity = "0";
    document.getElementById("asi-duct-txt").textContent = "CABIN VENTILATION DUCT · FORCED AIRFLOW";
    document.getElementById("asi-duct-txt").setAttribute("fill", "#D9D8D3");
    btnSuppress.textContent = "⚡ Simulate Fire & Auto-Suppression";
  }}

  function syncIframeHeight() {{
    if (window.frameElement) {{
      const h = document.body.scrollHeight;
      if (h > 200) window.frameElement.style.height = (h + 20) + "px";
    }}
  }}

  function selectOptimalSuppression(matName, o2, g, pKpa) {{
    const gRegime = g <= 0.02 ? "0.00g microgravity" : (g < 0.98 ? `${{g.toFixed(2)}}g partial gravity` : "1.00g gravity");
    let agentShort = "Fine Water Mist (PFE)";
    let agentDetail = "";

    if (o2 >= 36.0) {{
      agentShort = "Helium + CO₂ Rapid Dilution";
      agentDetail = `At <b>${{o2.toFixed(1)}}% O₂</b> (${{pKpa.toFixed(1)}} kPa), water mist alone cannot quench the enriched oxidizer zone. Station injects <b>Helium + CO₂ inert gas dilution</b> [FLEX-02] to drop local O₂ below the flammability limit while cooling the reaction zone.`;
    }} else if (matName.includes("Polyethylene") || matName.includes("PMMA")) {{
      agentShort = "CO₂ Flooding + Cool-Flame Guard";
      agentDetail = `<b>${{matName}}</b> melts into a volatile pool that can transition into invisible 500–800 K <b>cool flames</b> [FLEX-01, ACME-BRE]. Station deploys <b>CO₂ gas flooding</b> plus continuous IR/laser monitoring to prevent reignition.`;
    }} else {{
      agentShort = "Fine Water Mist + CO₂ Local Jet";
      agentDetail = `For <b>${{matName}}</b> at <b>${{o2.toFixed(1)}}% O₂</b> in ${{gRegime}}, station deploys <b>ISS Portable Fine Water Mist (PFE) + localized CO₂</b> [FLEX-02], absorbing latent heat without toxic Halon byproducts.`;
    }}

    return {{ agentShort, agentDetail, gRegime }};
  }}

  function updateAll() {{
    clearSuppressionTimers();
    eclssLog.style.display = "none";

    const matName = elMat.value;
    const loiBase = MATERIALS[matName] || 29.0;
    const o2   = parseFloat(slO2.value);
    const g    = parseFloat(slG.value);
    const hold = chkHold.checked;

    dockSlO2.value = o2;
    dockSlG.value  = g;
    dockMat.value  = matName;
    dockLblO2.textContent = `${{o2.toFixed(1)}}% O₂`;
    dockLblG.textContent  = `${{g.toFixed(2)}} g`;

    const needle = document.getElementById("orb1-needle");
    if (needle) {{
      const deg = -120 + (o2 - 16.0) / 84.0 * 240.0;
      needle.setAttribute("transform", `rotate(${{deg.toFixed(1)}} 50 50)`);
    }}

    wrapP.style.display = hold ? "none" : "block";
    const pKpa = hold ? Math.min(21.3 / (o2 / 100.0), 101.325) : parseFloat(slP.value);
    const pPsi = pKpa / 6.894757;

    lblO2.textContent = `${{o2.toFixed(1)}}% O₂`;
    lblG.textContent  = `${{g.toFixed(2)}} g`;
    lblP.textContent  = `${{pKpa.toFixed(1)}} kPa (${{pPsi.toFixed(1)}} psi)`;

    const lowGPenalty = g < 0.98 ? 2.0 * Math.max(0.0, Math.min(1.0, (0.98 - g) / 0.30)) : 0.0;
    const limit = loiBase - lowGPenalty;
    const margin = limit - o2;
    const ppo2 = pKpa * o2 / 100.0;

    let risk = "Low", statusText = "NOMINAL ENVELOPE", badge = "NOMINAL", sevColor = "#6FA3D8";
    if (margin <= 0) {{
      risk = "High"; statusText = "CRITICAL FIRE HAZARD"; badge = "CRITICAL"; sevColor = "#F2600F";
    }} else if (margin < SAFETY_MARGIN) {{
      risk = "Medium"; statusText = "CAUTION BUFFER"; badge = "CAUTION"; sevColor = "#FF8A2A";
    }} else if (margin < SAFETY_MARGIN + 3.0) {{
      risk = "Low"; statusText = "LOW WARNING BUFFER"; badge = "ELEVATED"; sevColor = "#FFC27A";
    }}

    let sev = 0.15;
    if (margin <= 0) sev = Math.min(1.0, 0.62 + 0.38 * Math.min(-margin, 8.0) / 8.0);
    else if (margin < SAFETY_MARGIN) sev = 0.30 + 0.30 * (1.0 - margin / SAFETY_MARGIN);
    else sev = Math.max(0.08, 0.30 - 0.22 * Math.min(margin - SAFETY_MARGIN, 12.0) / 12.0);

    const xFire = limit - SAFETY_MARGIN;
    const xMax = 100.0 * 21.3 / 56.5;
    const xMin = Math.floor(100.0 * 21.3 / 101.325 * 2.0) / 2.0;
    const xSweet = Math.floor(Math.min(xFire, xMax) * 2.0) / 2.0;
    const hasSweet = xSweet >= xMin;

    // 1. Telemetry Cards
    document.getElementById("asi-val-p").innerHTML = `${{pKpa.toFixed(1)}} <span style="font-size:13px;font-weight:500;color:#D9D8D3;">kPa</span>`;
    document.getElementById("asi-sub-p").textContent = `${{pPsi.toFixed(1)}} psi total`;
    document.getElementById("asi-val-ppo2").innerHTML = `${{ppo2.toFixed(1)}} <span style="font-size:13px;font-weight:500;color:#D9D8D3;">kPa</span>`;
    document.getElementById("asi-val-limit").innerHTML = `${{limit.toFixed(1)}}<span style="font-size:13px;font-weight:500;color:#D9D8D3;">% O₂</span>`;
    const elMar = document.getElementById("asi-val-margin");
    elMar.innerHTML = `${{margin > 0 ? '+' : '-'}}${{Math.abs(margin).toFixed(1)}} <span style="font-size:13px;font-weight:500;">pts</span>`;
    elMar.style.color = sevColor;

    // 2. Strictly Separated 3-Lane Zone Bar
    const xCoord = (pct) => 60 + 478 * (Math.min(Math.max(pct, 15.0), 100.0) - 15.0) / 85.0;
    const safeEnd = xCoord(limit - SAFETY_MARGIN);
    const limX = xCoord(limit);
    const cx = xCoord(o2);
    const cxLabel = Math.min(Math.max(cx, 120.0), 480.0);

    document.getElementById("asi-zone-safe").setAttribute("width", Math.max(safeEnd - 60, 0).toFixed(1));
    const zCaut = document.getElementById("asi-zone-caut");
    zCaut.setAttribute("x", safeEnd.toFixed(1));
    zCaut.setAttribute("width", Math.max(limX - safeEnd, 0).toFixed(1));
    const zDang = document.getElementById("asi-zone-dang");
    zDang.setAttribute("x", limX.toFixed(1));
    zDang.setAttribute("width", Math.max(538 - limX, 0).toFixed(1));

    const swLine = document.getElementById("asi-sweet-line");
    const swText = document.getElementById("asi-sweet-text");
    if (hasSweet) {{
      const sx = xCoord(xSweet);
      const sxText = Math.min(Math.max(sx, 145.0), 455.0);
      swLine.setAttribute("x1", sx.toFixed(1));
      swLine.setAttribute("x2", sx.toFixed(1));
      swLine.setAttribute("opacity", "1");
      swText.setAttribute("x", sxText.toFixed(1));
      swText.setAttribute("fill", "#E8F1FA");
      swText.textContent = `SAFE LIMIT: ${{xSweet.toFixed(1)}}% O₂`;
    }} else {{
      swLine.setAttribute("opacity", "0");
      swText.setAttribute("x", "300");
      swText.setAttribute("fill", "#FFC27A");
      swText.textContent = "FLAMMABLE EVEN IN NORMAL AIR (21% O₂)";
    }}

    const pointer = document.getElementById("asi-zone-pointer");
    pointer.setAttribute("d", `M${{cx.toFixed(1)}},54 l-6,10 h12 z`);
    pointer.setAttribute("fill", sevColor);

    const selText = document.getElementById("asi-zone-sel-text");
    selText.setAttribute("x", cxLabel.toFixed(1));
    selText.textContent = `CURRENT: ${{o2.toFixed(1)}}% O₂`;

    // 3. Banner & Plain-English Explanations
    const banner = document.getElementById("asi-live-banner");
    banner.className = `banner ${{risk.toLowerCase()}}`;
    banner.innerHTML = `${{o2.toFixed(1)}}% O<sub>2</sub> · ${{matName}} — ${{statusText}}`;

    const swTag = document.getElementById("asi-ins-sweet-tag");
    const swBody = document.getElementById("asi-ins-sweet-body");
    if (!hasSweet) {{
      swTag.style.background = "#F2600F";
      swTag.style.color = "#F4F3EF";
      swTag.textContent = "UNSAFE MATERIAL";
      swBody.innerHTML = `<b>${{matName}} burns even in normal Earth air.</b> Because its fire limit is only <b>${{limit.toFixed(1)}}% O<sub>2</sub></b>, lowering oxygen cannot make it safe without suffocating the crew. Replace this material or cover it with a fire barrier.`;
    }} else {{
      if (o2 > xSweet + 0.25) {{
        swTag.style.background = "#FF8A2A";
        swTag.style.color = "#07080A";
        swTag.textContent = "LOWER O₂";
        swBody.innerHTML = `<b>Reduce oxygen to ${{xSweet.toFixed(1)}}% O<sub>2</sub>.</b> At your current setting (<b>${{o2.toFixed(1)}}% O<sub>2</sub></b>), ${{matName}} can easily catch fire. Dropping to <b>${{xSweet.toFixed(1)}}% O<sub>2</sub></b> stops fire spread while keeping the air completely breathable.`;
      }} else if (o2 < xSweet - 0.25) {{
        swTag.style.background = "#FFC27A";
        swTag.style.color = "#07080A";
        swTag.textContent = "EXTRA MARGIN";
        swBody.innerHTML = `<b>Safe up to ${{xSweet.toFixed(1)}}% O<sub>2</sub>.</b> ${{matName}} is well below its fire limit here. You can safely raise oxygen up to <b>${{xSweet.toFixed(1)}}% O<sub>2</sub></b> to lower cabin pressure and speed up spacewalk preparation.`;
      }} else {{
        swTag.style.background = "#6FA3D8";
        swTag.style.color = "#07080A";
        swTag.textContent = "IDEAL O₂";
        swBody.innerHTML = `<b>Optimal oxygen setting (${{xSweet.toFixed(1)}}% O<sub>2</sub>).</b> You are at the exact sweet spot that maximizes mission efficiency while keeping ${{matName}} safely protected against fire.`;
      }}
    }}

    const physTag = document.getElementById("asi-ins-phys-tag");
    const physBody = document.getElementById("asi-ins-phys-body");
    if (ppo2 < 18.0) {{
      physTag.style.background = "#F2600F";
      physTag.style.color = "#F4F3EF";
      physTag.textContent = "LOW OXYGEN";
      physBody.innerHTML = `<b>Crew hypoxia risk:</b> The air is too thin for astronauts to breathe safely. Increase the oxygen percentage or raise cabin pressure.`;
    }} else if (ppo2 > 23.5) {{
      physTag.style.background = "#FF8A2A";
      physTag.style.color = "#07080A";
      physTag.textContent = "HIGH OXYGEN";
      physBody.innerHTML = `<b>Oxygen toxicity risk:</b> Breathable oxygen is too concentrated for long missions. Lower cabin pressure or reduce the oxygen percentage.`;
    }} else {{
      physTag.style.background = "#6FA3D8";
      physTag.style.color = "#07080A";
      physTag.textContent = "BREATHING OK";
      physBody.innerHTML = `<b>Crew air is completely safe:</b> Breathable oxygen matches healthy Earth sea-level conditions for the astronauts.`;
    }}

    // 4. Update Live Cabin Simulation
    const badgeRect = document.getElementById("asi-svg-badge-rect");
    const badgeTxt  = document.getElementById("asi-svg-badge-text");
    if (risk === "High") {{
      badgeRect.setAttribute("fill", "#8C2A08");
      badgeRect.setAttribute("stroke", "#F2600F");
      badgeTxt.setAttribute("fill", "#F4F3EF");
    }} else if (risk === "Medium") {{
      badgeRect.setAttribute("fill", "#8C2A08");
      badgeRect.setAttribute("stroke", "#FF8A2A");
      badgeTxt.setAttribute("fill", "#FFC27A");
    }} else {{
      badgeRect.setAttribute("fill", "#12306E");
      badgeRect.setAttribute("stroke", "#6FA3D8");
      badgeTxt.setAttribute("fill", "#E8F1FA");
    }}
    badgeTxt.textContent = `RISK · ${{badge}}`;

    document.getElementById("asi-svg-grav-text").textContent = g <= 0.02
      ? "0.00G BLUE DIFFUSION"
      : `${{g.toFixed(2)}}G BUOYANT PLUME`;
    document.getElementById("asi-svg-caption").textContent = risk === "Low"
      ? "CABIN RACK NOMINAL — MATERIAL BELOW FLAMMABILITY LIMIT"
      : (risk === "Medium"
          ? (g <= 0.02 ? "CAUTION — 0G BLUE DIFFUSION SPHERE, SUPPRESSION VIABLE" : "CAUTION — PARTIAL-G BUOYANT FLAME, SUPPRESSION VIABLE")
          : (g <= 0.02 ? "CRITICAL — EXPANDING 0G BLUE DIFFUSION FIRE IN CABIN RACK" : "CRITICAL — RAPID BUOYANT PLUME PROPAGATION & SMOKE ALARM"));

    const smokeBox = document.getElementById("asi-smoke-box");
    const smokeLed = document.getElementById("asi-smoke-led");
    const smokeTxt = document.getElementById("asi-smoke-txt");
    const chFrame  = document.getElementById("asi-chamber-frame");
    if (risk === "Low") {{
      smokeLed.setAttribute("fill", "#6FA3D8");
      smokeTxt.textContent = "SAME SENSOR: STANDBY";
      smokeTxt.setAttribute("fill", "#D9D8D3");
      smokeBox.setAttribute("stroke", "#1A1D23");
      chFrame.setAttribute("stroke", "#1A1D23");
    }} else if (risk === "Medium") {{
      smokeLed.setAttribute("fill", "#FF8A2A");
      smokeTxt.textContent = "SAME SENSOR: AEROSOL";
      smokeTxt.setAttribute("fill", "#FFC27A");
      smokeBox.setAttribute("stroke", "#FF8A2A");
      chFrame.setAttribute("stroke", "#FF8A2A");
    }} else {{
      smokeLed.setAttribute("fill", "#F2600F");
      smokeTxt.textContent = "SAME SENSOR: SMOKE ALARM!";
      smokeTxt.setAttribute("fill", "#F4F3EF");
      smokeBox.setAttribute("stroke", "#F2600F");
      chFrame.setAttribute("stroke", "#F2600F");
    }}

    document.getElementById("asi-scene-low").style.opacity  = risk === "Low" ? "1" : "0";
    document.getElementById("asi-scene-med").style.opacity  = risk === "Medium" ? "1" : "0";
    document.getElementById("asi-scene-high").style.opacity = risk === "High" ? "1" : "0";

    const floatFactor = Math.max(0.0, Math.min(1.0, (0.35 - g) / 0.35));
    const yFig = (188.0 - 16.0 * floatFactor).toFixed(1);
    const tiltLowMed = (-7.0 * floatFactor).toFixed(1);
    const tiltHigh = (-10.0 - 4.0 * floatFactor).toFixed(1);

    document.getElementById("asi-sb-low").setAttribute("transform", `translate(178 ${{yFig}}) rotate(${{tiltLowMed}})`);
    document.getElementById("asi-sb-med").setAttribute("transform", `translate(178 ${{yFig}}) rotate(${{tiltLowMed}})`);
    document.getElementById("asi-sb-high").setAttribute("transform", `translate(152 ${{yFig}}) rotate(${{tiltHigh}})`);

    const plumeWeight = g > 0 ? Math.min(1.0, Math.pow(g / 0.25, 0.7)) : 0.0;
    document.getElementById("asi-med-0g").style.opacity = (1.0 - plumeWeight).toFixed(2);
    document.getElementById("asi-med-1g").style.opacity = plumeWeight.toFixed(2);
    document.getElementById("asi-med-ellipse").setAttribute("ry", (24 + 12 * Math.min(g, 1.0)).toFixed(1));

    const sc = (0.72 + 0.44 * sev).toFixed(2);
    document.getElementById("asi-flame-scaler").setAttribute("transform", `translate(405 202) scale(${{sc}})`);
    document.getElementById("asi-fire-0g").style.opacity = (1.0 - plumeWeight).toFixed(2);
    document.getElementById("asi-fire-1g").style.opacity = plumeWeight.toFixed(2);

    // 5. Physics Summary Pills & Optimal Suppression Preview
    const strat = selectOptimalSuppression(matName, o2, g, pKpa);
    document.getElementById("eclss-method-preview").innerHTML =
      `Selected Protocol for <b>${{matName}}</b> (${{o2.toFixed(1)}}% O₂, ${{g.toFixed(2)}}g): <b>HVAC Cut + ${{strat.agentShort}}</b>`;

    const elGeom = document.getElementById("asi-pill-geom");
    const elOx   = document.getElementById("asi-pill-ox");
    const elBuoy = document.getElementById("asi-pill-buoy");
    if (g <= 0.02) {{
      elGeom.textContent = "Blue Diffusion Sphere";
      elGeom.style.color = "#6FA3D8";
      elBuoy.textContent = "None (Hot air stays still)";
    }} else if (g < 0.98) {{
      elGeom.textContent = "Partial-G Teardrop Plume";
      elGeom.style.color = "#FFC27A";
      elBuoy.textContent = `${{Math.round(Math.sqrt(g) * 100)}}% of Earth (${{g.toFixed(2)}}g)`;
    }} else {{
      elGeom.textContent = "1G Rising Teardrop";
      elGeom.style.color = "#FF8A2A";
      elBuoy.textContent = "100% Normal Earth (1.00g)";
    }}
    elOx.textContent = strat.agentShort;

    syncIframeHeight();
  }}

  // -------------------------------------------------------------------------
  // LIVE STATION LINK: SIMULATE CUSTOM SCENARIO FIRE & AUTO-SUPPRESSION
  // -------------------------------------------------------------------------
  btnSuppress.addEventListener("click", () => {{
    clearSuppressionTimers();

    const matName = elMat.value;
    const o2   = parseFloat(slO2.value);
    const g    = parseFloat(slG.value);
    const hold = chkHold.checked;
    const pKpa = hold ? Math.min(21.3 / (o2 / 100.0), 101.325) : parseFloat(slP.value);
    const strat = selectOptimalSuppression(matName, o2, g, pKpa);

    const plumeWeight = g > 0 ? Math.min(1.0, Math.pow(g / 0.25, 0.7)) : 0.0;
    document.getElementById("asi-fire-0g").style.opacity = (1.0 - plumeWeight).toFixed(2);
    document.getElementById("asi-fire-1g").style.opacity = plumeWeight.toFixed(2);

    document.getElementById("eclss-step-1-txt").innerHTML =
      `<b>[T+0.0s] FDS DETECTION (SAME LASER):</b> Ignition detected on <b>${{matName}}</b> at <b>${{o2.toFixed(1)}}% O₂</b> (${{pKpa.toFixed(1)}} kPa, ${{strat.gRegime}}).`;
    document.getElementById("eclss-step-2-txt").innerHTML =
      `<b>[T+1.1s] HVAC DAMPER ISOLATION (BASS-II):</b> Station automatically closes overhead ventilation duct (flow → 0 cm/s) to starve the flame of forced oxidizer.`;
    document.getElementById("eclss-step-3-txt").innerHTML =
      `<b>[T+2.3s] OPTIMAL AGENT INJECTION (FLEX):</b> ${{strat.agentDetail}}`;
    document.getElementById("eclss-step-4-txt").innerHTML =
      `<b>[T+4.0s] EXTINGUISHED &amp; SCRUBBING (SAFFIRE-IV):</b> Flame extinguished. ECLSS CO₂/CO scrubbers active; IR sensors locked on to prevent cool-flame reignition.`;

    ["eclss-step-1", "eclss-step-2", "eclss-step-3", "eclss-step-4"].forEach((id) => {{
      document.getElementById(id).classList.remove("active");
    }});
    eclssLog.style.display = "block";
    btnSuppress.textContent = "⚡ Executing Auto-Suppression...";
    syncIframeHeight();

    document.getElementById("eclss-step-1").classList.add("active");
    document.getElementById("asi-scene-low").style.opacity  = "0";
    document.getElementById("asi-scene-med").style.opacity  = "0";
    document.getElementById("asi-scene-high").style.opacity = "1";
    document.getElementById("asi-flame-scaler").setAttribute("transform", "translate(405 202) scale(1.15)");
    document.getElementById("asi-smoke-led").setAttribute("fill", "#F2600F");
    document.getElementById("asi-smoke-txt").textContent = "SAME SENSOR: SMOKE ALARM!";
    document.getElementById("asi-smoke-txt").setAttribute("fill", "#F4F3EF");
    document.getElementById("asi-smoke-box").setAttribute("stroke", "#F2600F");
    document.getElementById("asi-chamber-frame").setAttribute("stroke", "#F2600F");
    document.getElementById("asi-svg-badge-rect").setAttribute("fill", "#8C2A08");
    document.getElementById("asi-svg-badge-rect").setAttribute("stroke", "#F2600F");
    document.getElementById("asi-svg-badge-text").setAttribute("fill", "#F4F3EF");
    document.getElementById("asi-svg-badge-text").textContent = "FDS · FIRE DETECTED";
    document.getElementById("asi-svg-caption").textContent = "STAGE 1/4 — CUSTOM SCENARIO FIRE DETECTED BY STATION TELEMETRY";

    suppressTimers.push(setTimeout(() => {{
      document.getElementById("eclss-step-2").classList.add("active");
      document.getElementById("asi-duct-txt").textContent = "HVAC DAMPER: CLOSED (0 cm/s · OXIDIZER STARVED)";
      document.getElementById("asi-duct-txt").setAttribute("fill", "#FFC27A");
      document.getElementById("asi-flame-scaler").setAttribute("transform", "translate(405 202) scale(0.75)");
      document.getElementById("asi-svg-badge-rect").setAttribute("fill", "#8C2A08");
      document.getElementById("asi-svg-badge-rect").setAttribute("stroke", "#FF8A2A");
      document.getElementById("asi-svg-badge-text").setAttribute("fill", "#FFC27A");
      document.getElementById("asi-svg-badge-text").textContent = "ECLSS · HVAC CUT";
      document.getElementById("asi-svg-caption").textContent = "STAGE 2/4 — VENTILATION ISOLATED TO STOP FORCED O₂ SUPPLY";
    }}, 1100));

    suppressTimers.push(setTimeout(() => {{
      document.getElementById("eclss-step-3").classList.add("active");
      document.getElementById("asi-scene-high").style.opacity = "0";
      document.getElementById("asi-scene-med").style.opacity  = "1";
      document.getElementById("asi-suppress-cloud").style.opacity = "1";
      document.getElementById("asi-svg-badge-rect").setAttribute("fill", "#12306E");
      document.getElementById("asi-svg-badge-rect").setAttribute("stroke", "#6FA3D8");
      document.getElementById("asi-svg-badge-text").setAttribute("fill", "#E8F1FA");
      document.getElementById("asi-svg-badge-text").textContent = "SUPPRESSING FIRE";
      document.getElementById("asi-svg-caption").textContent =
        `STAGE 3/4 — DEPLOYING ${{strat.agentShort.toUpperCase()}} INTO RACK`;
    }}, 2300));

    suppressTimers.push(setTimeout(() => {{
      document.getElementById("eclss-step-4").classList.add("active");
      document.getElementById("asi-suppress-cloud").style.opacity = "0";
      document.getElementById("asi-scene-med").style.opacity = "0";
      document.getElementById("asi-scene-low").style.opacity = "1";
      document.getElementById("asi-smoke-led").setAttribute("fill", "#6FA3D8");
      document.getElementById("asi-smoke-txt").textContent = "SAME SENSOR: CLEARED";
      document.getElementById("asi-smoke-txt").setAttribute("fill", "#E8F1FA");
      document.getElementById("asi-smoke-box").setAttribute("stroke", "#6FA3D8");
      document.getElementById("asi-chamber-frame").setAttribute("stroke", "#6FA3D8");
      document.getElementById("asi-svg-badge-rect").setAttribute("fill", "#12306E");
      document.getElementById("asi-svg-badge-rect").setAttribute("stroke", "#6FA3D8");
      document.getElementById("asi-svg-badge-text").setAttribute("fill", "#E8F1FA");
      document.getElementById("asi-svg-badge-text").textContent = "CABIN SAFE · EXTINGUISHED";
      document.getElementById("asi-svg-caption").textContent =
        "STAGE 4/4 — FIRE EXTINGUISHED · ECLSS SCRUBBERS & COOL-FLAME GUARD ACTIVE";
      btnSuppress.textContent = "⚡ Re-Run Fire & Auto-Suppression";
      syncIframeHeight();
    }}, 4000));
  }});

  elPreset.addEventListener("change", () => {{
    const p = PRESETS[elPreset.value];
    if (p) {{
      slG.value    = p.g;
      slO2.value   = p.o2;
      chkHold.checked = p.hold;
      slP.value    = p.p;
      updateAll();
    }}
  }});

  slO2.addEventListener("input", () => {{ elPreset.value = "Custom Configuration"; updateAll(); }});
  slG.addEventListener("input",  () => {{ elPreset.value = "Custom Configuration"; updateAll(); }});
  slP.addEventListener("input",  () => {{ elPreset.value = "Custom Configuration"; updateAll(); }});
  elMat.addEventListener("change", updateAll);
  chkHold.addEventListener("change", updateAll);

  dockSlO2.addEventListener("input", () => {{
    slO2.value = dockSlO2.value;
    elPreset.value = "Custom Configuration";
    updateAll();
  }});
  dockSlG.addEventListener("input", () => {{
    slG.value = dockSlG.value;
    elPreset.value = "Custom Configuration";
    updateAll();
  }});
  dockMat.addEventListener("change", () => {{
    elMat.value = dockMat.value;
    updateAll();
  }});

  window.addEventListener("resize", syncIframeHeight);
  if (window.ResizeObserver) {{
    new ResizeObserver(syncIframeHeight).observe(document.body);
  }}

  updateAll();
}})();
</script>
</body>
</html>"""
    components.html(html_doc, height=780, scrolling=False)


# ---------------------------------------------------------------------------
# Legacy wrappers
# ---------------------------------------------------------------------------
def render_o2_optimizer(
    material: str | None = None,
    gravity_g: float | None = None,
    *,
    default_o2: float = 34.0,
    key: str = "env",
    show_header: bool = True,
) -> O2Assessment:
    del show_header
    mat = material or "Nomex (meta-aramid)"
    g = 0.16 if gravity_g is None else gravity_g
    a = assess_o2(mat, default_o2, 56.5, g)
    st.session_state[f"{key}_snapshot"] = {
        "material": a.material, "gravity_g": a.gravity_g, "o2_pct": a.o2_pct,
        "pressure_kpa": a.pressure_kpa, "ppo2_kpa": a.ppo2_kpa, "limit_pct": a.limit_pct,
        "margin_pct": a.margin_pct, "risk_level": a.risk_level, "severity": a.severity,
    }
    return a


def render_stickman_animation(
    risk_level: str,
    caption: str | None = None,
    *,
    severity: float | None = None,
    gravity_g: float = 0.0,
    height: int = 310,
) -> str:
    del caption, severity, gravity_g, height
    return risk_level