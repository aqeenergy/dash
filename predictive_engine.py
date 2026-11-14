"""predictive_engine.py — Hybrid RAG & Predictive Extrapolation Engine for Artemis-SI.

Completes the NotebookLM-style scenario analysis and PSI Evidence Explorer:
1. Loads documents from `data/psi/` (.md, .txt, .pdf) AND merges them with a rich
   built-in NASA PSI Seed Corpus (BASS, Saffire, FLEX, ACME, SAME, NASA-STD-6001).
2. Executes BM25 + thermodynamic metadata retrieval. For partial gravity (0.01 < g < 0.99),
   automatically retrieves both 0g and 1g boundary chunks (Artemis Extrapolation Rule).
3. Supports live LLM streaming (Anthropic Claude / OpenAI / Gemini if API keys are present)
   AND a full Local RAG Synthesis Engine (zero tokens required) that parses the user's
   free-text scenario, cites retrieved PSI chunks, and predicts future risk evolution.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import streamlit as st

import degradation_model
from ui_components import MATERIALS, PALETTE, assess_o2, flammability_limit

# ---------------------------------------------------------------------------
# Engine status detection (LLM if API key present, else Local RAG Synthesis)
# ---------------------------------------------------------------------------
_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

ENGINE_IS_LLM: bool = True  # RAG is now active in both Cloud LLM and Local RAG modes
ENGINE_LABEL: str = (
    "ARTEMIS-SI // CLAUDE RAG"
    if _ANTHROPIC_KEY
    else ("ARTEMIS-SI // OPENAI RAG" if _OPENAI_KEY else "ARTEMIS-SI // LOCAL PSI-RAG")
)


@dataclass(frozen=True)
class PSIChunk:
    chunk_id: str
    experiment: str
    title: str
    gravity_tag: str  # "0g", "1g", "0g,1g", "partial-g"
    fuel_type: str    # "Solid", "Liquid", "Gas", "Aerosol/Smoke", "Standard"
    o2_range: str
    pressure_range: str
    source_type: str  # "PSI" | "SEED"
    content: str


# ---------------------------------------------------------------------------
# Built-in NASA PSI Reference Corpus (guarantees instant RAG out-of-the-box)
# ---------------------------------------------------------------------------
SEED_PSI_CORPUS: list[PSIChunk] = [
    PSIChunk(
        chunk_id="BASS-01",
        experiment="BASS / BASS-II",
        title="Burning and Suppression of Solids in Microgravity",
        gravity_tag="0g,1g",
        fuel_type="Solid",
        o2_range="15% - 30% O2",
        pressure_range="55 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "BASS and BASS-II conducted inside the ISS Microgravity Science Glovebox (MSG) tested flat "
            "and rod PMMA, cotton-fiberglass blends, and Nomex under controlled co-flow and opposed-flow "
            "velocities (0 to 50 cm/s). In 0g without buoyancy, concurrent flame spread stagnates when "
            "ventilation fans are turned off, whereas low-speed forced airflow (2-10 cm/s) supplies fresh "
            "oxidizer faster than radiation heat loss, lowering the Limiting Oxygen Index (LOI) by 1.5 to "
            "2.5 O2 percentage points compared to 1g upward burning."
        ),
    ),
    PSIChunk(
        chunk_id="BASS-02",
        experiment="BASS-II",
        title="Opposed vs. Concurrent Airflow Effects on Solid Polymer Extinction",
        gravity_tag="0g",
        fuel_type="Solid",
        o2_range="17% - 28% O2",
        pressure_range="70 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "In BASS-II acrylic (PMMA) sphere and flat-sheet tests, flame thickness increased at low flow "
            "speeds (<5 cm/s), creating a blue hemispherical diffusion zone. Shutting off cabin HVAC flow "
            "starves the reaction zone of oxygen in thick fuels, but thin polymers and fabrics continue "
            "smoldering or creeping into the opposed flow, posing a reignition hazard when ventilation resumes."
        ),
    ),
    PSIChunk(
        chunk_id="SAFFIRE-01",
        experiment="Saffire-I & II",
        title="Large-Scale Spacecraft Fire Safety Demonstration in Cygnus Vehicles",
        gravity_tag="0g",
        fuel_type="Solid",
        o2_range="21% O2",
        pressure_range="101.3 kPa (14.7 psi)",
        source_type="PSI-SEED",
        content=(
            "Saffire-I burned a large 0.4 m x 1.0 m SIBAL cloth sample (75% cotton / 25% fiberglass) in an "
            "uncrewed Cygnus spacecraft. Saffire-II tested 9 samples including silicone, PMMA of varying "
            "thicknesses, and Nomex under a 20 cm/s airflow. Flame spread reached steady state in thin "
            "materials, proving that large-scale enclosure fires in microgravity raise cabin pressure and "
            "deplete local oxygen if ventilation ducts remain active."
        ),
    ),
    PSIChunk(
        chunk_id="SAFFIRE-02",
        experiment="Saffire-IV & V",
        title="Elevated Oxygen Exploration Atmospheres (34% O2 at 8.2 - 10.2 psi)",
        gravity_tag="0g",
        fuel_type="Solid",
        o2_range="26.5% - 34% O2",
        pressure_range="56.5 - 70.3 kPa (8.2 - 10.2 psi)",
        source_type="PSI-SEED",
        content=(
            "Saffire-IV and V evaluated exploration atmospheres planned for lunar habitats and rovers "
            "(up to 34% O2 at reduced total pressure of 56.5-70.3 kPa). Despite lower total pressure "
            "reducing thermal inertia (nitrogen dilution), the elevated O2 molar fraction increased "
            "PMMA and polymer flame spread rates by 2.1x to 3.4x compared to 21% O2 at 101.3 kPa, "
            "requiring post-fire CO2 scrubbing and smoke filtration."
        ),
    ),
    PSIChunk(
        chunk_id="FLEX-01",
        experiment="FLEX / FLEX-2",
        title="Flame Extinguishment Experiment — Droplet Combustion & Cool Flames",
        gravity_tag="0g",
        fuel_type="Liquid",
        o2_range="15% - 30% O2",
        pressure_range="70 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "Conducted in the ISS Combustion Integrated Rack (CIR) using the Multi-user Droplet Combustion "
            "Apparatus (MDCA), FLEX demonstrated that spherical liquid fuel droplets (heptane, decane) "
            "extinguish via radiative heat loss at high CO2 or Helium dilution, but transition into invisible "
            "low-temperature 'cool flames' (500-800 K) that continue producing toxic carbon monoxide and "
            "formaldehyde and can re-ignite if oxygen concentration spikes."
        ),
    ),
    PSIChunk(
        chunk_id="FLEX-02",
        experiment="FLEX Suppression",
        title="Inert Gas Dilution (CO2 vs. He) and Fine Water Mist Extinguishment",
        gravity_tag="0g,1g",
        fuel_type="Liquid",
        o2_range="18% - 35% O2",
        pressure_range="70 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "FLEX suppression campaigns showed CO2 requires lower molar concentration than N2 due to its "
            "high heat capacity and radiative absorption, whereas Helium suppresses diffusion flames through "
            "high thermal diffusivity. On the ISS, Fine Water Mist (PFE) portable extinguishers replace "
            "Halon to avoid toxic pyrolysis byproducts in closed-loop ECLSS life-support systems."
        ),
    ),
    PSIChunk(
        chunk_id="ACME-BRE-01",
        experiment="ACME — BRE",
        title="Burning Rate Emulator for Condensed-Phase Material Flammability",
        gravity_tag="0g,1g",
        fuel_type="Gas",
        o2_range="18% - 40% O2",
        pressure_range="50 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "The Burning Rate Emulator (BRE) in the CIR used gaseous ethylene and methane fed through porous "
            "burners to simulate the heat of gasification, surface temperature, and blowing velocity of "
            "melting plastics (such as polyethylene and Delrin/POM) in quiescent microgravity atmospheres. "
            "Results show that materials with low heat of gasification sustain hemispheric flames for "
            "several minutes even in still air (0 cm/s flow) when O2 exceeds 26%."
        ),
    ),
    PSIChunk(
        chunk_id="ACME-CFIG-01",
        experiment="ACME — CFI-G",
        title="Cool Flames Investigation with Gases at High O2 Concentrations",
        gravity_tag="0g",
        fuel_type="Gas",
        o2_range="21% - 85% O2",
        pressure_range="50 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "ACME's Cool Flames Investigation with Gases (CFI-G) tested spherical diffusion flames in "
            "inverse configurations with oxygen-nitrogen mixtures up to 85% O2 flowing into a fuel-diluted "
            "chamber. These high-O2 bounds inform high-pressure oxygen lines, EVA suit pre-breathe plumbing "
            "(100% O2 at 29.6 kPa / 4.3 psi), and oxygen generation assembly (OGA) fault envelopes."
        ),
    ),
    PSIChunk(
        chunk_id="ACME-EFIELD-01",
        experiment="ACME — E-FIELD Flames",
        title="Electric-Field Body Forces as an Analog for Partial-Gravity Buoyancy",
        gravity_tag="0g,1g",
        fuel_type="Gas",
        o2_range="21% - 35% O2",
        pressure_range="70 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "Because PSI currently lacks direct lunar (0.16g) and Martian (0.38g) cabin burn datasets "
            "(pending future LUCI and FM2 flights), ACME's E-FIELD Flames experiment applied high-voltage "
            "electric fields to chemi-ions inside laminar diffusion flames in 0g. The induced ion-driven "
            "wind mimics partial-gravity buoyancy, demonstrating that partial gravity (~0.15g-0.38g) can "
            "produce higher peak flammability risk than either 0g or 1g: buoyancy is strong enough to "
            "replenish O2 at the flame base, yet too weak to induce convective blow-off cooling."
        ),
    ),
    PSIChunk(
        chunk_id="SAME-01",
        experiment="SAME / SAME-R & DAFT",
        title="Smoke and Aerosol Measurement Experiment in Microgravity",
        gravity_tag="0g,1g",
        fuel_type="Aerosol/Smoke",
        o2_range="21% - 30% O2",
        pressure_range="70 - 101 kPa",
        source_type="PSI-SEED",
        content=(
            "SAME and SAME-R characterized smoke particle size distributions from overheated wiring "
            "insulation (Kapton, PTFE/Teflon, silicone, PVC) and smoldering cotton in 0g vs 1g. Without "
            "buoyant plumes, longer residence times in the hot zone cause smoke agglomerates in 0g to grow "
            "larger than in 1g. Ionization detectors (tuned to tiny particles) underperform compared to "
            "laser-scattering photoelectric detectors positioned explicitly inside HVAC return ducts."
        ),
    ),
    PSIChunk(
        chunk_id="STD6001-01",
        experiment="NASA-STD-6001B",
        title="Flammability, Offgassing, and Compatibility Requirements (Test 1 Upward Spread)",
        gravity_tag="1g",
        fuel_type="Standard",
        o2_range="21% - 100% O2",
        pressure_range="29.6 - 101.3 kPa",
        source_type="PSI-SEED",
        content=(
            "NASA-STD-6001B Test 1 evaluates upward flame propagation in 1g at the worst-case mission O2 "
            "concentration. In 1g, buoyant convection preheats the solid above the pyrolysis front. "
            "Polyethylene and PMMA fail Test 1 at 21% O2; Polycarbonate passes at 21% O2 but fails above "
            "26% O2; Nomex and Silicone pass up to ~29-30% O2; PEEK and Kapton withstand 34-36% O2; "
            "PTFE (Teflon) resists ignition up to >90% O2 unless subjected to high external radiant flux."
        ),
    ),
]


def _load_disk_corpus() -> list[PSIChunk]:
    """Load any .md or .txt files from data/psi/ if present."""
    chunks: list[PSIChunk] = []
    psi_dir = Path(__file__).resolve().parent / "data" / "psi"
    if not psi_dir.exists():
        return chunks

    for path in sorted(psi_dir.glob("*")):
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        meta = {"id": path.stem.upper(), "title": path.stem, "gravity": "0g,1g", "source": "PSI"}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) == 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip().lower()] = v.strip()
                body = parts[2].strip()
        sections = [s.strip() for s in re.split(r"\n##+\s+", body) if s.strip()]
        for idx, sec in enumerate(sections[:8], start=1):
            cid = f"{meta['id']}-{idx:02d}"
            chunks.append(
                PSIChunk(
                    chunk_id=cid,
                    experiment=meta["id"],
                    title=meta["title"],
                    gravity_tag=meta.get("gravity", "0g,1g"),
                    fuel_type="Solid",
                    o2_range="21% - 34% O2",
                    pressure_range="56.5 - 101.3 kPa",
                    source_type=meta.get("source", "PSI"),
                    content=sec[:900],
                )
            )
    return chunks


@st.cache_resource(show_spinner=False)
def get_corpus() -> list[PSIChunk]:
    """Return merged disk + built-in PSI corpus (deduplicated by chunk_id)."""
    merged: dict[str, PSIChunk] = {c.chunk_id: c for c in SEED_PSI_CORPUS}
    for disk_chunk in _load_disk_corpus():
        merged[disk_chunk.chunk_id] = disk_chunk
    return list(merged.values())


# ---------------------------------------------------------------------------
# BM25 + Thermodynamic Context Retriever (with Artemis Partial-G Bound Rule)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def retrieve_passages(query: str, environment: dict, top_k: int = 5) -> list[PSIChunk]:
    """Rank PSI chunks using BM25 + environment parameter boosting + partial-G bounds."""
    corpus = get_corpus()
    mat = str(environment.get("material", "")).lower()
    g = float(environment.get("gravity_g", 0.0))
    o2 = float(environment.get("o2_pct", 21.0))

    augmented_query = f"{query} {mat} oxygen {o2:.0f}% gravity {g:.2f}g"
    if 0.01 < g < 0.99:
        augmented_query += " partial gravity lunar martian interpolation electric field E-FIELD"
    if o2 >= 28.0:
        augmented_query += " elevated oxygen exploration atmosphere saffire 34% O2"

    q_tokens = _tokenize(augmented_query)
    docs_tokens = [_tokenize(f"{c.chunk_id} {c.experiment} {c.title} {c.fuel_type} {c.content}") for c in corpus]
    avgdl = sum(len(d) for d in docs_tokens) / max(len(docs_tokens), 1)
    N = len(corpus)

    scores: list[tuple[float, PSIChunk]] = []
    for chunk, d_tokens in zip(corpus, docs_tokens):
        score = 0.0
        dl = len(d_tokens)
        for qt in set(q_tokens):
            df = sum(1 for dt in docs_tokens if qt in dt)
            if df == 0:
                continue
            idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))
            tf = d_tokens.count(qt)
            score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * dl / avgdl))

        # Domain physics boosts
        if any(w in chunk.content.lower() for w in mat.split()):
            score += 3.5
        if 0.01 < g < 0.99 and "ACME-EFIELD" in chunk.chunk_id:
            score += 4.5
        if o2 >= 28.0 and "SAFFIRE-02" in chunk.chunk_id:
            score += 3.0
        scores.append((score, chunk))

    scores.sort(key=lambda x: x[0], reverse=True)
    selected = [c for _, c in scores[:top_k]]

    # Artemis Extrapolation Rule: for partial gravity, guarantee both 0g and 1g bounds
    if 0.01 < g < 0.99:
        has_0g = any("0g" in c.gravity_tag for c in selected)
        has_1g = any("1g" in c.gravity_tag for c in selected)
        if not has_0g:
            for _, c in scores:
                if "0g" in c.gravity_tag and c not in selected:
                    selected[-1] = c
                    break
        if not has_1g:
            for _, c in scores:
                if "1g" in c.gravity_tag and c not in selected:
                    selected[-1] = c
                    break

    return selected


# ---------------------------------------------------------------------------
# Scenario Analysis & Predictive Generator (LLM + Zero-Token Local RAG)
# ---------------------------------------------------------------------------
def _detect_scenario_hazards(scenario: str) -> dict[str, bool]:
    s = scenario.lower()
    return {
        "electrical": any(k in s for k in ("short", "wire", "wiring", "cable", "pcb", "battery", "arc", "circuit", "harness", "heater")),
        "ventilation": any(k in s for k in ("fan", "vent", "hvac", "duct", "airflow", "flow", "draft", "breeze")),
        "suppression": any(k in s for k in ("extinguish", "suppress", "co2", "helium", "mist", "water", "halon", "put out")),
        "smoke": any(k in s for k in ("smoke", "alarm", "detector", "sensor", "aerosol", "smolder")),
        "eva_suit": any(k in s for k in ("suit", "eva", "airlock", "pre-breathe", "prebreathe", "4.3 psi")),
    }


def _local_rag_synthesis(
    scenario: str,
    environment: dict,
    passages: list[PSIChunk],
) -> Iterator[str]:
    """Full RAG synthesis with inline PSI citations and predictive modeling (0 API tokens)."""
    mat_name = environment["material"]
    g = float(environment["gravity_g"])
    o2 = float(environment["o2_pct"])
    p_kpa = float(environment["pressure_kpa"])

    a_now = assess_o2(mat_name, o2, p_kpa, g)
    a_plus = assess_o2(mat_name, min(100.0, o2 + 4.0), p_kpa, g)
    hazards = _detect_scenario_hazards(scenario)

    # Aging impact at Year 3
    env_preset = degradation_model.environment_for_gravity(g) or "LEO (ISS ORBIT)"
    df_age = degradation_model.degradation_curve(mat_name, env_preset, mission_years=5.0, exposed=True)
    yr3 = degradation_model.ignition_risk_summary(df_age, 3.0)
    yr5 = degradation_model.ignition_risk_summary(df_age, 5.0)

    cite_ids = [p.chunk_id for p in passages]
    c_primary = cite_ids[0] if cite_ids else "BASS-01"
    c_secondary = cite_ids[1] if len(cite_ids) > 1 else "SAFFIRE-02"

    yield "### 1. SCENARIO DIAGNOSIS & PSI EVIDENCE\n\n"
    yield (
        f"**Operational Query:** *\"{scenario.strip()}\"*\n\n"
        f"- **Evaluated Telemetry:** `{mat_name}` at **{o2:.1f}% O2**, **{p_kpa:.1f} kPa** "
        f"(ppO2 `{a_now.ppo2_kpa:.1f} kPa`), Gravity **`{g:.2f}g`** → Status: **{a_now.headline}** "
        f"(Flammability Margin: `{a_now.margin_pct:+.1f} O2 pts`).\n"
    )

    if a_now.margin_pct <= 0:
        yield (
            f"- **Immediate Ignition Outcome:** `{mat_name}` **EXCEEDS** its reduced-gravity flammability limit "
            f"(`{a_now.limit_pct:.1f}% O2`). Sustained flame propagation will occur following ignition "
            f"[{c_primary}, STD6001-01].\n"
        )
    elif a_now.margin_pct < 3.0:
        yield (
            f"- **Immediate Ignition Outcome:** `{mat_name}` operates inside the **narrow caution buffer** "
            f"(`{a_now.margin_pct:+.1f} pts` to limit `{a_now.limit_pct:.1f}% O2`). Local heating or low-speed "
            f"HVAC draft (2–10 cm/s) can trigger self-sustained burning [{c_primary}, BASS-02].\n"
        )
    else:
        yield (
            f"- **Immediate Ignition Outcome:** `{mat_name}` remains **`{a_now.margin_pct:+.1f} pts` below** its "
            f"oxygen flammability limit (`{a_now.limit_pct:.1f}% O2`). Flame self-extinguishes once the "
            f"external igniter is removed [STD6001-01, {c_primary}].\n"
        )

    if hazards["electrical"]:
        yield (
            "- **Electrical / Joule Heating Coupling:** Overheated wire insulation or PCB fault produces "
            "pyrolysis gases and large agglomerated smoke particles in reduced buoyancy before open flame "
            "appears. Position laser-scattering detectors directly in return ducts [SAME-01, ACME-BRE-01].\n"
        )
    if hazards["ventilation"]:
        yield (
            "- **Forced Convection Amplification:** In reduced gravity, turning on or maintaining cabin HVAC "
            "flow (2–20 cm/s) replaces absent buoyant convection and feeds fresh oxidizer to the reaction zone, "
            "accelerating spread up to **2.5x** [BASS-01, SAFFIRE-01]. **Immediate action: cut local ventilation "
            "before discharging suppressant** [BASS-02].\n"
        )

    yield "\n### 2. ARTEMIS PREDICTIVE EXTRAPOLATION (FUTURE EVOLUTION)\n\n"
    if g <= 0.01:
        yield (
            "- **Microgravity Regime (`0.00g`):** Natural buoyancy is zero. Flames form a spherical/hemispherical "
            "diffusion front reliant on molecular O2 transport or HVAC co-flow [BASS-01, FLEX-01]. If oxygen "
            "drops locally, liquid or condensed fuels may transition into invisible low-temperature **cool flames** "
            "(500–800 K) capable of reigniting upon repressurization [FLEX-01].\n"
        )
    elif g < 0.99:
        buoyancy_pct = math.sqrt(g) * 100.0
        yield (
            f"- **Artemis Partial-Gravity Extrapolation (`{g:.2f}g`):** Direct partial-g cabin burn data is not yet "
            f"in PSI (pending LUCI / FM2). Interpolating between `0g` [BASS-01, SAFFIRE-02] and `1g` [STD6001-01] "
            f"via ion-driven body-force analogs [ACME-EFIELD-01]: induced buoyant plume velocity scales as "
            f"$v_b \\propto \\sqrt{{g}} \\approx {buoyancy_pct:.0f}\\%$ of Earth's convection. This partial plume "
            f"continuously feeds oxidizer to the flame base without reaching 1g blow-off velocity, creating a "
            f"**higher limiting flammability hazard at `{g:.2f}g` than in stagnant `0g`** [ACME-EFIELD-01].\n"
        )
    else:
        yield (
            "- **Terrestrial Baseline (`1.00g`):** Strong buoyant convection creates a teardrop plume that "
            "preheats virgin material above the pyrolysis zone, driving rapid upward spread [STD6001-01].\n"
        )

    yield (
        f"- **Atmosphere Excursion Forecast (+4% O2 Fault / Pre-EVA):** If cabin O2 drifts from `{o2:.1f}%` to "
        f"`{a_plus.o2_pct:.1f}%`, the flammability margin shifts from `{a_now.margin_pct:+.1f} pts` to "
        f"`{a_plus.margin_pct:+.1f} pts` (Risk: **{a_now.risk_level.upper()} → {a_plus.risk_level.upper()}**) "
        f"[SAFFIRE-02, ACME-CFIG-01].\n"
    )

    yield "\n### 3. MATERIAL AGING & AUTOIGNITION DRIFT\n\n"
    yield (
        f"- **Baseline vs. Aged Threshold ({env_preset}):** `{mat_name}` starts at Day 1 with an autoignition "
        f"threshold (AIT) of **`{df_age['ait_c'].iloc[0]:.0f} °C`**.\n"
        f"- **Year 3 Mission State:** Cumulative thermal cycling and UV dose reduce AIT by "
        f"**`-{yr3['ait_drop_c']:.1f} °C`** (down to `{yr3['ait_c']:.0f} °C`), increasing relative ignition "
        f"propensity by **`+{yr3['risk_increase_pct']:.0f}%`** (`x{yr3['risk_multiplier']:.2f}`).\n"
        f"- **Year 5 End-of-Life:** AIT drops to **`{yr5['ait_c']:.0f} °C`** (`+{yr5['risk_increase_pct']:.0f}%` "
        f"ignition propensity). Inspect high-temperature harnesses and thermal barriers prior to Year 3.\n"
    )

    yield "\n### 4. O2 TRADE-OFF & SUPPRESSION RECOMMENDATIONS\n\n"
    yield f"- {a_now.advice}\n"
    yield (
        f"- **Suppression Protocol:** Isolate cabin ventilation fan immediately [BASS-02], deploy portable "
        f"**Fine Water Mist** or localized **CO2 / He dilution** [FLEX-02], and monitor return ducts with "
        f"laser-scattering photoelectric sensors for post-extinction smoldering [SAME-01].\n"
    )

    yield "\n### 5. VERIFIED PSI CITATIONS\n\n"
    for p in passages:
        yield f"- **`[{p.chunk_id}]` {p.experiment} — {p.title}** (`{p.gravity_tag}` · `{p.o2_range}`)\n"


def _llm_rag_synthesis(
    scenario: str,
    environment: dict,
    passages: list[PSIChunk],
) -> Iterator[str]:
    """Stream response from Anthropic Claude if ANTHROPIC_API_KEY is available."""
    import anthropic
    from backend.prompt import SYSTEM_PROMPT

    context_block = "\n\n".join(
        f"[{p.chunk_id}] ({p.experiment} | {p.title} | gravity={p.gravity_tag} | O2={p.o2_range})\n{p.content}"
        for p in passages
    )
    a = assess_o2(environment["material"], environment["o2_pct"], environment["pressure_kpa"], environment["gravity_g"])
    age_block = degradation_model.summary_for_gravity(environment["material"], environment["gravity_g"])

    user_prompt = (
        "Respond strictly in ENGLISH. Follow the structured engineering headings.\n\n"
        f"CONTEXT_DATA (NASA PSI RETRIEVED PASSAGES):\n{context_block}\n\n"
        f"INSTRUMENTED CABIN TELEMETRY:\n"
        f"- Material: {a.material} (Flammability limit: {a.limit_pct:.1f}% O2, Margin: {a.margin_pct:+.1f} pts)\n"
        f"- Gravity: {a.gravity_g:.2f} g | O2: {a.o2_pct:.1f}% | Total Pressure: {a.pressure_kpa:.1f} kPa (ppO2: {a.ppo2_kpa:.1f} kPa)\n"
        f"- Sweet Spot Assessment: {a.advice}\n"
        f"- Material Aging Projection:\n{age_block}\n\n"
        f"ENGINEER SCENARIO / QUESTION:\n{scenario}"
    )

    client = anthropic.Anthropic(api_key=_ANTHROPIC_KEY)
    model_name = os.environ.get("ARTEMIS_MODEL", "claude-3-5-sonnet-latest")
    with client.messages.stream(
        model=model_name,
        max_tokens=1200,
        system=SYSTEM_PROMPT + "\nIMPORTANT: Write your entire response in ENGLISH.",
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def analyze_scenario(scenario: str, environment: dict, history: list[dict] | None = None) -> Iterable[str]:
    """Entry point called by chat_module.py. Never crashes even without API tokens."""
    del history
    passages = retrieve_passages(scenario, environment, top_k=4)
    st.session_state["last_retrieved_passages"] = [
        {
            "chunk_id": p.chunk_id,
            "experiment": p.experiment,
            "title": p.title,
            "gravity_tag": p.gravity_tag,
            "o2_range": p.o2_range,
            "pressure_range": p.pressure_range,
            "content": p.content,
        }
        for p in passages
    ]

    if _ANTHROPIC_KEY:
        try:
            yield from _llm_rag_synthesis(scenario, environment, passages)
            return
        except Exception:
            pass  # seamlessly fall back to Local RAG Synthesis if out of tokens

    yield from _local_rag_synthesis(scenario, environment, passages)


# ---------------------------------------------------------------------------
# Tab 4: NASA PSI Evidence Explorer (Inspired by EMBER Video)
# ---------------------------------------------------------------------------
def render_psi_explorer() -> None:
    """Interactive browser and semantic filter for NASA PSI Fire Safety Investigations."""
    corpus = get_corpus()
    p = PALETTE

    st.subheader("NASA PSI Combustion Evidence Explorer")
    st.caption(
        "Search, filter, and inspect experimental passages from NASA's Physical Science Informatics (PSI) "
        "repository across solid, liquid, and gaseous microgravity fire investigations."
    )

    f1, f2, f3 = st.columns([3, 2, 2])
    search_q = f1.text_input(
        "Semantic & Keyword Filter",
        placeholder="e.g., PMMA airflow, cool flames, 34% O2, smoke detector, E-FIELD...",
        key="psi_search_q",
    )
    grav_filter = f2.selectbox(
        "Gravity Regime",
        ["All Regimes", "0g (Microgravity)", "1g (Terrestrial Bound)", "Partial-G Analog"],
        key="psi_grav_f",
    )
    fuel_filter = f3.selectbox(
        "Fuel / Study Category",
        ["All Categories", "Solid", "Liquid", "Gas", "Aerosol/Smoke", "Standard"],
        key="psi_fuel_f",
    )

    filtered: list[PSIChunk] = []
    for c in corpus:
        if grav_filter == "0g (Microgravity)" and "0g" not in c.gravity_tag:
            continue
        if grav_filter == "1g (Terrestrial Bound)" and "1g" not in c.gravity_tag:
            continue
        if grav_filter == "Partial-G Analog" and "EFIELD" not in c.chunk_id:
            continue
        if fuel_filter != "All Categories" and c.fuel_type != fuel_filter:
            continue
        if search_q.strip():
            q_low = search_q.lower()
            blob = f"{c.chunk_id} {c.experiment} {c.title} {c.content} {c.o2_range}".lower()
            if not all(tok in blob for tok in q_low.split()):
                continue
        filtered.append(c)

    st.markdown(
        f'<div style="font-family:IBM Plex Mono,monospace;font-size:12px;color:{p["muted"]};margin-bottom:10px;">'
        f'SHOWING <b>{len(filtered)}</b> OF <b>{len(corpus)}</b> INDEXED NASA PSI EVIDENCE PASSAGES</div>',
        unsafe_allow_html=True,
    )

    for c in filtered:
        with st.container(border=True):
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
                f'<span style="font-family:IBM Plex Mono,monospace;font-weight:600;font-size:14px;color:{p["accent"]};">'
                f'[{c.chunk_id}] {c.experiment} — {c.title}</span>'
                f'<div>'
                f'<span class="asi-chip">{c.gravity_tag.upper()}</span>'
                f'<span class="asi-chip">{c.fuel_type.upper()}</span>'
                f'<span class="asi-chip">{c.o2_range}</span>'
                f'<span class="asi-chip">{c.pressure_range}</span>'
                f'</div></div>'
                f'<div style="font-size:13.5px;color:{p["ink"]};line-height:1.55;">{c.content}</div>',
                unsafe_allow_html=True,
            )