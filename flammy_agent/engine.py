"""Flammy rule engine: turns a scenario (simulation parameters and/or free text)
into a fire-safety Advisory. Pure Python, no dependencies, no network."""
from __future__ import annotations

import itertools
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import knowledge as K

LEVELS = {"info": 1, "caution": 2, "danger": 3}
SIGNAL = {"info": "blue", "caution": "amber", "danger": "red"}   # suggested flame colour
_ids = itertools.count(1)


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s if s is not None else "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# ----------------------------------------------------------- text extraction
_GRAV = [
    ("micro", r"microgravity|micro-gravity|zero[- ]?g\b|zero gravity|weightless|freefall|free-fall|\b0 ?g\b|\biss\b|space station"),
    ("lunar", r"\bmoon\b|lunar|\b1/6\b|0\.16|artemis"),
    ("earth", r"\bearth\b|\b1 ?g\b|normal gravity|terrestrial|ground[- ]based|drop tower on earth"),
]
_IGN = [
    ("battery", r"batter|li-?ion|lithium|laptop|tablet|power ?bank|thermal runaway"),
    ("electrical", r"spark|short[- ]circuit|electrical|overheat|\barc(ing)?\b"),
    ("hot", r"hot surface|heater|heating element"),
    ("flame", r"open flame|welding|candle|lighter|\bmatch(es)?\b"),
]
_TOPIC = [
    ("fire", r"\bfire\b|\bburn|combust|ignit|blaze"),
    ("flame", r"flame|spherical|\bblue\b|invisible|visible"),
    ("extinguisher", r"extinguish|suppress|put out|fire[- ]?fight"),
    ("smoke", r"smoke|detector|alarm|detection"),
    ("gas", r"\bgas(es)?\b|carbon monoxide|toxic|\bco2\b|\bco\b|fumes"),
    ("standard", r"standard|6001|certif|qualif|approved|rated"),
]
_MAT = {mid: [re.compile(r"(?<![a-z0-9])" + re.escape(_norm(a)).replace(r"\ ", r"[\s-]?").replace(r"\-", r"[\s-]?") + r"(?![a-z0-9])")
              for a in m["aliases"]] for mid, m in K.MATERIALS.items()}
_GRAV_RE = [(g, re.compile(p)) for g, p in _GRAV]
_IGN_RE = [(g, re.compile(p)) for g, p in _IGN]
_TOPIC_RE = [(g, re.compile(p)) for g, p in _TOPIC]
_O2_A = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:of\s*)?(?:o2|oxygen)")
_O2_B = re.compile(r"(?:o2|oxygen)[^\d%]{0,25}(\d{1,2}(?:\.\d+)?)\s*%")
_PRESS = re.compile(r"(\d+(?:\.\d+)?)\s*(psia|psi|kpa|atm|bar)\b")
_PUNIT = {"psia": 6.894757, "psi": 6.894757, "kpa": 1.0, "atm": 101.325, "bar": 100.0}
_VENT_NONE = re.compile(r"no ventilation|without ventilation|still air|quiescent|no airflow|no air flow|stagnant|fan off|ventilation off|no flow")
_VENT_FORCED = re.compile(r"ventilation|\bfan\b|airflow|air flow|forced flow|draft")


def _grav_from(v: Any) -> Optional[str]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "micro" if v <= 0.05 else ("lunar" if v <= 0.5 else "earth")
    n = _norm(v)
    if n in ("micro", "lunar", "earth"):
        return n
    for g, rx in _GRAV_RE:
        if rx.search(n):
            return g
    return None


def _mats_from(n: str) -> List[str]:
    return [mid for mid, rxs in _MAT.items() if any(r.search(n) for r in rxs)]


@dataclass
class Context:
    gravities: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    ignitions: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    o2: Optional[float] = None
    pressure_kpa: Optional[float] = None
    ventilation: Optional[str] = None
    assumed_gravity: bool = False


def extract(text: str) -> Context:
    n = _norm(text)
    c = Context()
    found = []
    for g, rx in _GRAV_RE:
        m = rx.search(n)
        if m:
            found.append((m.start(), g))
    c.gravities = [g for _, g in sorted(found)]
    c.materials = _mats_from(n)
    c.ignitions = [g for g, rx in _IGN_RE if rx.search(n)]
    c.topics = [g for g, rx in _TOPIC_RE if rx.search(n)]
    m = _O2_A.search(n) or _O2_B.search(n)
    if m:
        c.o2 = float(m.group(1))
    p = _PRESS.search(n)
    if p:
        c.pressure_kpa = float(p.group(1)) * _PUNIT[p.group(2)]
    if _VENT_NONE.search(n):
        c.ventilation = "none"
    elif _VENT_FORCED.search(n):
        c.ventilation = "forced"
    return c


def _uniq(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def _as_list(v) -> list:
    return [] if v is None else (list(v) if isinstance(v, (list, tuple, set)) else [v])


def build_context(params: Optional[Dict[str, Any]] = None, text: str = "", default_gravity: str = "micro") -> Context:
    """Explicit parameters win over what is parsed from text."""
    params = params or {}
    c = extract(text) if text else Context()
    if params.get("gravity") is not None:
        g = _grav_from(params["gravity"])
        if g:
            c.gravities = [g]
    for m in _as_list(params.get("material")):
        c.materials = _uniq(c.materials + ([m] if m in K.MATERIALS else _mats_from(_norm(m))))
    if params.get("o2") is not None:
        o2 = float(params["o2"])
        c.o2 = o2 * 100 if o2 <= 1 else o2
    if params.get("pressure_kpa") is not None:
        c.pressure_kpa = float(params["pressure_kpa"])
    elif params.get("pressure_psi") is not None:
        c.pressure_kpa = float(params["pressure_psi"]) * 6.894757
    v = params.get("ventilation")
    if v in ("none", 0):
        c.ventilation = "none"
    elif v == "forced" or (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
        c.ventilation = "forced"
    if params.get("flow_cm_s") is not None:
        c.ventilation = "forced" if float(params["flow_cm_s"]) > 0 else "none"
    c.ignitions = _uniq(c.ignitions + _as_list(params.get("ignition")))
    c.topics = _uniq(c.topics + _as_list(params.get("topic")))
    if "battery" in c.materials:
        c.ignitions = _uniq(c.ignitions + ["battery"])
    if "electrical" in c.materials:
        c.ignitions = _uniq(c.ignitions + ["electrical"])
    if not c.gravities:
        c.gravities, c.assumed_gravity = [default_gravity], True
    return c


def _matches(w: Dict[str, Any], c: Context) -> bool:
    def any_of(wanted, have):
        return any(x in have for x in wanted)
    if "gravity" in w and not any_of(w["gravity"], c.gravities): return False
    if "material" in w and not any_of(w["material"], c.materials): return False
    if "ignition" in w and not any_of(w["ignition"], c.ignitions): return False
    if "topic" in w and not any_of(w["topic"], c.topics): return False
    if "o2_min" in w and (c.o2 is None or c.o2 < w["o2_min"]): return False
    if "o2_max" in w and (c.o2 is None or c.o2 > w["o2_max"]): return False
    if "pressure_max_kpa" in w and (c.pressure_kpa is None or c.pressure_kpa > w["pressure_max_kpa"]): return False
    if "ventilation" in w and (c.ventilation is None or c.ventilation not in w["ventilation"]): return False
    return True


def _srcs(ids) -> List[Dict[str, str]]:
    return [dict(K.SOURCES[i], id=i) for i in _uniq(_as_list(ids)) if i in K.SOURCES]


@dataclass
class Advisory:
    """What Flammy tells you about one event. Render it however your UI likes."""
    id: int
    timestamp: float
    event_type: str                 # simulation | question | experiment | manual
    level: str                      # info | caution | danger
    signal: str                     # blue | amber | red  (suggested flame colour)
    headline: str                   # short title of the main hazard
    summary: str                    # one sentence: why it is dangerous and what to do
    hazards: List[Dict[str, Any]]   # each: id, level, title, summary, why[], actions[], sources[]
    actions: List[str]              # merged top actions
    if_fire: Dict[str, Any]         # regime, label, steps[], class_notes[], sources[]
    sources: List[Dict[str, str]]
    context: Dict[str, Any]
    assumed_gravity: bool
    experiment: Optional[Dict[str, str]] = None
    repeat: bool = False            # same hazards as the previous event of this type (don't re-alert)
    disclaimer: str = K.DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.headline} - {self.summary}"


def advise(params: Optional[Dict[str, Any]] = None, text: str = "", event_type: str = "manual",
           default_gravity: str = "micro", experiment: Optional[Dict[str, Any]] = None,
           extra_rules: Optional[List[Dict[str, Any]]] = None, max_hazards: int = 4) -> Advisory:
    c = build_context(params, text, default_gravity)
    rules = list(K.RULES) + list(extra_rules or [])
    hit = sorted((r for r in rules if _matches(r["when"], c)),
                 key=lambda r: -(LEVELS[r["level"]] * 10 + len(r["when"]) * 2))[:max_hazards]
    if not hit:
        f = K.FALLBACK
        hit = [{"id": "fallback", "level": "info", **{k: f[k] for k in ("title", "short", "why", "actions", "sources")}}]
    lvl = max((r["level"] for r in hit), key=LEVELS.get)

    regime = c.gravities[0]
    fr = K.FIRE_RESPONSE.get(regime, K.FIRE_RESPONSE["micro"])
    classes = _uniq([K.MATERIALS[m]["cls"] for m in c.materials]
                    + (["C"] if "electrical" in c.ignitions else []) + (["battery"] if "battery" in c.ignitions else []))
    all_src = [s for r in hit for s in r["sources"]] + (experiment or {}).get("sources", [])
    top = hit[0]
    return Advisory(
        id=next(_ids), timestamp=time.time(), event_type=event_type, level=lvl, signal=SIGNAL[lvl],
        headline=top["title"], summary=top["short"][0].upper() + top["short"][1:],
        hazards=[{"id": r["id"], "level": r["level"], "title": r["title"], "summary": r["short"],
                  "why": r["why"], "actions": r["actions"], "sources": _srcs(r["sources"])} for r in hit],
        actions=_uniq([a for r in hit for a in r["actions"]])[:6],
        if_fire={"regime": regime, "label": fr["label"], "steps": fr["steps"],
                 "class_notes": [K.CLASS_NOTES[x] for x in classes if x in K.CLASS_NOTES], "sources": _srcs(fr["sources"])},
        sources=_srcs(all_src),
        context={"gravity": regime, "gravities": c.gravities, "materials": c.materials, "ignitions": c.ignitions,
                 "o2_percent": c.o2, "pressure_kpa": c.pressure_kpa, "ventilation": c.ventilation, "topics": c.topics},
        assumed_gravity=c.assumed_gravity,
        experiment={"name": experiment["name"], "note": experiment["note"]} if experiment else None,
    )
