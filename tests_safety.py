"""Tests for the SAFETY MECHANISMS adapter (safety_research.py).

    .venv\\Scripts\\python -m unittest tests_safety -v
    set FLAMA_NET=1 to also resolve every DOI online through doi.org.
"""
import hashlib
import json
import os
import unittest
import urllib.request
from pathlib import Path

import safety_research as sr

ROOT = Path(__file__).resolve().parent


def db_fingerprint() -> dict:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(sr.DB_DIR.iterdir()) if p.is_file()}


class TestFlamaScore(unittest.TestCase):
    def test_extremes(self):
        self.assertEqual(sr.flama_score(0, 0, 0, 0), 0)
        self.assertEqual(sr.flama_score(3, 3, 3, 3), 100)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(sr.WEIGHTS.values()), 1.0)

    def test_known_values(self):
        # round(100*(0.40*3 + 0.25*2 + 0.20*3 + 0.15*3)/3) = round(91.67) = 92
        self.assertEqual(sr.flama_score(3, 2, 3, 3), 92)
        # round(100*(0.40*3 + 0.25*3 + 0.20*1 + 0.15*3)/3) = round(86.67) = 87
        self.assertEqual(sr.flama_score(3, 3, 1, 3), 87)
        # single criteria at full score equal their weight
        self.assertEqual(sr.flama_score(3, 0, 0, 0), 40)
        self.assertEqual(sr.flama_score(0, 3, 0, 0), 25)
        self.assertEqual(sr.flama_score(0, 0, 3, 0), 20)
        self.assertEqual(sr.flama_score(0, 0, 0, 3), 15)

    def test_monotonic(self):
        for crit in range(4):
            prev = -1
            for v in range(4):
                args = [0, 0, 0, 0]
                args[crit] = v
                s = sr.flama_score(*args)
                self.assertGreater(s, prev)
                prev = s

    def test_rejects_out_of_range(self):
        for bad in (-1, 4, 1.5, True, "3"):
            with self.assertRaises(ValueError):
                sr.flama_score(bad, 0, 0, 0)


class TestResearchData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = db_fingerprint()
        cls.data = sr.build(force=True)

    def test_database_untouched(self):
        self.assertEqual(db_fingerprint(), self.before, "base_de_datos/ changed during build()")

    def test_four_to_six_studies(self):
        self.assertTrue(4 <= len(self.data["items"]) <= 6)

    def test_scores_match_formula_and_ranks(self):
        items = self.data["items"]
        for it in items:
            c = it["criteria"]
            self.assertEqual(it["score"], sr.flama_score(c["A"]["score"], c["H"]["score"], c["E"]["score"], c["F"]["score"]))
            self.assertTrue(c["A"]["why"] and c["H"]["why"] and c["E"]["why"] and c["F"]["why"])
            self.assertFalse(c["E"]["editorial"], "E must be computed, not editorial")
        self.assertEqual([it["rank"] for it in items], list(range(1, len(items) + 1)))
        self.assertEqual([it["score"] for it in items], sorted((it["score"] for it in items), reverse=True))

    def test_summary_length(self):
        for it in self.data["items"]:
            n = len(it["summary"].split())
            self.assertTrue(18 <= n <= 22, f"{it['acronym']} summary has {n} words")

    def test_doi_matches_local_record(self):
        for it in self.data["items"]:
            rec = json.loads((sr.DB_DIR / f"{it['acc']}.json").read_text(encoding="utf-8"))
            self.assertEqual(it["source"]["doi"], rec["doi"])
            self.assertTrue(it["source"]["doi"].startswith("10.60555/"))
            self.assertEqual(it["source"]["doi_url"], "https://doi.org/" + rec["doi"])

    def test_library_files_exist(self):
        lib = ROOT / "static" / "library"
        if not lib.exists():
            self.skipTest("text library not generated yet (run the web once)")
        for it in self.data["items"]:
            self.assertTrue((lib / it["source"]["record_lib"]).exists(), it["source"]["record_lib"])
            if it["source"]["table_lib"]:
                self.assertTrue((lib / it["source"]["table_lib"]).exists(), it["source"]["table_lib"])

    def test_categories_and_history_labels(self):
        cats = {it["category"] for it in self.data["items"]}
        self.assertEqual(cats, {"Prevention", "Detection", "Suppression"})
        for it in self.data["items"]:
            self.assertIn(it["category"], it["tags"])
            for h in it["history"]:
                self.assertIn(h["link"], {"Direct historical consequence", "Thematic link"})

    def test_findings_computed_not_empty(self):
        for it in self.data["items"]:
            self.assertTrue(it["findings"], it["acronym"])
            self.assertFalse(any("Could not compute" in f for f in it["findings"]), it["acronym"])

    @unittest.skipUnless(os.getenv("FLAMA_NET") == "1", "set FLAMA_NET=1 to resolve DOIs online")
    def test_dois_resolve_online(self):
        for it in self.data["items"]:
            doi = it["source"]["doi"]
            with urllib.request.urlopen(f"https://doi.org/api/handles/{doi}", timeout=20) as r:
                body = json.loads(r.read().decode())
            self.assertEqual(body.get("responseCode"), 1, doi)
            urls = [v["data"]["value"] for v in body["values"] if v.get("type") == "URL"]
            self.assertTrue(any(it["acc"] in u for u in urls), f"{doi} -> {urls}")


if __name__ == "__main__":
    unittest.main()
