"""Locale qualifiers: case (#28) and equivalent languages (#27)."""

import pytest

from fma.signals import (
    AppInputs,
    best_match,
    device_config,
    qualifier_parts,
    read_styles,
    resolve_opt_out,
)

# --- #28: Android ignores the case of qualifier values -----------------------


@pytest.mark.parametrize(
    "qualifier, locale",
    [
        ("values-EN-rus", "en-rUS"),
        ("values-En-Rus", "en-rUS"),
        ("values-B+EN+us", "en-rUS"),
        ("values-b+ZH+hant+tw", "zh-Hant-rTW"),
        ("values-en-rUS", "en-rUS"),
    ],
)
def test_locale_case_is_ignored(qualifier, locale):
    assert qualifier_parts(qualifier) == {"locale": locale}


def test_region_and_three_letter_language_are_told_apart_by_position():
    # rus right after a language is the region US ...
    assert qualifier_parts("values-en-rus")["locale"] == "en-rUS"
    # ... but on its own it is the language Russian.
    assert qualifier_parts("values-rus")["locale"] == "rus"
    assert qualifier_parts("values-rus-night") == {"locale": "rus", "night": "night"}


def test_other_qualifiers_ignore_case_too():
    assert qualifier_parts("values-NIGHT-V35") == {"night": "night", "version": 35}


def test_mixed_case_directory_is_chosen_for_its_device():
    assert (
        best_match({"values", "values-EN-rus"}, device_config("values-en-rUS"))
        == "values-EN-rus"
    )


# --- #27: Filipino (fil) and Tagalog (tl) are the same language -------------

OPT = '<item name="android:windowOptOutEdgeToEdgeEnforcement">{}</item>'


def styles(*dirs):
    inputs = AppInputs()
    for qualifier, xml in dirs:
        read_styles(
            f"<resources>{xml}</resources>",
            f"{qualifier}/styles.xml",
            qualifier,
            inputs,
        )
    return inputs.styles


def test_fil_device_uses_tl_resources():
    """The case in #27: Android takes values-tl/Base on a fil device."""
    got = styles(
        (
            "values",
            f'<style name="Base">{OPT.format("true")}</style><style name="NormalTheme" parent="Base"/>',
        ),
        ("values-b+fil", '<style name="NormalTheme" parent="Base"/>'),
        ("values-tl", f'<style name="Base">{OPT.format("false")}</style>'),
    )
    result = resolve_opt_out(got, "NormalTheme", "values-b+fil")
    assert result.value is False
    assert [s.qualifier for s in result.styles] == ["values-b+fil", "values-tl"]


def test_the_exact_language_wins_among_equivalent_ones():
    dirs = {"values", "values-fil", "values-tl"}
    assert best_match(dirs, device_config("values-fil")) == "values-fil"
    assert best_match(dirs, device_config("values-tl")) == "values-tl"
    assert (
        best_match({"values", "values-tl"}, device_config("values-fil")) == "values-tl"
    )
    assert (
        best_match({"values", "values-fil"}, device_config("values-tl")) == "values-fil"
    )


def test_regions_of_equivalent_languages_are_grouped():
    from fma.signals import unchecked_qualifiers

    out = unchecked_qualifiers({"values", "values-fil-rPH", "values-tl-rUS"})
    assert set(out) == {"values-fil-rPH", "values-tl-rUS"}


def test_region_specificity_comes_before_the_exact_language_code():
    """Local review: AOSP compares regions first and prefers the device's own
    language code only as the last tie-breaker."""
    assert (
        best_match({"values-fil", "values-tl-rPH"}, device_config("values-fil-rPH"))
        == "values-tl-rPH"
    )
    assert (
        best_match({"values-tl", "values-fil-rPH"}, device_config("values-tl-rPH"))
        == "values-fil-rPH"
    )
    assert (
        best_match({"values-fil-rPH", "values-tl-rPH"}, device_config("values-tl-rPH"))
        == "values-tl-rPH"
    )
