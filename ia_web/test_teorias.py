"""Offline tests for the Theory Lab engine (no API calls).

    voz\.venv\Scripts\python -m unittest ia_web.test_teorias -v
"""
import hashlib
import json
import unittest
from pathlib import Path

from ia_web import teorias as T

ROOT = Path(__file__).resolve().parent.parent


class TestFormula(unittest.TestCase):
    def test_probability_values(self):
        self.assertEqual(T.probability(0, 0), 50)          # no evidence -> 50 %
        self.assertEqual(T.probability(10, 0), 92)         # 11/12
        self.assertEqual(T.probability(10, 2), 79)         # 11/14
        self.assertEqual(T.probability(20, 1.5), 89)       # 21/23.5 = 0.894

    def test_probability_monotonic(self):
        self.assertLess(T.probability(10, 3), T.probability(10, 1))
        self.assertGreater(T.probability(14, 1), T.probability(10, 1))
        with self.assertRaises(ValueError):
            T.probability(-1, 0)

    def test_contra_weight(self):
        e = [{"stance": "contradicts"}, {"stance": "qualifies"}, {"stance": "qualifies"}]
        self.assertEqual(T.contra_weight(e), 2.0)


class TestQuoteVerification(unittest.TestCase):
    def setUp(self):
        self.docs = {d["acc"]: d for d in T.load_corpus()}

    def test_real_quote_accepted(self):
        flex = self.docs["PSI-69"]["text"]
        frag = flex.split("Objective: ")[1][:120]
        self.assertTrue(T.quote_in(frag, flex))
        self.assertTrue(T.quote_in(frag.upper().replace(" ", "  "), flex))  # case / spacing tolerant

    def test_paraphrase_rejected(self):
        flex = self.docs["PSI-69"]["text"]
        self.assertFalse(T.quote_in("FLEX proved that helium is always the best suppressant in space", flex))
        self.assertFalse(T.quote_in("microgravity", flex))                 # too short to count as evidence

    def test_corpus(self):
        self.assertEqual(len(self.docs), 133)
        self.assertTrue(all(d["text"] and d["lib"].endswith(".md") for d in self.docs.values()))


class TestPublishedTheories(unittest.TestCase):
    path = ROOT / "static" / "theories" / "theories.json"

    @unittest.skipUnless((ROOT / "static" / "theories" / "theories.json").exists(), "no synthesis yet")
    def test_rules_hold(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        docs = {d["acc"]: d for d in T.load_corpus()}
        for t in data["theories"]:
            self.assertGreaterEqual(t["n_support"], T.MIN_SUPPORT, t["title"])
            self.assertEqual(len({d["acc"] for d in t["support"]}), t["n_support"])      # independent investigations
            self.assertEqual(t["probability"], T.probability(t["n_support"], T.contra_weight(t["against"])))
            for d in t["support"] + t["against"]:
                self.assertTrue(T.quote_in(d["quote"], docs[d["acc"]]["text"]), (t["title"], d["acc"]))
                self.assertTrue((ROOT / "static" / "library" / d["lib"]).exists(), d["lib"])
        probs = [t["probability"] for t in data["theories"]]
        self.assertEqual(probs, sorted(probs, reverse=True))


class TestDatabaseReadOnly(unittest.TestCase):
    def test_load_does_not_write(self):
        before = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in T.DB_DIR.iterdir() if p.is_file()}
        T.load_corpus()
        after = {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in T.DB_DIR.iterdir() if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
