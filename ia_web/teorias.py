"""teorias.py — FLAMA Theory Lab: cross-document synthesis over the NASA PSI corpus.

Pipeline (Gemini text model; base_de_datos/ is read-only):
  1. CORPUS     133 PSI investigations from _todas_las_investigaciones_PSI.json, enriched with the
                full PSI-XX.json record where one exists (the 24 combustion investigations).
  2. DISCOVER   the model reads a compact view of all investigations and proposes cross-cutting,
                falsifiable hypotheses, each with >= 12 candidate supporting investigations and the
                candidates most likely to contradict or qualify it, plus a microgravity experiment.
  3. VERIFY     for each hypothesis the model re-reads the FULL text of every candidate and returns
                a stance (supports / contradicts / qualifies / irrelevant) with a VERBATIM quote.
                Python then checks that each quote really appears in that document; unverifiable
                entries are discarded, so every cited datum is traceable.
  4. FILTER     keep only hypotheses with >= MIN_SUPPORT distinct verified supporting investigations.
  5. SCORE      probability = (S + 1) / (S + C + 2), with S = verified supporting investigations and
                C = contradicting + 0.5 x qualifying (Laplace-smoothed evidence balance).

Output: static/theories/theories.json (whole corpus) and static/theories/topics/<slug>.json (topic runs).
CLI:    voz\\.venv\\Scripts\\python -m ia_web.teorias [--tema "soot"]
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

RAIZ = Path(__file__).resolve().parent.parent
DB_DIR = RAIZ / "base_de_datos"                    # READ-ONLY
OUT_DIR = RAIZ / "static" / "theories"
sys.path.insert(0, str(RAIZ / "voz"))
sys.path.insert(0, str(RAIZ))

log = logging.getLogger("flama.teorias")
MIN_SUPPORT = 10
# Free tier = ~20 requests/day PER MODEL, so a pool of flash models is rotated when one runs out.
MODELOS = [m.strip() for m in os.getenv("FLAMA_MODELO_TEORIAS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.8-flash,gemini-3.5-flash,"
           "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]
_EXHAUSTED: set = set()


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------
def _clean(v) -> str:
    return " ".join(str(v or "").split())


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[*_`#>|]", " ", t)
    return re.sub(r"[^a-z0-9%.,;:()/+=-]+", " ", t).strip()


def probability(s: int, c: float) -> int:
    """Laplace-smoothed evidence balance in %, S supporting vs C contradicting weight."""
    if s < 0 or c < 0:
        raise ValueError("counts must be >= 0")
    return round(100 * (s + 1) / (s + c + 2))


def quote_in(quote: str, document: str) -> bool:
    """True only if the quote (>= 15 normalised chars) appears verbatim in the document."""
    q = _norm(quote)
    return len(q) >= 15 and q in _norm(document)


def contra_weight(entries) -> float:
    return sum(1.0 if e["stance"] == "contradicts" else 0.5 for e in entries)


def load_corpus() -> list[dict]:
    from biblioteca import _slug

    hits = json.loads((DB_DIR / "_todas_las_investigaciones_PSI.json").read_text(encoding="utf-8"))["hits"]["hits"]
    docs = []
    for h in hits:
        s = h["_source"]
        acc = _clean(s.get("Accession"))
        if not acc:
            continue
        fields = {"Objective": s.get("Objectives"), "Hypothesis": s.get("Hypothesis"), "Approach": s.get("Approach"),
                  "Research impacts": s.get("Research Impacts/Earth Benefits")}
        rec_path = DB_DIR / f"{acc}.json"
        if rec_path.exists():  # richer record for the combustion investigations
            r = json.loads(rec_path.read_text(encoding="utf-8"))
            for label, key in (("Objective", "objective"), ("Hypothesis", "hypothesis"),
                               ("Approach", "approach"), ("Research impacts", "researchImpacts")):
                if len(_clean(r.get(key))) > len(_clean(fields.get(label))):
                    fields[label] = r.get(key)
        title = _clean(s.get("Title"))
        body = "\n".join(f"{k}: {_clean(v)}" for k, v in fields.items() if _clean(v))
        docs.append({
            "acc": acc, "title": title, "acronym": _clean(s.get("Acronym")),
            "area": _clean(s.get("Research Area")), "keywords": " · ".join(x for x in re.split(r"\s{3,}", str(s.get("Keywords") or "")) if x.strip()),
            "text": f"Title: {title}\n{body}", "lib": _slug(acc) + ".md",
        })
    docs.sort(key=lambda d: int(re.sub(r"\D", "", d["acc"]) or 0))
    return docs


def compact_view(docs: list[dict], per_doc: int = 650) -> str:
    out = []
    for d in docs:
        obj = re.search(r"Objective: (.*)", d["text"])
        hyp = re.search(r"Hypothesis: (.*)", d["text"])
        txt = f"[{d['acc']}] ({d['area']}) {d['title']} | kw: {d['keywords'][:120]}"
        if obj:
            txt += f" | Obj: {obj.group(1)[:per_doc]}"
        if hyp:
            txt += f" | Hyp: {hyp.group(1)[:per_doc // 2]}"
        out.append(txt)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Structured outputs
# ---------------------------------------------------------------------------
class Experiment(BaseModel):
    title: str
    design: str = Field(description="What to run in microgravity, step by step, 2-4 sentences.")
    variables: list[str] = Field(description="Independent variables to sweep.")
    measurements: list[str] = Field(description="What to measure to confirm or refute the hypothesis.")
    platform: str = Field(description="Plausible platform: ISS rack, Cygnus/Saffire-like vehicle, sounding rocket, drop tower...")


class Candidate(BaseModel):
    title: str
    hypothesis: str = Field(description="The new, falsifiable hypothesis and its physical rationale, 3-5 sentences.")
    summary: str = Field(description="One sentence, max 30 words.")
    tags: list[str] = Field(description="3-6 lowercase topic tags, e.g. soot, droplets, convection.")
    support_candidates: list[str] = Field(description="Accessions (PSI-XX) expected to SUPPORT it; at least 12.")
    against_candidates: list[str] = Field(description="Accessions (PSI-XX) likely to contradict or qualify it.")
    experiment: Experiment


class Discovery(BaseModel):
    theories: list[Candidate]


class Stance(BaseModel):
    acc: str
    stance: Literal["supports", "contradicts", "qualifies", "irrelevant"]
    quote: str = Field(description="VERBATIM sentence fragment copied exactly from that document's text (20-300 chars).")
    datum: str = Field(description="One sentence: what this document shows that bears on the hypothesis.")


class Verification(BaseModel):
    stances: list[Stance]


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
def _client():
    from google import genai
    from ia_llama import config

    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY missing (voz/.env)")
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _ask(client, prompt: str, schema, temperature: float, state: dict):
    from google.genai import types

    last = None
    order = ([state["model"]] if state.get("model") else []) + MODELOS
    for model in dict.fromkeys(order):
        if model in _EXHAUSTED:
            continue
        for attempt in range(2):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json",
                                                       response_schema=schema, temperature=temperature))
                state["model"] = model
                return schema.model_validate_json(r.text)
            except Exception as e:
                last = e
                msg = str(e)
                if "404" in msg or "not found" in msg.lower():
                    _EXHAUSTED.add(model)        # model retired for this key
                    break
                if "PerDay" in msg or "per day" in msg.lower():
                    _EXHAUSTED.add(model)        # free-tier daily quota spent: switch model immediately
                    break
                time.sleep(3 * (attempt + 1))    # per-minute limit / overload: short back-off
    raise RuntimeError(f"Gemini quota or availability exhausted on every model ({', '.join(MODELOS)}): {str(last)[:300]}")


DISCOVER_PROMPT = """You are a research synthesist working ONLY from the NASA Physical Sciences Informatics (PSI) corpus below
({n} investigations: id, research area, title, keywords, objective, hypothesis).

Task: find hidden cross-cutting patterns and formulate {k} NEW scientific hypotheses that are still to be confirmed.
Rules:
- Each hypothesis must connect findings or premises from many DIFFERENT investigations (ideally across research areas),
  not restate a single study. It must be falsifiable and phrased so a microgravity experiment could test it.
- Prefer MECHANISM-level hypotheses (e.g. how removing buoyancy-driven convection changes transport, residence time,
  interface dynamics, particle growth, extinction) that many investigations' own objectives and hypotheses speak to,
  so that at least 10 different investigations can be shown to support it from their own text.
- support_candidates: at least 12 accessions from the corpus whose text plausibly supports it. Use only ids that appear below.
- against_candidates: accessions whose text plausibly contradicts or qualifies it (can be empty if none).
- Propose one concrete microgravity experiment per hypothesis.
- Do not invent numbers or results that are not in the corpus.
{topic}
CORPUS:
{corpus}
"""

VERIFY_PROMPT = """Hypothesis to evaluate:
TITLE: {title}
HYPOTHESIS: {hypothesis}

Below are full texts of NASA PSI investigations. For EACH document, decide its stance toward the hypothesis:
- supports: the document's own text states a premise, observation or result consistent with the hypothesis
- contradicts: its text states something inconsistent with the hypothesis
- qualifies: its text limits the hypothesis (only under some conditions, different mechanism, mixed evidence)
- irrelevant: nothing in the text bears on it
For every stance except irrelevant, copy a VERBATIM fragment (20-300 characters) from that document's text that justifies it,
exactly as written (same words, same order). Never paraphrase inside "quote". Be strict: topical similarity alone is not support.

DOCUMENTS:
{docs}
"""


def discover(client, docs, k: int, tema: str | None, state: dict) -> list[Candidate]:
    topic = (f"- FOCUS: every hypothesis must be about this topic requested by the user: \"{tema}\".\n" if tema else "")
    prev = OUT_DIR / "theories.json"
    if not tema and prev.exists():  # steer new batches away from hypotheses already established
        try:
            done = [t["title"] for t in json.loads(prev.read_text(encoding="utf-8")).get("theories", [])]
            if done:
                topic += "- Do NOT repeat these already-established hypotheses: " + "; ".join(done) + "\n"
        except Exception:
            pass
    prompt = DISCOVER_PROMPT.format(n=len(docs), k=k, topic=topic, corpus=compact_view(docs))
    return _ask(client, prompt, Discovery, 0.6, state).theories


_IDF: dict = {}


def lexical_candidates(cand: Candidate, docs: list[dict], n: int = 24) -> list[str]:
    """Extra candidates by idf-weighted keyword overlap with the hypothesis, so verification is
    not limited to the documents the discovery step happened to name."""
    if not _IDF:
        import math
        df: dict = {}
        for d in docs:
            for w in set(_norm(d["text"]).split()):
                df[w] = df.get(w, 0) + 1
        _IDF.update({w: math.log(len(docs) / c) for w, c in df.items() if len(w) > 3 and c < len(docs) * 0.6})
    q = {w for w in _norm(" ".join([cand.title, cand.hypothesis] + cand.tags)).split() if w in _IDF}
    scored = sorted(((sum(_IDF[w] for w in q & set(_norm(d["text"]).split())), d["acc"]) for d in docs), reverse=True)
    return [a for sc, a in scored[:n] if sc > 0]


def _verify_chunk(client, cand: Candidate, accs: list[str], by_acc: dict, state: dict) -> list:
    blocks = "\n\n".join(f"=== {a} ===\n{by_acc[a]['text'][:3200]}" for a in accs)
    prompt = VERIFY_PROMPT.format(title=cand.title, hypothesis=cand.hypothesis, docs=blocks)
    res = None
    res = _ask(client, prompt, Verification, 0.1, state)
    if len(res.stances) < max(1, len(accs) // 3):   # empty / truncated answer: retry once
        res = _ask(client, prompt, Verification, 0.1, state)
    return res.stances if res else []


def verify(client, cand: Candidate, by_acc: dict, state: dict, docs: list[dict] | None = None) -> dict:
    named = [a.strip().upper() for a in cand.support_candidates + cand.against_candidates]
    extra = lexical_candidates(cand, docs) if docs else []
    accs = [a for a in dict.fromkeys(named + extra) if a in by_acc][:30]
    stances = _verify_chunk(client, cand, accs, by_acc, state)   # one call per hypothesis (quota-friendly)
    support, against, rejected = {}, {}, 0
    for st in stances:
        acc = st.acc.strip().upper()
        if acc not in by_acc or acc not in accs or st.stance == "irrelevant":
            continue
        if not quote_in(st.quote, by_acc[acc]["text"]):
            rejected += 1          # quote not found verbatim: discard (anti-hallucination)
            continue
        entry = {"acc": acc, "title": by_acc[acc]["title"], "area": by_acc[acc]["area"], "datum": st.datum.strip(),
                 "quote": st.quote.strip(), "lib": by_acc[acc]["lib"], "stance": st.stance}
        (support if st.stance == "supports" else against).setdefault(acc, entry)
    s = len(support)
    c = contra_weight(against.values())
    return {
        "title": cand.title.strip(), "hypothesis": cand.hypothesis.strip(), "summary": cand.summary.strip(),
        "tags": [t.lower().strip() for t in cand.tags][:6], "experiment": cand.experiment.model_dump(),
        "support": list(support.values()), "against": list(against.values()),
        "n_support": s, "n_against": len(against), "contra_weight": c,
        "probability": probability(s, c),
        "checked": len(accs), "quotes_rejected": rejected,
    }


def run(tema: str | None = None, k: int = 12, workers: int = 12) -> dict:
    t0 = time.time()
    docs = load_corpus()
    by_acc = {d["acc"]: d for d in docs}
    client, state = _client(), {}
    cands = discover(client, docs, k, tema, state)
    print(f"discovered {len(cands)} candidate hypotheses ({round(time.time() - t0)} s); verifying…", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda c: _safe_verify(client, c, by_acc, state, docs), cands))
    results = [r for r in results if r]
    kept = [r for r in results if r["n_support"] >= MIN_SUPPORT]
    kept.sort(key=lambda r: (-r["probability"], -r["n_support"]))
    for i, r in enumerate(kept, 1):
        r["rank"] = i
        r["id"] = f"T{i:02d}" + (f"-{_slug_topic(tema)}" if tema else "")
    return {
        "generated": date.today().isoformat(), "model": state.get("model"), "topic": tema,
        "corpus": {"investigations": len(docs), "areas": sorted({d["area"] for d in docs if d["area"]})},
        "rules": {"min_support": MIN_SUPPORT, "probability": "(S + 1) / (S + C + 2); S = verified supporting investigations, "
                  "C = contradicting + 0.5 × qualifying", "verification": "every quote must appear verbatim in its PSI document"},
        "stats": {"candidates": len(cands), "verified": len(results), "kept": len(kept),
                  "discarded_low_support": len(results) - len(kept),
                  "quotes_rejected": sum(r["quotes_rejected"] for r in results), "seconds": round(time.time() - t0)},
        "theories": kept,
        "discarded": [{"title": r["title"], "n_support": r["n_support"], "n_against": r["n_against"]}
                      for r in results if r["n_support"] < MIN_SUPPORT],
    }


def _safe_verify(client, cand, by_acc, state, docs=None):
    try:
        r = verify(client, cand, by_acc, state, docs)
        print(f"  verified: {r['n_support']:2d} for / {r['n_against']} against  {r['title'][:70]}", flush=True)
        return r
    except Exception as e:
        log.warning("verification failed for %r: %s", cand.title, e)
        return None


def _slug_topic(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(t or ""))[:40].strip("-") or "topic"


def merge(old: dict, new: dict) -> dict:
    """Add new theories to a previous synthesis, skipping near-duplicates (same normalised title or
    >= 70 % overlap of supporting investigations), then re-rank."""
    out = dict(new)
    kept = list(old.get("theories", []))
    for t in new.get("theories", []):
        sup = {d["acc"] for d in t["support"]}
        dup = any(_norm(t["title"]) == _norm(o["title"]) or
                  len(sup & {d["acc"] for d in o["support"]}) >= 0.7 * min(len(sup), len(o["support"])) for o in kept)
        if not dup:
            kept.append(t)
    kept.sort(key=lambda r: (-r["probability"], -r["n_support"]))
    for i, r in enumerate(kept, 1):
        r["rank"], r["id"] = i, f"T{i:02d}"
    st_o, st_n = old.get("stats", {}), new.get("stats", {})
    out["stats"] = {k: st_o.get(k, 0) + st_n.get(k, 0)
                    for k in ("candidates", "verified", "discarded_low_support", "quotes_rejected", "seconds")}
    out["stats"]["kept"] = len(kept)
    out["stats"]["runs"] = st_o.get("runs", 1) + 1
    out["discarded"] = old.get("discarded", []) + new.get("discarded", [])
    out["theories"] = kept
    return out


def save(data: dict) -> Path:
    path = OUT_DIR / "theories.json" if not data.get("topic") else OUT_DIR / "topics" / f"{_slug_topic(data['topic'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--tema", default=None)
    ap.add_argument("-k", type=int, default=12)
    ap.add_argument("--merge", action="store_true", help="add to the existing theories.json instead of replacing it")
    a = ap.parse_args()
    d = run(a.tema, a.k)
    prev = OUT_DIR / "theories.json"
    if a.merge and not a.tema and prev.exists():
        d = merge(json.loads(prev.read_text(encoding="utf-8")), d)
    p = save(d)
    print(json.dumps(d["stats"], indent=1), "model:", d["model"], "->", p)
    for t in d["theories"]:
        print(f"{t['rank']:02d} {t['probability']:3d}%  ✓{t['n_support']:2d} ⚠{t['n_against']}  {t['title']}")
