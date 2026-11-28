"""Korean particles (조사) that change with the final sound of the word
before them.

Report text interpolates numbers (API levels, targetSdk values) and other
words, so the particle must be chosen at run time. Use `josa(word, "을/를")`
instead of writing the particle in the f-string. `tests/test_korean.py`
fails when a variable particle follows an interpolated value directly.
"""

from __future__ import annotations

import re

# Each pair: (form after a final consonant, form after a vowel).
PAIRS: dict[str, tuple[str, str]] = {
    "은/는": ("은", "는"),
    "이/가": ("이", "가"),
    "을/를": ("을", "를"),
    "과/와": ("과", "와"),
    "으로/로": ("으로", "로"),
    "이었/였": ("이었", "였"),
    "이라/라": ("이라", "라"),
}
# Every form maps to its pair, so josa(n, "를") and josa(n, "을/를") agree.
ALIASES = {form: key for key, forms in PAIRS.items() for form in (key, *forms)}

# Final consonant of each digit as read in Korean numerals (일, 이, 삼, ...).
# "L" marks ㄹ, which takes 로 rather than 으로.
DIGIT_FINAL = {
    "0": "N",  # 영 (only for the number 0 itself)
    "1": "L",  # 일
    "2": None,  # 이
    "3": "N",  # 삼
    "4": None,  # 사
    "5": None,  # 오
    "6": "N",  # 육
    "7": "L",  # 칠
    "8": "L",  # 팔
    "9": None,  # 구
}
# Final consonant of the unit read for trailing zeros: 십, 백, 천, 만.
UNIT_FINAL = {1: "N", 2: "N", 3: "N", 4: "N"}

HANGUL_FIRST, HANGUL_LAST = 0xAC00, 0xD7A3
FINAL_L = 8  # index of ㄹ among the final consonants
PARENTHETICAL = re.compile(r"\s*\([^()]*\)$")
TRAILING_MARKS = "`'\"”’ ."


class Unknown:
    """The final sound cannot be decided (for example a Latin identifier)."""


UNKNOWN = Unknown()


def number_final(digits: str) -> str | None:
    """Final sound of an integer read in Korean numerals: "N" for a final
    consonant other than ㄹ, "L" for ㄹ, None for a vowel."""
    stripped = digits.lstrip("0") or "0"
    if stripped == "0":
        return DIGIT_FINAL["0"]
    zeros = len(stripped) - len(stripped.rstrip("0"))
    if zeros:
        # 10 십, 100 백, 1000 천, 10000 만; larger units repeat 만/억/조,
        # all of which end in a consonant other than ㄹ.
        return UNIT_FINAL.get(zeros % 4 or 4, "N")
    return DIGIT_FINAL[stripped[-1]]


def final_sound(word: str | int) -> str | None | Unknown:
    """Final sound of `word` as read aloud: "N" (consonant other than ㄹ),
    "L" (ㄹ), None (vowel), or UNKNOWN."""
    text = str(word)
    # A parenthetical explains the word before it; the particle follows
    # that word (API 36(Android 16) → 으로, as for 36).
    while PARENTHETICAL.search(text) and not text.startswith("("):
        text = PARENTHETICAL.sub("", text)
    text = text.rstrip(TRAILING_MARKS)
    if not text:
        return UNKNOWN
    if m := re.search(r"(\d+)$", text):
        return number_final(m[1])
    last = ord(text[-1])
    if HANGUL_FIRST <= last <= HANGUL_LAST:
        final = (last - HANGUL_FIRST) % 28
        if final == 0:
            return None
        return "L" if final == FINAL_L else "N"
    return UNKNOWN


def particle(word: str | int, pair: str) -> str:
    """The particle of `pair` (such as "을/를") that follows `word`. When
    the final sound is unknown, return both forms, such as "을(를)"."""
    with_final, without_final = PAIRS[ALIASES[pair]]
    final = final_sound(word)
    if isinstance(final, Unknown):
        return f"{with_final}({without_final})"
    if final is None:
        return without_final
    if final == "L" and with_final == "으로":
        return without_final
    return with_final


def josa(word: str | int, pair: str) -> str:
    """`word` followed by the correct particle: josa(36, "을/를") is "36을"."""
    return f"{word}{particle(word, pair)}"
