"""flama_type.py — FLAMA type rule: UPPERCASE letters in Roboto Condensed, lowercase in Chalet.

CSS cannot style by letter case, so the rule is built with @font-face unicode-range: one family,
"FlamaType", made of two faces.
  1. Chalet face (declared FIRST, full range): lowercase, digits, punctuation, everything else.
  2. Roboto Condensed face (declared LAST, capitals only): A–Z plus accented capitals (Á É Í Ó Ú Ñ Ü...).
When ranges overlap, the browser uses the face declared last, so capitals always resolve to
Roboto Condensed.

Chalet is a commercial typeface (House Industries) and is not bundled. It is picked up from:
  * an installed system font (local("Chalet ..."), or
  * a file you drop in static/fonts/ whose name starts with "chalet" (.woff2/.woff/.otf/.ttf).
Until then, Jost (OFL, a geometric sans in the same family of shapes) stands in.
Roboto Condensed and Jost are self-hosted from static/fonts/ (both SIL Open Font License).
"""
from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
URL = "/app/static/fonts/"
_FORMATS = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype", ".ttf": "truetype"}

CAPITALS = "U+0041-005A, U+00C0-00D6, U+00D8-00DE, U+0100, U+0102, U+0104, U+0106, U+010C, U+0118, U+011A, U+0141, U+0143, U+0147, U+0150, U+0152, U+0158, U+015A, U+0160, U+0164, U+016E, U+0170, U+0178, U+0179, U+017B, U+017D"


def chalet_files() -> list[Path]:
    if not FONT_DIR.exists():
        return []
    return sorted(p for p in FONT_DIR.iterdir() if p.name.lower().startswith("chalet") and p.suffix.lower() in _FORMATS)


def chalet_available() -> bool:
    return bool(chalet_files())


def font_face_css() -> str:
    chalet_src = [
        'local("Chalet")', 'local("Chalet-ParisNineteenSixty")', 'local("Chalet Paris Nineteen Sixty")',
        'local("Chalet-LondonNineteenSixty")', 'local("Chalet London Nineteen Sixty")',
        'local("Chalet-NewYorkNineteenSixty")', 'local("Chalet New York Nineteen Sixty")',
    ]
    chalet_src += [f'url("{URL}{p.name}") format("{_FORMATS[p.suffix.lower()]}")' for p in chalet_files()]
    chalet_src.append(f'url("{URL}jost-latin.woff2") format("woff2")')
    return f"""
  /* FLAMA type rule — lowercase: Chalet (Jost stand-in until Chalet is installed) */
  @font-face {{
    font-family: "FlamaType"; font-style: normal; font-weight: 300 800; font-display: swap;
    src: {", ".join(chalet_src)};
  }}
  @font-face {{
    font-family: "FlamaType"; font-style: normal; font-weight: 300 800; font-display: swap;
    src: url("{URL}jost-latin-ext.woff2") format("woff2");
    unicode-range: U+0100-024F, U+1E00-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF;
  }}
  /* FLAMA type rule — UPPERCASE: Roboto Condensed (declared last: wins on capitals) */
  @font-face {{
    font-family: "FlamaType"; font-style: normal; font-weight: 300 800; font-display: swap;
    src: local("Roboto Condensed"), url("{URL}roboto-condensed-latin.woff2") format("woff2");
    unicode-range: {CAPITALS};
  }}
"""


FAMILY = '"FlamaType", "Segoe UI", system-ui, sans-serif'
