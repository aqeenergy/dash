"""psi_database.py — index the raw NASA PSI metadata in base_de_datos/ and build
every knowledge JSON that the FLAMA console and the Flammy agent expect.

base_de_datos/ is READ-ONLY: this module never writes, renames or deletes there.
All derived JSONs go to knowledge_cache/ (safe to delete; regenerated on start).

The folder holds the REAL downloads (PSI-XX.json metadata + experimental-table
CSV/XLSX + _todas_las_investigaciones_PSI.json). Flammy's knowledge layer and
ui_components, however, read derived files (experiments.json, materials.json,
rules.json, sources.json, fire_response.json, class_notes.json,
mission_presets.json) that were never generated — so the UI showed
"AWAITING PSI DATABASE" and Flammy always answered its fallback.

This module closes that gap:
  ensure_knowledge()        (re)builds the derived JSONs from the raw metadata.
                            A file the user edited by hand (newer than the raw
                            sources and this script) is left untouched.
  investigation_cards()     fast, cached card list for the Bubble-1 browser
                            (accession, title, DOI, fuel class, tables, blurb).

Classification notes: fuel class / topics per accession follow the official
investigation descriptions (see LEEME_datos_PSI.md); anything unknown falls
back to keyword inference over the real title/objective text. Rule thresholds
(O2 %, pressure) mirror the constants already used by the console. DOIs come
straight from each PSI-XX.json, as the LEEME requires for citation.

CLI:  python psi_database.py [--force]   -> rebuild + print a summary table.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DB_DIR = Path(__file__).resolve().parent / "base_de_datos"      # READ-ONLY source of truth
OUT_DIR = Path(__file__).resolve().parent / "knowledge_cache"     # every derived file lives here
INDEX_FILE = "psi_index.json"
BUILD_INFO_FILE = "knowledge_build_info.json"
CURATED_FILE = "experiments.json.py"  # curated flight-program entries (valid JSON saved with a .py name)

TARGETS = (
    "experiments.json", "materials.json", "rules.json", "sources.json",
    "fire_response.json", "class_notes.json", "mission_presets.json", INDEX_FILE,
)

# --------------------------------------------------------------------------
# Per-accession classification (from the official investigation descriptions)
# --------------------------------------------------------------------------
FUEL_CLASS = {
    10: "gaseous", 20: "gaseous", 21: "gaseous", 22: "gaseous", 23: "gaseous",
    106: "gaseous", 107: "gaseous", 159: "gaseous",
    39: "droplet", 68: "droplet", 69: "droplet",
    25: "solid", 26: "solid", 98: "solid", 99: "solid", 100: "solid",
    47: "detection", 101: "detection", 102: "detection",
    60: "analysis", 62: "analysis", 115: "analysis", 117: "analysis", 142: "analysis",
}
CTX_MATERIALS = {25: ["pmma", "fabric"], 26: ["pmma", "fabric"], 98: ["fabric"], 99: ["fabric", "pmma", "silicone"], 100: ["fabric"]}
CTX_TOPICS = {
    "solid": ["fire", "flame"], "droplet": ["flame", "extinguisher"], "gaseous": ["flame"],
    "detection": ["smoke", "gas"], "analysis": [],
}
FLOW_STUDIES = {25, 26, 98, 99, 100}          # imposed-airflow experiments
O2_MAX_PCT = {159: 85.0}                      # CFI-G ran up to 85 % O2
PARTIAL_G_ANALOG = {22}                       # E-FIELD: electric body force as gravity analog

_KEYWORD_FUEL = (
    ("droplet", r"droplet|methanol|heptane"),
    ("solid", r"solid|fabric|pmma|flame spread|material flammab"),
    ("detection", r"smoke|detector|aerosol|particulate"),
    ("gaseous", r"gaseous|coflow|jet flame|spherical flame|burner"),
)


def _num(accession: str) -> int:
    m = re.search(r"(\d+)", accession or "")
    return int(m.group(1)) if m else 0


def _fuel_for(num: int, text: str) -> str:
    if num in FUEL_CLASS:
        return FUEL_CLASS[num]
    low = text.lower()
    for fuel, pattern in _KEYWORD_FUEL:
        if re.search(pattern, low):
            return fuel
    return "analysis"


# --------------------------------------------------------------------------
# Raw metadata indexing
# --------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clip(text: str, limit: int = 230) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _count_rows(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return max(sum(1 for line in f if line.strip()) - 1, 0)
    except Exception:
        return 0


def build_index() -> list[dict[str, Any]]:
    """Parse every PSI-XX.json + its local tables into light card records."""
    cards: list[dict[str, Any]] = []
    for meta_path in sorted(DB_DIR.glob("PSI-*.json"), key=lambda p: _num(p.stem)):
        if not re.fullmatch(r"PSI-\d+", meta_path.stem):
            continue
        meta = _read_json(meta_path)
        if not isinstance(meta, dict):
            continue
        acc = meta.get("accession") or meta_path.stem
        num = _num(acc)
        title = str(meta.get("title") or acc).strip()
        acr = str(meta.get("investigationAcronym") or "").strip()
        doi = str(meta.get("doi") or "").strip()
        objective = str(meta.get("objective") or meta.get("approach") or "")
        fuel = _fuel_for(num, f"{title} {objective}")
        tables = sorted(DB_DIR.glob(f"{acc}_Experimental table_*.*")) + sorted(DB_DIR.glob(f"{acc}_Analyzed Data_*.*")) + sorted(DB_DIR.glob(f"{acc}_Science Documents_*.*"))
        rows = sum(_count_rows(t) for t in tables if t.suffix.lower() == ".csv")
        pubs = meta.get("publications")
        cards.append({
            "id": acc.lower(),
            "acc": acc,
            "num": num,
            "name": title,
            "acr": acr,
            "fuel": fuel,
            "hardware": _clip(meta.get("experimentHardware") or "", 60),
            "gravity": "ground" if fuel == "analysis" else "micro",
            "partial_analog": num in PARTIAL_G_ANALOG,
            "flow": num in FLOW_STUDIES,
            "o2max": O2_MAX_PCT.get(num),
            "mats": CTX_MATERIALS.get(num, []),
            "topics": CTX_TOPICS.get(fuel, []),
            "tables": len(tables),
            "table_names": [t.name for t in tables],
            "rows": rows,
            "pubs": len(pubs) if isinstance(pubs, list) else 0,
            "doi": doi,
            "url": f"https://doi.org/{doi}" if doi else "https://psi.nasa.gov/physci/repo",
            "blurb": _clip(objective),
            "kw": " ".join([acc, title, acr, fuel, str(meta.get("experimentHardware") or ""), objective]).lower(),
        })
    return cards


# --------------------------------------------------------------------------
# Derived knowledge files
# --------------------------------------------------------------------------
def _curated_experiments() -> dict[str, Any]:
    for name in ("experiments_curated.json", CURATED_FILE):
        raw = (DB_DIR / name)
        if raw.exists():
            try:
                data = json.loads(raw.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {}


def _experiments_json(cards: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(_curated_experiments())
    for c in cards:
        ctx: dict[str, Any] = {"gravity": "earth" if c["gravity"] == "ground" else "micro"}
        if c["mats"]:
            ctx["material"] = c["mats"]
        if c["topics"]:
            ctx["topic"] = c["topics"]
        if c["o2max"]:
            ctx["o2"] = c["o2max"]
        if c["flow"]:
            ctx["ventilation"] = "forced"
        label = f"{c['acr']} - {c['name']}" if c["acr"] and c["acr"].lower() not in c["name"].lower() else c["name"]
        out[c["id"]] = {
            "name": f"{c['acc']} · {label}",
            "ctx": ctx,
            "note": c["blurb"] or f"{c['fuel']} combustion investigation ({c['hardware']}).",
            "sources": [c["id"]],
            "doi": c["doi"],
        }
    return out


def _sources_json(cards: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "glenn": {"name": "NASA GRC ISS Combustion Research", "url": "https://www1.grc.nasa.gov/space/iss-research/"},
        "fm2": {"name": "NASA FM2 - Flammability of Materials on the Moon", "url": "https://www1.grc.nasa.gov/space/iss-research/"},
        "luci": {"name": "LUCI - Lunar Combustion Investigation", "url": "https://www1.grc.nasa.gov/space/iss-research/"},
        "flare2021": {"name": "JAXA FLARE - Flammability Limits At Reduced-g", "url": "https://humans-in-space.jaxa.jp/en/"},
        "saffire45": {"name": "NASA Saffire IV-V - Spacecraft Fire Safety", "url": "https://www1.grc.nasa.gov/space/scm/saffire/"},
        "saffire6": {"name": "NASA Saffire VI - Spacecraft Fire Safety", "url": "https://www1.grc.nasa.gov/space/scm/saffire/"},
        "psi-repo": {"name": "NASA Physical Sciences Informatics repository", "url": "https://psi.nasa.gov/physci/repo"},
    }
    for c in cards:
        out[c["id"]] = {
            "name": f"{c['acc']} · {c['acr'] or c['name']}" if c["acr"] else f"{c['acc']} · {_clip(c['name'], 48)}",
            "url": c["url"],
            "doi": c["doi"],
        }
    return out


def _materials_json() -> dict[str, Any]:
    """Dual-schema materials: the console reads name/loi_pct, Flammy reads aliases/cls.

    LOI values are the same literature placeholders the console has used since
    v1 (flagged in-app); replace with NASA-STD-6001 MOC data when available.
    """
    return {
        "pe": {"name": "Polyethylene (PE)", "loi_pct": 17.4, "cls": "A",
               "aliases": ["polyethylene", "pe foam", "plastic bag", "polymer", "plastic"]},
        "pmma": {"name": "PMMA (acrylic)", "loi_pct": 17.3, "cls": "A",
                 "aliases": ["pmma", "acrylic", "plexiglas", "perspex", "acrylic window"]},
        "fabric": {"name": "Cotton fabric (SIBAL blend)", "loi_pct": 18.4, "cls": "A",
                   "aliases": ["cotton", "fabric", "cloth", "textile", "sibal", "garment", "clothing"]},
        "pc": {"name": "Polycarbonate", "loi_pct": 26.0, "cls": "A",
               "aliases": ["polycarbonate", "lexan"]},
        "nomex": {"name": "Nomex (meta-aramid)", "loi_pct": 29.0, "cls": "A",
                  "aliases": ["nomex", "aramid", "webbing", "kevlar", "strap", "harness"]},
        "silicone": {"name": "Silicone rubber", "loi_pct": 30.0, "cls": "A",
                     "aliases": ["silicone", "rubber seal", "elastomer", "gasket"]},
        "peek": {"name": "PEEK", "loi_pct": 35.0, "cls": "A",
                 "aliases": ["peek", "polyetheretherketone"]},
        "electrical": {"name": "Kapton wiring (polyimide)", "loi_pct": 37.0, "cls": "C",
                       "aliases": ["kapton", "polyimide", "wire", "wiring", "cable", "circuit", "insulation"]},
        "ptfe": {"name": "PTFE (Teflon)", "loi_pct": 95.0, "cls": "A",
                 "aliases": ["ptfe", "teflon", "fluoropolymer"]},
    }


def _rules_json() -> list[dict[str, Any]]:
    """Hazard rules for the Flammy engine, each grounded in PSI investigations."""
    return [
        {"id": "o2-danger", "level": "danger", "title": "Oxygen-enriched atmosphere - flammability limits widen sharply",
         "short": "above ~30 % O2 most cabin materials ignite easier and spread flame faster.",
         "why": ["Material flammability limits widen as the O2 fraction rises; CFI-G ran gaseous flames up to 85 % O2 to map this regime.",
                 "Autoignition delays shorten in enriched O2, so weak ignition sources become credible."],
         "actions": ["Add N2 to pull the O2 fraction down while holding ppO2 at 21.3 kPa.",
                     "Freeze hot-work and high-power operations until the mix is corrected.",
                     "Re-verify exposed materials against their enriched-O2 limits."],
         "sources": ["psi-159", "fm2"], "when": {"o2_min": 30.0}},
        {"id": "o2-caution", "level": "caution", "title": "O2 fraction above standard air",
         "short": "between 23.5 and 30 % O2 the flammable-material set grows; margins shrink.",
         "why": ["Several materials that pass at 21 % O2 sustain flames in mildly enriched atmospheres."],
         "actions": ["Check the selected material's limit against the current O2 fraction.", "Keep a >=3-pt design margin below the material limit."],
         "sources": ["psi-159", "glenn"], "when": {"o2_min": 23.5, "o2_max": 30.0}},
        {"id": "exploration-atmo", "level": "danger", "title": "Exploration atmosphere: low pressure + enriched O2",
         "short": "8.2-10.2 psi with 26-34 % O2 keeps crews EVA-ready but widens flammability limits.",
         "why": ["FM2-class testing targets exactly this trade: 34 % O2 at 8.2 psia versus 21 % at 14.7 psia.",
                 "At fixed ppO2 a lower total pressure means a higher O2 fraction, which controls flame spread."],
         "actions": ["Restrict materials to those qualified for the enriched fraction.", "Increase detection coverage in low-pressure modules."],
         "sources": ["fm2", "psi-98"], "when": {"o2_min": 26.0, "pressure_max_kpa": 72.0}},
        {"id": "micro-quiescent", "level": "info", "title": "Quiescent microgravity - weak flames, hidden smolder",
         "short": "with no airflow a flame dims toward diffusive burning, but smolder and detection become the problem.",
         "why": ["Without buoyancy, quenching a flame of oxidizer flow makes it dim and blue (BASS).",
                 "Smoke does not rise in microgravity; detectors depend on the ventilation that is now off."],
         "actions": ["Treat 'flame out' as unverified: monitor CO/CO2 after apparent extinction.", "Restore detection airflow sampling as soon as safe."],
         "sources": ["psi-26", "psi-101"], "when": {"gravity": ["micro"], "ventilation": ["none"]}},
        {"id": "micro-flow", "level": "caution", "title": "Forced airflow replaces buoyancy and feeds the flame",
         "short": "in microgravity even 10-20 cm/s of duct flow strengthens flame spread.",
         "why": ["BASS-II mapped solid-fuel burning from 0 to 53 cm/s: low imposed flows sustain and strengthen flames that would otherwise weaken."],
         "actions": ["On fire alarm, stop HVAC flow in the affected volume first.", "Keep cable runs and fabrics out of duct outlets."],
         "sources": ["psi-25", "psi-26"], "when": {"gravity": ["micro"], "ventilation": ["forced"]}},
        {"id": "micro-fabric", "level": "caution", "title": "Fabrics in microgravity burn beyond 1-g predictions",
         "short": "cotton-blend fabrics kept burning in micro-g at conditions ground tests called marginal.",
         "why": ["BASS burned PMMA and fabric samples in orbit; Saffire-II spread flames over large fabric sheets without crew risk.",
                 "The 1-g upward test is not always the conservative case in microgravity."],
         "actions": ["Prefer aramid over cotton blends near power or ducts.", "Apply micro-g-informed margins, not raw 1-g pass/fail."],
         "sources": ["psi-26", "psi-99"], "when": {"gravity": ["micro"], "material": ["fabric"]}},
        {"id": "standard-gap", "level": "caution", "title": "1-g flammability standard may not transfer to micro-g",
         "short": "a NASA-STD-6001 pass on the ground does not guarantee the same margin in orbit.",
         "why": ["SoFIE and FLARE exist precisely to tie the 1-g standard test to low-gravity behavior; BASS-II found regimes where micro-g burns stronger."],
         "actions": ["Flag materials qualified only by ground tests.", "Use flow-and-O2-specific limits for orbit configurations."],
         "sources": ["psi-25", "glenn"], "when": {"gravity": ["micro"], "topic": ["standard"]}},
        {"id": "lunar-sparse", "level": "caution", "title": "Partial gravity - sparse data, interpolated regime",
         "short": "at 0.16-0.38 g weak buoyancy returns; direct experimental coverage is thin.",
         "why": ["LUCI and FM2 target lunar gravity precisely because PSI holds almost no partial-g fire data.",
                 "ACME E-FIELD used electric body forces as a partial-gravity analog for flames."],
         "actions": ["Treat partial-g predictions as interpolation between 0 g and 1 g bounds.", "Add margin on suppression sizing until FM2/LUCI data lands."],
         "sources": ["fm2", "luci", "psi-22"], "when": {"gravity": ["lunar"]}},
        {"id": "polymer-enriched", "level": "caution", "title": "Polymer surfaces at elevated O2",
         "short": "PMMA-class polymers burn vigorously once the O2 fraction clears their limit.",
         "why": ["PMMA is the reference solid in BASS/BASS-II: burn rate and flame strength grow with O2 and flow."],
         "actions": ["Keep polymer panels clear of ignition sources above 25 % O2.", "Consider PEEK/polyimide substitutions in enriched zones."],
         "sources": ["psi-25", "psi-26"], "when": {"material": ["pmma", "pe"], "o2_min": 25.0}},
        {"id": "battery-runaway", "level": "danger", "title": "Li-ion thermal runaway",
         "short": "battery runaway self-heats, vents toxic CO/CO2 and can reignite for hours.",
         "why": ["Runaway is self-sustained: it does not need cabin O2 to keep heating.", "Vented gases are flammable and toxic in a sealed volume."],
         "actions": ["Isolate pack electrically; cool continuously; never open containment early.", "Track CO/CO2 until readings stay flat."],
         "sources": ["glenn", "psi-101"], "when": {"ignition": ["battery"]}},
        {"id": "electrical-ignition", "level": "caution", "title": "Electrical fault as ignition source",
         "short": "overheated wiring or arcing is the dominant credible ignition path in spacecraft.",
         "why": ["SAME/SAME-R characterized the smoke that overheated spacecraft materials emit, to tune detectors to this exact scenario."],
         "actions": ["De-energize the affected circuit before suppression (Class C).", "Inspect harness insulation after any overcurrent event."],
         "sources": ["psi-101", "psi-102"], "when": {"ignition": ["electrical"]}},
        {"id": "suppression-diluent", "level": "info", "title": "Diluent suppression behaves differently in micro-g",
         "short": "CO2/He effectiveness measured on FLEX droplets does not map 1:1 from ground data.",
         "why": ["FLEX ran ~274 droplet tests with CO2 and He diluents: transport, not chemistry, controls suppression in micro-g."],
         "actions": ["Size suppressant quantity with micro-g data, not terrestrial design curves.", "After discharge, hold ventilation off to avoid re-feeding the fire."],
         "sources": ["psi-69", "psi-68"], "when": {"gravity": ["micro"], "topic": ["extinguisher"]}},
        {"id": "cool-flames", "level": "caution", "title": "Cool flames - burning can continue invisibly",
         "short": "after visible extinction, low-temperature chemistry can keep consuming fuel.",
         "why": ["FLEX discovered large heptane droplets kept vaporizing and reacting after the visible flame died.",
                 "CFI and CFI-G mapped the same cool-flame regime for droplets and gaseous flames."],
         "actions": ["Verify extinction with temperature/CO sensors, not eyesight.", "Keep the suppressed zone isolated until readings decay."],
         "sources": ["psi-69", "psi-39", "psi-159"], "when": {"gravity": ["micro"], "topic": ["flame"]}},
        {"id": "smoke-detection", "level": "info", "title": "Smoke behavior and detection in micro-g",
         "short": "particle size and transport differ in micro-g; detectors must be tuned for it.",
         "why": ["SAME/SAME-R measured spacecraft-material smoke properties in orbit; DAFT tested detection against dust backgrounds."],
         "actions": ["Favor aspirated/duct-sampling detectors over ceiling logic.", "Alarm on CO/CO2 rate-of-rise as the primary cue."],
         "sources": ["psi-101", "psi-102", "psi-47"], "when": {"topic": ["smoke", "gas"]}},
        {"id": "fabric-enriched", "level": "danger", "title": "Fabric + enriched O2: fast spread",
         "short": "cotton-blend fabric in >=30 % O2 is a rapid-spread scenario.",
         "why": ["Saffire burned large fabric sheets to measure spread at scale; enrichment accelerates exactly this geometry."],
         "actions": ["Remove or bag cotton-blend items during enriched-O2 operations.", "Pre-stage suppression at fabric storage."],
         "sources": ["psi-99", "fm2"], "when": {"material": ["fabric"], "o2_min": 30.0}},
        {"id": "earth-baseline", "level": "info", "title": "1-g baseline: buoyant upward spread",
         "short": "on the ground, upward spread over a vertical sample is the severe reference case.",
         "why": ["The 1-g upward test anchors NASA-STD-6001 material screening; orbit data are compared against it."],
         "actions": ["Use ground results as the comparison baseline, not as orbit margins."],
         "sources": ["glenn", "psi-repo"], "when": {"gravity": ["earth"], "topic": ["fire", "standard"]}},
    ]


def _fire_response_json() -> dict[str, Any]:
    return {
        "micro": {"label": "ISS-STYLE RESPONSE (MICROGRAVITY)",
                  "steps": ["Sound the alarm and alert the whole crew.",
                            "Cut forced ventilation in the affected volume - airflow feeds micro-g flames.",
                            "De-energize the suspected rack or circuit.",
                            "Apply the portable CO2/water-mist extinguisher through the access port.",
                            "Don masks; monitor CO/CO2 until readings stay flat - cool flames can persist unseen."],
                  "sources": ["psi-25", "psi-69", "psi-101"]},
        "lunar": {"label": "SURFACE HABITAT RESPONSE (PARTIAL G)",
                  "steps": ["Sound the alarm; weak buoyancy lofts smoke slowly - do not trust ceiling detectors alone.",
                            "Stop HVAC flow to the compartment.",
                            "De-energize local power.",
                            "Suppress at the base of the flame; partial-g plumes tilt with any draft.",
                            "Verify extinction with sensors; partial-g fire data are sparse (FM2/LUCI pending)."],
                  "sources": ["fm2", "luci", "psi-22"]},
        "earth": {"label": "GROUND TEST-BENCH RESPONSE (1 G)",
                  "steps": ["Raise the alarm and evacuate non-essential personnel.",
                            "Cut power to the bench.",
                            "Use the extinguisher class matching the fuel.",
                            "Ventilate only after confirmed extinction."],
                  "sources": ["glenn"]},
    }


def _class_notes_json() -> dict[str, str]:
    return {
        "A": "Class A (solids): after knockdown, cool the char - deep smolder can re-ignite when airflow returns.",
        "B": "Class B (liquids/gases): shut off the fuel feed before suppressing.",
        "C": "Class C (electrical): de-energize before applying any agent; assume re-arc risk.",
        "battery": "Battery: runaway is self-heating - cool continuously and expect reignition for hours; never open containment early.",
    }


def _mission_presets_json() -> dict[str, Any]:
    """Reference atmospheres for the console preset selector ({g, o2, hold, p})."""
    return {
        "ISS Cabin - Sea-Level Mix": {"g": 0.0, "o2": 21.0, "hold": False, "p": 101.3},
        "Exploration Atmosphere (8.2 psi / 34% O2)": {"g": 0.0, "o2": 34.0, "hold": False, "p": 56.5},
        "Lunar Surface Habitat": {"g": 0.16, "o2": 34.0, "hold": False, "p": 56.5},
        "Mars Transit (10.2 psi)": {"g": 0.0, "o2": 26.5, "hold": False, "p": 70.3},
        "Mars Surface Habitat": {"g": 0.38, "o2": 26.5, "hold": False, "p": 70.3},
        "Terrestrial Test Bench": {"g": 1.0, "o2": 21.0, "hold": False, "p": 101.3},
    }


# --------------------------------------------------------------------------
# Build orchestration
# --------------------------------------------------------------------------
def _write(name: str, data: Any) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _source_mtime() -> float:
    times = [Path(__file__).stat().st_mtime]
    times += [p.stat().st_mtime for p in DB_DIR.glob("PSI-*.json")]
    curated = DB_DIR / CURATED_FILE
    if curated.exists():
        times.append(curated.stat().st_mtime)
    return max(times)


def ensure_knowledge(force: bool = False) -> dict[str, Any]:
    """(Re)build the derived knowledge JSONs. Hand-edited newer files are kept."""
    if not DB_DIR.exists():
        return {"built": [], "kept": [], "error": f"missing {DB_DIR}"}
    src_time = _source_mtime()
    stale = [n for n in TARGETS
             if force or not (OUT_DIR / n).exists() or (OUT_DIR / n).stat().st_mtime < src_time]
    if not stale:
        return {"built": [], "kept": list(TARGETS)}

    cards = build_index()
    payloads: dict[str, Any] = {
        INDEX_FILE: cards,
        "experiments.json": _experiments_json(cards),
        "sources.json": _sources_json(cards),
        "materials.json": _materials_json(),
        "rules.json": _rules_json(),
        "fire_response.json": _fire_response_json(),
        "class_notes.json": _class_notes_json(),
        "mission_presets.json": _mission_presets_json(),
    }
    for name in stale:
        _write(name, payloads[name])
    _write(BUILD_INFO_FILE, {
        "generator": "psi_database.py", "investigations": len(cards),
        "rebuilt": stale, "note": "Derived from the raw PSI metadata in base_de_datos/ (read-only); delete a file here to regenerate it.",
    })
    return {"built": stale, "kept": [n for n in TARGETS if n not in stale], "investigations": len(cards)}


def investigation_cards() -> list[dict[str, Any]]:
    """Card list for the Bubble-1 browser (cached in psi_index.json)."""
    ensure_knowledge()
    data = _read_json(OUT_DIR / INDEX_FILE)
    return data if isinstance(data, list) else build_index()


if __name__ == "__main__":
    import sys

    result = ensure_knowledge(force="--force" in sys.argv)
    print(f"rebuilt: {result['built'] or 'nothing (fresh)'}")
    for c in investigation_cards():
        print(f"{c['acc']:>8}  {c['fuel']:<9}  tables={c['tables']:<2} rows={c['rows']:<5} doi={c['doi'] or '-':<22} {c['acr'] or c['name'][:40]}")
