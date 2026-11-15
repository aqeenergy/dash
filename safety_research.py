"""safety_research.py — minimal backend adapter for the SAFETY MECHANISMS bubble.

Publishes  GET /app/static/safety/research.json  (Streamlit static serving; Streamlit has no
custom API routes, so the "GET /api/safety/research" endpoint is this static JSON, rebuilt
whenever base_de_datos/ or this file changes).

Rules
  * base_de_datos/ is READ-ONLY (pathlib reads only; tests assert the folder is unchanged).
  * Every number shown as a measured result is computed here from the PSI experimental tables.
  * Objective / hypothesis / impact text is quoted from the PSI records (PSI-XX.json).
  * "Safety application", "limitation", the 18-22-word summary and the A/H/F criterion scores
    are FLAMA editorial judgements, labelled as such in the UI. E (evidence) is computed.
  * Historical accidents are secondary context, from the general historical record (not in
    base_de_datos), each tagged as a documented direct consequence or a thematic link only.

FLAMA Score (0-100, ours — not a NASA ranking):
    score = round(100 * (0.40*A + 0.25*H + 0.20*E + 0.15*F) / 3),  A, H, E, F in {0,1,2,3}
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / "base_de_datos"                      # READ-ONLY
OUT_DIR = ROOT / "static" / "safety"
OUT_FILE = OUT_DIR / "research.json"
DOI_CHECK_FILE = OUT_DIR / "doi_check.json"          # written by: python safety_research.py --check-dois
URL = "/app/static/safety/research.json"
VERSION = 3

WEIGHTS = {"A": 0.40, "H": 0.25, "E": 0.20, "F": 0.15}
MIN_ROWS = 10   # E: measured values in at least this many table rows
MIN_PUBS = 10   # E: at least this many publications listed in the PSI record


def flama_score(a: int, h: int, e: int, f: int) -> int:
    """Reproducible FLAMA Score. Each criterion is an integer 0-3; result is 0-100."""
    for name, v in (("A", a), ("H", h), ("E", e), ("F", f)):
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 3:
            raise ValueError(f"criterion {name} must be an integer 0-3, got {v!r}")
    weighted = WEIGHTS["A"] * a + WEIGHTS["H"] * h + WEIGHTS["E"] * e + WEIGHTS["F"] * f
    return int(round(100 * weighted / 3 + 1e-9))


# ---------------------------------------------------------------------------
# Read-only access
# ---------------------------------------------------------------------------
def _record(acc: str) -> dict | None:
    p = DB_DIR / f"{acc}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _table(acc: str) -> tuple[str | None, pd.DataFrame | None]:
    files = sorted(DB_DIR.glob(f"{acc}_Experimental table_*.csv"))
    if not files:
        return None, None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(files[0], encoding=enc)
            df.columns = [str(c).strip() for c in df.columns]
            return files[0].name, df
        except UnicodeDecodeError:
            continue
    return files[0].name, None


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")


def _sentences(text: str, n: int = 2, limit: int = 420) -> str:
    text = " ".join(str(text or "").split())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text)
    out = " ".join(parts[:n]).strip()
    return out if len(out) <= limit else out[: limit - 1].rsplit(" ", 1)[0] + "…"


def _lib_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


# ---------------------------------------------------------------------------
# Measured results, computed from each local table (no hand-typed numbers)
# ---------------------------------------------------------------------------
def _findings_bass2(df: pd.DataFrame) -> list[str]:
    o2i, o2f = _num(df["Calibrated  initial O2 % by vol"]), _num(df["Calibrated final O2 % by vol"])
    co, co2 = _num(df["Final CO (ppm)"]), _num(df["Final CO2 % by vol"])
    mats = df["Fuel Sample Material"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip().value_counts()
    return [
        f"{len(df)} test points logged; initial O2 (calibrated) {o2i.min():g}–{o2i.max():g} % by volume.",
        f"After burning, chamber O2 recorded {o2f.min():g}–{o2f.max():g} %, CO2 up to {co2.max():g} % and CO up to {co.max():g} ppm.",
        "Most-tested fuels: " + "; ".join(f"{m} ({n})" for m, n in mats.head(4).items()) + ".",
    ]


def _findings_bass(df: pd.DataFrame) -> list[str]:
    mats = df["Fuel Sample Material"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip().value_counts()
    return [
        f"{len(df)} as-run tests logged in the local table (date, test number, sample, fuel).",
        "Most-tested fuels: " + "; ".join(f"{m} ({n})" for m, n in mats.head(5).items()) + ".",
        "The local table carries no measured flame quantities: results are reported in the record's publications.",
    ]


def _findings_samer(df: pd.DataFrame) -> list[str]:
    g = df.groupby("Sample Type")["Rt/R0"].agg(["count", "min", "max"])
    v = sorted(set(_num(df["Inlet velocity (cm/s)"]).dropna()))
    return [
        f"{len(df)} smoke-aging runs on {len(g)} spacecraft materials: " + "; ".join(f"{k} ({int(r['count'])})" for k, r in g.iterrows()) + ".",
        "Inlet velocities used: " + ", ".join(f"{x:g}" for x in v) + " cm/s.",
        "Rt/R0 as recorded: " + "; ".join(f"{k} {r['min']:g}–{r['max']:g}" for k, r in g.iterrows()) + ".",
    ]


def _findings_same(df: pd.DataFrame) -> list[str]:
    mat = df.columns[1]
    rate = _num(df["Weight loss rate (mg/min)"])
    rows = df[rate.notna()]
    flows = sorted(set(_num(rows["Air Flow (cm/s)"]).dropna()))
    names = sorted(set(rows[mat].astype(str).str.strip()))
    return [
        f"{len(rows)} of {len(df)} rows carry measured values, all for {', '.join(names)}: air flow {', '.join(f'{x:g}' for x in flows)} cm/s, weight-loss rate {rate.min():g}–{rate.max():g} mg/min.",
        "Other materials are listed as run under the same conditions without values: "
        + ", ".join(str(x).split(":")[0].strip() for x in df.loc[rate.isna(), mat]) + ".",
    ]


def _findings_saffire2(df: pd.DataFrame) -> list[str]:
    runs = df[df["Air Flow (cm/s)"].astype(str).str.contains("cm/s", na=False)]
    o2 = [float(x) for v in runs["Percent O2 (Note 1)"].astype(str) for x in re.findall(r"\d+\.\d+|\d+", v)]
    dirs = runs["Flow Direction"].astype(str).str.strip().value_counts()
    out = [f"{len(runs)} samples at {', '.join(sorted(set(runs['Air Flow (cm/s)'].str.strip())))} "
           f"({', '.join(f'{k.lower()} {v}' for k, v in dirs.items())}); O2 {min(o2):g}–{max(o2):g} % (derived from CO2, table note 1)."]
    for _, r in runs.iterrows():
        m = str(r["Material"]).strip()
        m = m if m and m.lower() != "nan" else "material not stated in the table"
        out.append(f"Sample {r['Sample Number']} · {m}: burn time {r['Burn Time (s)']}, µg burn length {r['?-g Burn Length']}.")
    notes = [str(x) for x in df["Sample Number"] if str(x).startswith("Note 2") or str(x).startswith("Note 4")]
    return out + [n.replace("Note 2 ", "Table note (sample 2-7): ").replace("Note 4 ", "Table note (sample 2-9): ") for n in notes]


def _findings_flex(df: pd.DataFrame) -> list[str]:
    o2 = _num(df["O initial ambient composition; mole fraction"])
    he = (_num(df["He initial ambient composition; mole fraction"]) > 0).sum()
    co2 = (_num(df["CO initial ambient composition; mole fraction"]) > 0).sum()
    end = df["Test end"].astype(str).str.strip().value_counts()
    fuel = df["Fuel"].astype(str).str.strip().value_counts()
    return [
        f"{len(df)} droplet tests: " + ", ".join(f"{k} {v}" for k, v in fuel.items()) + ".",
        "How each test ended: " + ", ".join(f"{k} {v}" for k, v in end.items()) + ".",
        f"Ambient O2 mole fraction {o2.min():g}–{o2.max():g}; tests with a diluent: CO2 {co2}, He {he}.",
    ]


# ---------------------------------------------------------------------------
# Study catalogue (editorial fields are labelled in the UI)
# ---------------------------------------------------------------------------
APOLLO1 = ("Apollo 1 (1967)", "A cabin fire during a ground test killed three astronauts. NASA then reworked spacecraft "
           "materials selection and introduced systematic flammability testing, the lineage of today's upward-burning "
           "screening test (NASA-STD-6001 Test 1).")
STUDIES = [
    {
        "acc": "PSI-25", "category": "Prevention", "tags": ["Prevention", "Suppression"],
        "summary": "Maps ignition, flame spread and extinction limits of solid materials in low ventilation flows, testing whether ground flammability screening holds in orbit.",
        "application": "Material-selection margins that do not rely only on the 1-g upward test, and the computational fire models the record says are used to design detection and suppression systems.",
        "limitation": "The local table records gas composition before and after each test, not flame-spread rates; flow is logged as fan and restrictor settings, not cm/s. One final-O2 value (40.4 %) exceeds every initial value and should be checked against the source.",
        "measured_columns": ["Calibrated final O2 % by vol", "Final CO (ppm)"],
        "findings": _findings_bass2,
        "scores": {"A": (3, "Record: helps select the safest materials and improve firefighting methods."),
                   "H": (3, "Microgravity, low-speed forced ventilation, cabin-like O2 (13.6–22.2 %)."),
                   "F": (3, "Record: results feed combustion models used to design detection and suppression systems; informs SoFIE.")},
        "history": [{"event": APOLLO1[0], "link": "Thematic link", "text": APOLLO1[1] + " BASS-II tests whether that 1-g screening is conservative in microgravity (per its PSI record)."}],
    },
    {
        "acc": "PSI-26", "category": "Suppression", "tags": ["Suppression", "Prevention"],
        "summary": "Burned realistic solid fuels in orbit and tested an ISS-like inert gaseous extinguishing agent, comparing behaviour against the standard ground flammability test.",
        "application": "Evidence for inert-gas (nitrogen) extinguishment in microgravity and for extending heat-release data to performance-based material selection, as described in the record.",
        "limitation": "The local table is an as-run log (date, sample, fuel) with no measured flame data; quantitative results live in the record's publications, not in base_de_datos.",
        "measured_columns": [],
        "findings": _findings_bass,
        "scores": {"A": (3, "Objective 2: effectiveness of an ISS-like inert gaseous extinguishing agent."),
                   "H": (3, "Spacecraft-relevant solid fuels burned in the ISS Microgravity Science Glovebox."),
                   "F": (2, "Record: data used in first-order heat-release models; nitrogen suppression links to current techniques.")},
        "history": [{"event": APOLLO1[0], "link": "Direct historical consequence", "text": APOLLO1[1] + " BASS's first objective is explicitly to bridge that NASA-STD-6001 Test 1 method and real flammability in microgravity (per its PSI record)."}],
    },
    {
        "acc": "PSI-101", "category": "Detection", "tags": ["Detection"],
        "summary": "Reflight measuring smoke from overheated spacecraft materials in microgravity to size particles that future spacecraft fire detectors must reliably sense.",
        "application": "Baseline reduced-gravity smoke data against which spacecraft smoke-detector technology can be evaluated, as the record states.",
        "limitation": "The local table does not define Rt/R0 or give particle-size distributions; interpreting them needs the final report referenced by the record.",
        "measured_columns": ["Rt/R0", "Inlet velocity (cm/s)"],
        "findings": _findings_samer,
        "scores": {"A": (3, "Record: leads to technology for an advanced spacecraft fire detector."),
                   "H": (3, "Smoke from real spacecraft materials (Kapton, Teflon, silicone…) in microgravity."),
                   "F": (3, "Record: provides the baseline for evaluating future detection technology.")},
        "history": [{"event": "Mir (1997)", "link": "Thematic link", "text": "A fire in an oxygen generator filled the Mir station with smoke; it illustrates why smoke detection in microgravity matters. SAME-R is a reflight of SAME — see that card."}],
    },
    {
        "acc": "PSI-102", "category": "Detection", "tags": ["Detection"],
        "summary": "First on-orbit study of how smoke particles grow from heated spacecraft materials without buoyancy, aimed at validating smoke-detector sensitivity.",
        "application": "Quantitative data on detector sensitivity to reduced-gravity smokes for the Fire Prevention, Detection and Suppression programme, per the record.",
        "limitation": "Only 4 of 8 local rows carry values (Teflon); the SAME-R record notes the original SAME particle-collection grids came back contaminated and largely unusable.",
        "measured_columns": ["Weight loss rate (mg/min)"],
        "findings": _findings_same,
        "scores": {"A": (3, "Record: evaluates the adequacy of smoke-detection technology."),
                   "H": (3, "Pyrolysis smoke from spacecraft materials in microgravity."),
                   "F": (2, "Valuable baseline, but its particle samples were compromised and a reflight (SAME-R) was required.")},
        "history": [{"event": "Mir (1997)", "link": "Thematic link", "text": "A fire in an oxygen generator filled the Mir station with smoke. It is a later thematic parallel to SAME's detection goal, not a documented cause of the experiment."}],
    },
    {
        "acc": "PSI-99", "category": "Prevention", "tags": ["Prevention", "Detection"],
        "summary": "Burned large spacecraft material samples inside an uncrewed Cygnus vehicle to compare low-gravity flammability limits with NASA's ground screening test.",
        "application": "Validation of NASA's material-selection criteria at spacecraft scale, and data on how microgravity and limited oxygen affect flame size, as stated in the record.",
        "limitation": "Burn times and lengths are partly qualitative ('Insignificant', '~ 10 cm'); oxygen values are derived from CO2 production (table note 1).",
        "measured_columns": ["Burn Time (s)", "?-g Burn Length"],
        "findings": _findings_saffire2,
        "scores": {"A": (3, "Record: determines microgravity flammability limits and validates material selection."),
                   "H": (3, "Spacecraft-scale fire in a real cargo-vehicle cabin with forced flow."),
                   "F": (3, "Record: informs material selection and future spacecraft fire-safety design.")},
        "history": [{"event": APOLLO1[0], "link": "Thematic link", "text": APOLLO1[1] + " Saffire compares low-g limits with that normal-gravity screening test."}],
    },
    {
        "acc": "PSI-69", "category": "Suppression", "tags": ["Suppression"],
        "summary": "Mapped flammability limits of fuel droplets in microgravity and measured how well gaseous suppressants such as CO2 and helium extinguish flames.",
        "application": "Suppressant selection and concentration targets for crewed vehicles, and predictive extinction models, per the record's stated impacts.",
        "limitation": "Burns isolated liquid droplets in a combustion rack, not cabin solids; burning-rate units are truncated in the table header ('Burning rate; mm').",
        "measured_columns": ["Burning rate; mm", "Burn time; s"],
        "findings": _findings_flex,
        "scores": {"A": (3, "Objective: measure effectiveness of gaseous suppressants (CO2, He, SF6)."),
                   "H": (2, "Microgravity and varied atmospheres, but liquid droplets rather than cabin materials."),
                   "F": (3, "Record: develops predictive models for combustion limits and suppressant efficacy.")},
        "history": [{"event": "Apollo 13 (1970)", "link": "Thematic link", "text": "Damaged wiring ignited inside an oxygen tank, which then failed. A thematic reminder of combustion in oxygen-rich systems; it is not documented as a cause of FLEX."}],
    },
]


def _evidence(rec: dict | None, table: str | None, df: pd.DataFrame | None, measured: list[str]) -> tuple[int, str]:
    """E is computed (no judgement): +1 DOI in the local record; +1 local table with measured
    values in at least MIN_ROWS rows; +1 at least MIN_PUBS publications listed in the record."""
    pts, why = 0, []
    if rec and rec.get("doi"):
        pts += 1; why.append("+1 DOI in local record")
    else:
        why.append("+0 no DOI in local record")
    rows = 0
    if df is not None and measured and all(c in df.columns for c in measured):
        rows = int(pd.concat([_num(df[c]) for c in measured], axis=1).notna().any(axis=1).sum())
    if rows >= MIN_ROWS:
        pts += 1; why.append(f"+1 measured values in {rows} rows of {table}")
    else:
        why.append(f"+0 measured values in only {rows} rows (needs ≥{MIN_ROWS})")
    pubs = len((rec or {}).get("publications") or [])
    if pubs >= MIN_PUBS:
        pts += 1; why.append(f"+1 {pubs} publications listed")
    else:
        why.append(f"+0 {pubs} publications listed (needs ≥{MIN_PUBS})")
    return pts, "; ".join(why) + "."  # noqa


def _doi_checks() -> dict:
    try:
        return json.loads(DOI_CHECK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build(force: bool = False) -> dict:
    sources = [Path(__file__)] + [p for p in DB_DIR.iterdir() if p.is_file()]
    newest = max(p.stat().st_mtime for p in sources)
    if DOI_CHECK_FILE.exists():
        newest = max(newest, DOI_CHECK_FILE.stat().st_mtime)
    if not force and OUT_FILE.exists() and OUT_FILE.stat().st_mtime >= newest:
        try:
            data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if data.get("version") == VERSION:
                return data
        except Exception:
            pass
    checks = _doi_checks()
    items = []
    for s in STUDIES:
        acc = s["acc"]
        rec = _record(acc)
        table, df = _table(acc)
        e, e_why = _evidence(rec, table, df, s["measured_columns"])
        a, h, f = s["scores"]["A"][0], s["scores"]["H"][0], s["scores"]["F"][0]
        try:
            findings = s["findings"](df) if df is not None else ["Local experimental table not available."]
        except Exception as ex:
            findings = [f"Could not compute results from the local table ({type(ex).__name__})."]
        doi = (rec or {}).get("doi") or ""
        chk = checks.get(doi, {})
        items.append({
            "acc": acc,
            "acronym": (rec or {}).get("investigationAcronym") or acc,
            "title": (rec or {}).get("title") or "Record not available",
            "category": s["category"], "tags": s["tags"], "summary": s["summary"],
            "studied": {"objective": _sentences((rec or {}).get("objective"), 2),
                        "hypothesis": _sentences((rec or {}).get("hypothesis"), 1, 300),
                        "hardware": (rec or {}).get("experimentHardware") or ""},
            "findings": findings,
            "application": s["application"],
            "impact_quote": _sentences((rec or {}).get("researchImpacts"), 1, 300),
            "limitation": s["limitation"],
            "source": {
                "record_available": rec is not None,
                "doi": doi, "doi_url": f"https://doi.org/{doi}" if doi else "",
                "doi_check": chk,   # {"ok": bool, "checked": "YYYY-MM-DD", "status": ...} or {}
                "psi_url": f"https://psi.nasa.gov/physci/repo/data/investigations/{acc}",
                "record_file": f"{acc}.json", "record_lib": _lib_id(acc) + ".md",
                "table_file": table, "table_lib": _lib_id(Path(table).stem) + ".csv" if table else None,
                "table_rows": int(len(df)) if df is not None else 0,
                "publications": len((rec or {}).get("publications") or []),
            },
            "history": s["history"],
            "criteria": {
                "A": {"score": a, "why": s["scores"]["A"][1], "editorial": True},
                "H": {"score": h, "why": s["scores"]["H"][1], "editorial": True},
                "E": {"score": e, "why": e_why, "editorial": False},
                "F": {"score": f, "why": s["scores"]["F"][1], "editorial": True},
            },
            "score": flama_score(a, h, e, f),
        })
    items.sort(key=lambda x: (-x["score"], x["acc"]))
    for i, it in enumerate(items, 1):
        it["rank"] = i
    data = {"version": VERSION, "generated": date.today().isoformat(), "weights": WEIGHTS,
            "formula": "round(100 × (0.40·A + 0.25·H + 0.20·E + 0.15·F) / 3)", "items": items}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def check_dois(timeout: float = 15.0) -> dict:
    """Resolve each DOI through the doi.org handle API and store the result (network)."""
    import urllib.request
    out = {}
    for s in STUDIES:
        doi = ((_record(s["acc"]) or {}).get("doi")) or ""
        if not doi:
            continue
        try:
            with urllib.request.urlopen(f"https://doi.org/api/handles/{doi}", timeout=timeout) as r:
                body = json.loads(r.read().decode())
            target = next((v["data"]["value"] for v in body.get("values", []) if v.get("type") == "URL"), "")
            out[doi] = {"ok": body.get("responseCode") == 1, "checked": date.today().isoformat(), "target": target}
        except Exception as e:
            out[doi] = {"ok": False, "checked": date.today().isoformat(), "error": str(e)[:120]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DOI_CHECK_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    if "--check-dois" in sys.argv:
        for doi, r in check_dois().items():
            print(doi, "OK" if r.get("ok") else "FAIL", r.get("target") or r.get("error", ""))
    d = build(force=True)
    for it in d["items"]:
        c = it["criteria"]
        print(f"{it['rank']:02d} {it['acronym']:<11} {it['category']:<11} A{c['A']['score']} H{c['H']['score']} E{c['E']['score']} F{c['F']['score']} -> {it['score']}")
