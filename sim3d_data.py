"""sim3d_data.py — data bridge for the 3D cabin fire simulator (SIMULATIONS · Section 02).

Reads base_de_datos/ strictly READ-ONLY (never writes, renames or deletes there) and
packages, for the browser:

  * HABITATS    atmosphere + gravity presets. Each value carries its provenance: a
                PSI table / file in base_de_datos, or an explicit "not in base_de_datos"
                tag that the UI renders as CONCEPTUAL.
  * EVIDENCE    the scientific panel shown when the user clicks a zone of the 3D cabin
                (fire source, vent, smoke sensor, atmosphere, flame shape, hull), with
                values extracted live from the PSI experimental tables + DOIs.
  * FLOW        ventilation slider range/default taken from PSI tables.
  * PROFILE     capsule radius-vs-height profile measured from the user's GLB, used to
                build the fluid-domain mask and a fallback mesh if the GLB can't load.

Nothing here invents combustion parameters. The numerical fluid model in the browser
(diffusivities, buoyancy gain, source strengths) is a visualization model and is
labeled CONCEPTUAL in the UI.
"""

from __future__ import annotations

import csv
import json
import re
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / "base_de_datos"           # READ-ONLY
GLB_PATH = ROOT / "static" / "nave.glb"   # served by Streamlit static serving
GLB_URL = "/app/static/nave.glb"
SIM_DIR = ROOT / "sim3d"

MMHG_TO_KPA = 0.133322
PSIA_TO_KPA = 6.894757


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------
def _rows(filename: str) -> list[dict[str, str]]:
    path = DB_DIR / filename
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


def _meta(acc: str) -> dict[str, str]:
    path = DB_DIR / f"{acc}.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"acc": acc, "title": acc, "doi": "", "url": "https://psi.nasa.gov/physci/repo"}
    doi = str(d.get("doi") or "")
    return {
        "acc": acc,
        "title": str(d.get("title") or acc),
        "acr": str(d.get("investigationAcronym") or ""),
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else "https://psi.nasa.gov/physci/repo",
    }


def _num(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def _curated() -> dict[str, Any]:
    for name in ("experiments_curated.json", "experiments.json.py"):
        p = DB_DIR / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _src(acc: str, detail: str) -> dict[str, str]:
    m = _meta(acc)
    return {"kind": "psi", "acc": acc, "label": f"{acc} · {m['acr'] or m['title']}", "doi": m["doi"], "url": m["url"], "detail": detail}


def _concept(detail: str) -> dict[str, str]:
    return {"kind": "concept", "label": "Not in base_de_datos — conceptual", "detail": detail}


# ---------------------------------------------------------------------------
# Atmospheres & habitats
# ---------------------------------------------------------------------------
def _flex_iss_atmosphere() -> dict[str, Any]:
    """Air-like FLEX runs (O2 = 0.21, ~1 atm) aboard the ISS CIR: median pressure."""
    p = [_num(r.get("Ambient pressure; mmHg", "")) for r in _rows("PSI-69_Experimental table_FLEX.csv")
         if r.get("O initial ambient composition; mole fraction") == "0.21"]
    p = sorted(x for x in p if x and 700 < x < 800)
    if not p:
        return {"kpa": None, "n": 0}
    med = p[len(p) // 2]
    return {"kpa": round(med * MMHG_TO_KPA, 1), "mmhg": med, "n": len(p)}


def _fm2_exploration() -> dict[str, Any] | None:
    note = str(_curated().get("fm2", {}).get("note", ""))
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:O2)?\s*at\s*(\d+(?:\.\d+)?)\s*psia\.?\s*$", note)
    if not m:
        m = re.search(r"(\d+)%\s*at\s*(\d+(?:\.\d+)?)\s*psia", note.split("and")[-1]) if "and" in note else None
    if not m:
        return None
    return {"o2": float(m.group(1)), "psia": float(m.group(2)), "kpa": round(float(m.group(2)) * PSIA_TO_KPA, 1), "note": note}


@lru_cache(maxsize=1)
def habitats() -> dict[str, Any]:
    iss = _flex_iss_atmosphere()
    fm2 = _fm2_exploration()
    saffire_o2 = next((r.get("Percent O2", "") for r in _rows("PSI-98_Experimental table_SAFFIRE-1.csv") if r.get("Percent O2")), "")

    iss_p = iss["kpa"] or 101.3
    iss_p_src = (_src("PSI-69", f"Median ambient pressure of {iss['n']} air-composition FLEX runs aboard the ISS: "
                                 f"{iss['mmhg']} mmHg = {iss['kpa']} kPa.")
                 if iss["kpa"] else _concept("Sea-level pressure assumed."))
    iss_o2_src = _src("PSI-98", f"Cabin-air O2 measured during Saffire-I: {saffire_o2} %.") if saffire_o2 else _concept("21 % assumed.")

    if fm2:
        expl = {"o2": fm2["o2"], "kpa": fm2["kpa"]}
        expl_src = {"kind": "psi-file", "label": "base_de_datos · experiments.json.py (FM2)",
                    "detail": f"FM2 note: “{fm2['note']}” → {fm2['o2']:.0f} % O2 at {fm2['psia']} psia = {fm2['kpa']} kPa."}
    else:
        expl, expl_src = {"o2": 34.0, "kpa": 56.5}, _concept("Exploration atmosphere assumed (34 % O2, 56.5 kPa).")

    g_src = {"kind": "physics", "label": "Physical constant", "detail": "Surface gravity relative to Earth (not combustion data)."}
    return {
        "iss": {"name": "ISS", "sub": "Low Earth orbit · 0 g", "g": 0.0, "o2": 21.0, "kpa": iss_p,
                "sources": {"g": g_src, "o2": iss_o2_src, "kpa": iss_p_src}},
        "gateway": {"name": "Lunar Gateway", "sub": "Lunar orbit · 0 g", "g": 0.0, "o2": 21.0, "kpa": iss_p,
                    "sources": {"g": g_src,
                                "o2": _concept("Gateway cabin atmosphere is not in base_de_datos; ISS-like air shown."),
                                "kpa": _concept("Gateway cabin pressure is not in base_de_datos; ISS-like value shown.")}},
        "lunar": {"name": "Lunar Base", "sub": "Surface · 0.16 g", "g": 0.16, "o2": expl["o2"], "kpa": expl["kpa"],
                  "sources": {"g": {"kind": "psi-file", "label": "base_de_datos · experiments.json.py (FM2)",
                                    "detail": "FM2 studies how materials burn at 1/6 g."},
                              "o2": expl_src, "kpa": expl_src}},
        "mars": {"name": "Mars Base", "sub": "Surface · 0.38 g", "g": 0.38, "o2": expl["o2"], "kpa": expl["kpa"],
                 "sources": {"g": g_src,
                             "o2": _concept("Mars-habitat atmosphere is not in base_de_datos; FM2 exploration atmosphere reused."),
                             "kpa": _concept("Mars-habitat pressure is not in base_de_datos; FM2 exploration atmosphere reused.")}},
        "eva": {"name": "EVA", "sub": "Suit / airlock · 0 g", "g": 0.0, "o2": 100.0, "kpa": 29.6,
                "sources": {"g": g_src,
                            "o2": _concept("Pure-O2 suit atmosphere is not in base_de_datos; reference value only."),
                            "kpa": _concept("4.3 psi suit pressure is not in base_de_datos; reference value only.")}},
        "custom": {"name": "Custom", "sub": "Your parameters", "g": 0.0, "o2": 21.0, "kpa": iss_p,
                   "sources": {"g": _concept("User-defined."), "o2": _concept("User-defined."), "kpa": _concept("User-defined.")}},
    }


# ---------------------------------------------------------------------------
# Ventilation range from PSI tables
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def flow() -> dict[str, Any]:
    s1 = sorted({_num(r.get("Air Flow (cm/s)", "")) for r in _rows("PSI-98_Experimental table_SAFFIRE-1.csv")} - {None})
    s3 = sorted({_num(r.get("Air Flow", "")) for r in _rows("PSI-100_Experimental table_SAFFIRE-3.csv")} - {None})
    leeme = (DB_DIR / "LEEME_datos_PSI.md").read_text(encoding="utf-8", errors="replace") if (DB_DIR / "LEEME_datos_PSI.md").exists() else ""
    m = re.search(r"BASS-II[^\n]*?de\s*(\d+)\s*a\s*(\d+)\s*cm/s", leeme)
    vmax = float(m.group(2)) if m else max(s1 + s3 + [30.0])
    return {
        "min": 0.0, "max": vmax, "default": s1[0] if s1 else 20.0,
        "marks": sorted(set(s1 + s3)),
        "source": (f"Range 0–{vmax:.0f} cm/s: BASS-II (PSI-25) per LEEME_datos_PSI.md. "
                   f"Marks: Saffire-I {', '.join(f'{v:.0f}' for v in s1)} cm/s (PSI-98), Saffire-III {', '.join(f'{v:.0f}' for v in s3)} cm/s (PSI-100)."),
    }


# ---------------------------------------------------------------------------
# Evidence panels for clickable zones
# ---------------------------------------------------------------------------
def _saffire_table() -> list[dict[str, str]]:
    out = []
    for f, acc, flowkey, o2key, burnkey, dirkey in (
        ("PSI-98_Experimental table_SAFFIRE-1.csv", "PSI-98", "Air Flow (cm/s)", "Percent O2", "Burn Time (s)", "Flow Direction"),
        ("PSI-99_Experimental table_SAFFIRE-2.csv", "PSI-99", "Air Flow (cm/s)", "Percent O2 (Note 1)", "Burn Time (s)", "Flow Direction"),
    ):
        for r in _rows(f):
            mat = r.get("Material", "")
            if not mat or not r.get(flowkey) or "Pre-test" in mat:
                continue
            out.append({"acc": acc, "sample": r.get("Sample Number", ""), "material": mat, "flow": r.get(flowkey, ""),
                        "o2": r.get(o2key, ""), "burn": r.get(burnkey, ""), "dir": r.get(dirkey, "")})
    return out


@lru_cache(maxsize=1)
def evidence() -> dict[str, Any]:
    saff = _saffire_table()
    bass2 = _rows("PSI-25_Experimental table_BASS-II.csv")
    o2s = sorted(x for x in (_num(r.get("Calibrated  initial O2 % by vol", "") or r.get("Calibrated  initial O2 % by vol ", "")) for r in bass2) if x)
    fuels = {}
    for r in bass2:
        k = re.sub(r"\s+", " ", r.get("Fuel Sample Material", ""))[:34]
        fuels[k] = fuels.get(k, 0) + 1
    top_fuels = sorted(fuels.items(), key=lambda kv: -kv[1])[:4]

    flex = _rows("PSI-69_Experimental table_FLEX.csv")
    fx_o2 = sorted({_num(r.get("O initial ambient composition; mole fraction", "")) for r in flex} - {None})
    fx_end = {}
    for r in flex:
        fx_end[r.get("Test end", "?")] = fx_end.get(r.get("Test end", "?"), 0) + 1
    fx_he = sum(1 for r in flex if (_num(r.get("He initial ambient composition; mole fraction", "")) or 0) > 0)
    fx_co2 = sum(1 for r in flex if (_num(r.get("CO initial ambient composition; mole fraction", "")) or 0) > 0)

    samer = _rows("PSI-101_Experimental table_SAME-R.csv")
    sm_types = {}
    for r in samer:
        sm_types[r.get("Sample Type", "?")] = sm_types.get(r.get("Sample Type", "?"), 0) + 1
    sm_v = sorted({_num(r.get("Inlet velocity (cm/s)", "")) for r in samer} - {None})
    fl = flow()

    return {
        "fire": {
            "title": "Ignition source & flame spread",
            "body": "In orbit, Saffire burned large samples inside an uncrewed Cygnus with a fan-driven duct flow. "
                    "These are the measured runs in base_de_datos:",
            "table": {"cols": ["Run", "Material", "Flow", "O₂ %", "Burn time", "Direction"],
                      "rows": [[f"{s['acc']} {s['sample']}", s["material"], s["flow"], s["o2"], s["burn"], s["dir"]] for s in saff[:9]]},
            "note": "The simulated flame is CONCEPTUAL: its size and heat release are not fitted to these runs.",
            "sources": [_src("PSI-98", "Saffire-I table"), _src("PSI-99", "Saffire-II table")],
        },
        "vent": {
            "title": "Forced ventilation (inlet)",
            "body": "With no buoyancy in 0 g, forced flow is the dominant oxidizer transport. " + fl["source"],
            "facts": [["Slider range", f"0–{fl['max']:.0f} cm/s"], ["Saffire flows", ", ".join(f"{v:.0f} cm/s" for v in fl["marks"])]],
            "sources": [_src("PSI-25", "BASS-II flow range"), _src("PSI-98", "Saffire-I air flow"), _src("PSI-100", "Saffire-III air flow")],
        },
        "sensor": {
            "title": "Smoke detection",
            "body": f"SAME-R measured smoke from overheated spacecraft materials in orbit: {len(samer)} runs.",
            "facts": [["Materials", ", ".join(f"{k} ({v})" for k, v in sorted(sm_types.items(), key=lambda kv: -kv[1]))],
                      ["Inlet velocities", ", ".join(f"{v:g} cm/s" for v in sm_v)]],
            "note": "The smoke field in the simulator is a CONCEPTUAL tracer, not SAME-R particle data.",
            "sources": [_src("PSI-101", "SAME-R table")],
        },
        "atmosphere": {
            "title": "Atmosphere & oxygen",
            "body": "Oxygen fraction and pressure control whether a flame survives. Ranges actually tested in base_de_datos:",
            "facts": [["FLEX O₂ mole fractions", f"{min(fx_o2):.2f}–{max(fx_o2):.2f} ({len(flex)} droplet runs)" if fx_o2 else "n/a"],
                      ["FLEX test endings", ", ".join(f"{k}: {v}" for k, v in sorted(fx_end.items(), key=lambda kv: -kv[1]))],
                      ["FLEX diluent runs", f"He: {fx_he} · CO₂: {fx_co2}"],
                      ["BASS-II initial O₂", f"{o2s[0]:.1f}–{o2s[-1]:.1f} % vol ({len(o2s)} runs)" if o2s else "n/a"]],
            "note": "The O₂ heat map shows RELATIVE depletion predicted by the visualization model, not measured O₂.",
            "sources": [_src("PSI-69", "FLEX table"), _src("PSI-25", "BASS-II table")],
        },
        "flame": {
            "title": "Flame shape vs gravity",
            "body": "0 g: no buoyant plume, the diffusion flame tends to a sphere and is fed by diffusion or forced flow. "
                    "Partial gravity reintroduces a weak plume; direct partial-g data are sparse, so shapes between 0 g and 1 g are interpolated.",
            "facts": [["BASS-II fuels (most tested)", "; ".join(f"{k} ({v})" for k, v in top_fuels)]],
            "note": "Partial-gravity flame geometry is a CONCEPTUAL interpolation awaiting FM2 / LUCI data.",
            "sources": [_src("PSI-26", "BASS"), _src("PSI-25", "BASS-II"), _src("PSI-22", "E-FIELD: body-force analog of gravity")],
        },
        "hull": {
            "title": "Capsule geometry",
            "body": "Geometry from your CAD model (NAVE_GLB / NAVE STEP). Dimensions are used only to bound the airflow domain.",
            "note": "No PSI experiment used this capsule; airflow inside it is a CONCEPTUAL visualization.",
            "sources": [],
        },
    }


# ---------------------------------------------------------------------------
# Capsule profile from the GLB (radius vs height)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def capsule_profile(bins: int = 24) -> dict[str, Any]:
    try:
        b = GLB_PATH.read_bytes()
        clen = struct.unpack("<I", b[12:16])[0]
        g = json.loads(b[20:20 + clen])
        bin_off = 20 + clen + 8
        prim = g["meshes"][0]["primitives"][0]
        acc = g["accessors"][prim["attributes"]["POSITION"]]
        view = g["bufferViews"][acc["bufferView"]]
        start = bin_off + view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride", 12)
        ymin, ymax = acc["min"][1], acc["max"][1]
        rad = [0.0] * bins
        for i in range(acc["count"]):
            x, y, z = struct.unpack_from("<fff", b, start + i * stride)
            k = min(bins - 1, int((y - ymin) / (ymax - ymin) * bins))
            rad[k] = max(rad[k], (x * x + z * z) ** 0.5)
        for k in range(1, bins):  # fill any empty bin from its neighbour
            if rad[k] == 0:
                rad[k] = rad[k - 1]
        top = g["accessors"][g["meshes"][0]["primitives"][1]["attributes"]["POSITION"]]["max"][1] if len(g["meshes"][0]["primitives"]) > 1 else ymax
        return {"ymin": ymin, "ymax": max(ymax, top), "radius": [round(r, 4) for r in rad], "ok": True}
    except Exception:
        return {"ymin": 0.0, "ymax": 3.2, "radius": [1.52 * (1 - (k / 24) ** 2.2) ** 0.5 + 0.05 for k in range(24)], "ok": False}


# ---------------------------------------------------------------------------
# HTML section for the console
# ---------------------------------------------------------------------------
def payload() -> dict[str, Any]:
    return {"habitats": habitats(), "evidence": evidence(), "flow": flow(), "profile": capsule_profile(),
            "glbUrl": GLB_URL, "glbAvailable": GLB_PATH.exists()}


def section_html() -> str:
    """Markup + CSS + inlined module script for SIMULATIONS · Section 02."""
    markup = (SIM_DIR / "sim3d.html").read_text(encoding="utf-8")
    css = (SIM_DIR / "sim3d.css").read_text(encoding="utf-8")
    js = (SIM_DIR / "sim3d.js").read_text(encoding="utf-8")
    data = json.dumps(payload(), ensure_ascii=False).replace("</", "<\\/")
    importmap = ('<script type="importmap">{"imports":{'
                 '"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",'
                 '"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>')
    return (f"<style>{css}</style>\n{markup}\n"
            f'<script id="sim3d-data" type="application/json">{data}</script>\n'
            f"{importmap}\n<script type=\"module\">\n{js}\n</script>")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    d = payload()
    for k, h in d["habitats"].items():
        print(f"{k:8} g={h['g']:<5} O2={h['o2']:<5} P={h['kpa']:<6} | o2:{h['sources']['o2']['kind']:<8} p:{h['sources']['kpa']['kind']}")
    print("flow:", d["flow"])
    print("profile ok:", d["profile"]["ok"], d["profile"]["ymin"], d["profile"]["ymax"], d["profile"]["radius"][:6], "...")
    print("evidence zones:", list(d["evidence"]))
    print("fire rows:", len(d["evidence"]["fire"]["table"]["rows"]))
    print(d["evidence"]["atmosphere"]["facts"])
