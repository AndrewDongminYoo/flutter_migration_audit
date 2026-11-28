"""Korean particles chosen from the final sound of the word before them."""

import re
from pathlib import Path

import pytest

from fma.korean import final_sound, josa, particle

SRC = Path(__file__).resolve().parents[1] / "src" / "fma"


@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0을"),  # 영
        (2, "2를"),  # 이
        (10, "10을"),  # 십
        (15, "15를"),  # 십오
        (16, "16을"),  # 십육
        (20, "20을"),  # 이십
        (33, "33을"),  # 삼십삼
        (35, "35를"),  # 삼십오
        (36, "36을"),  # 삼십육
        (100, "100을"),  # 백
        (1000, "1000을"),  # 천
        (10000, "10000을"),  # 만
    ],
)
def test_object_particle_after_numbers(n, expected):
    assert josa(n, "을/를") == expected


def test_ro_after_final_l_and_vowels():
    # 으로 after a final consonant, 로 after a vowel or ㄹ.
    assert [particle(n, "으로/로") for n in (15, 16, 17, 21, 33, 35, 36)] == [
        "로",
        "으로",
        "로",
        "로",
        "으로",
        "로",
        "으로",
    ]
    assert josa("파일", "으로/로") == "파일로"
    assert josa("스타일", "으로/로") == "스타일로"
    assert josa("디렉터리", "으로/로") == "디렉터리로"
    assert josa("버튼", "으로/로") == "버튼으로"


def test_hangul_words():
    assert josa("스타일", "이/가") == "스타일이"
    assert josa("테마", "이/가") == "테마가"
    assert josa("한정자", "은/는") == "한정자는"
    assert josa("항목", "과/와") == "항목과"


def test_any_form_names_the_pair():
    assert particle(35, "를") == particle(35, "을") == particle(35, "을/를") == "를"
    assert particle(36, "였") == "이었"


def test_parenthetical_follows_the_word_before_it():
    assert josa("API 36(Android 16)", "으로/로") == "API 36(Android 16)으로"
    assert josa("API 35(Android 15)", "으로/로") == "API 35(Android 15)로"
    assert josa("targetSdk 35", "과/와") == "targetSdk 35와"


def test_unknown_final_sound_gives_both_forms():
    assert josa("`NormalTheme`", "이/가") == "`NormalTheme`이(가)"
    assert josa("values-night", "을/를") == "values-night을(를)"
    assert josa("`values-35`", "은/는") == "`values-35`는"  # digits decide
    assert final_sound("") is not None


# A particle whose form depends on the final sound, written directly after an
# interpolated value ({x}, `{x}`, or {f(x)}) in report text.
VARIABLE = re.compile(r"\}[`)]*(?:은|는|이었|였|이|가|을|를|과|와|으로|로)")


def test_report_text_uses_josa_after_interpolated_values():
    offenders = [
        f"{path.name}:{i}: {line.strip()}"
        for path in sorted(SRC.glob("*.py"))
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if VARIABLE.search(line)
    ]
    assert not offenders, "use fma.korean.josa():\n" + "\n".join(offenders)
