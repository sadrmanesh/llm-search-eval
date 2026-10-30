"""Script-aware text utilities for English and Persian queries.

Persian text found in real catalogs is frequently written with Arabic code points
(``ي`` and ``ك``), mixed digit systems, diacritics, and the zero-width non-joiner.
Normalizing these consistently lets lexical tooling (the mock judge, validation)
treat equivalent spellings as equal.
"""

from __future__ import annotations

import re
import unicodedata

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",  # Arabic yeh -> Persian yeh
        "ى": "ی",  # alef maksura -> Persian yeh
        "ك": "ک",  # Arabic kaf -> Persian keheh
        "ة": "ه",  # teh marbuta -> heh
        "ۀ": "ه",  # heh with yeh above -> heh
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
        "ـ": None,  # tatweel
        "\u200c": " ",  # zero-width non-joiner
        "\u200d": None,  # zero-width joiner
        "\u200f": None,  # right-to-left mark
        "\u200e": None,  # left-to-right mark
        **{chr(0x06F0 + i): str(i) for i in range(10)},  # Persian digits
        **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic digits
    }
)

# Arabic diacritics (harakat), superscript alef and Quranic marks.
_DIACRITICS = re.compile("[\u064b-\u065f\u0670\u06d6-\u06ed]")
_TOKEN = re.compile(r"\w+", re.UNICODE)
_ARABIC_SCRIPT = re.compile("[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]")
_LATIN = re.compile("[A-Za-z]")

_STOPWORDS = frozenset(
    {
        # English
        "a", "an", "and", "are", "for", "from", "in", "is", "of", "on", "or",
        "the", "to", "with", "without", "best", "buy", "cheap", "new",
        # Persian
        "و", "در", "به", "از", "با", "برای", "که", "را", "این", "آن", "یک",
        "ها", "های", "می", "تا", "بدون", "خرید", "ارزان", "بهترین", "مدل",
    }
)  # fmt: skip


def normalize_text(text: str) -> str:
    """Return a canonical, case-folded form of ``text`` for comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text)
    return " ".join(text.casefold().split())


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Split normalized text into word tokens, optionally removing stopwords."""
    tokens = _TOKEN.findall(normalize_text(text))
    if drop_stopwords:
        tokens = [t for t in tokens if t not in _STOPWORDS]
    return tokens


def detect_language(text: str) -> str:
    """Best-effort detection of ``"fa"`` versus ``"en"`` based on script."""
    arabic = len(_ARABIC_SCRIPT.findall(text))
    latin = len(_LATIN.findall(text))
    if arabic == 0 and latin == 0:
        return "und"
    return "fa" if arabic >= latin else "en"


def is_rtl(text: str) -> bool:
    return detect_language(text) == "fa"
