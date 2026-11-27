"""Opt-out inherited through style parents (issue #4).

The 3.27 migration guide says a parent style that child styles inherit from
can carry the opt-out item alone. Android resolves a style's parent from its
`parent` attribute, or, without one, from the prefix of a dotted name.
"""

import pytest

from fma.rules import AFFECTED, NEEDS_CHECK, NOT_AFFECTED, audit
from fma.signals import (
    AppInputs,
    read_gradle,
    read_manifest,
    read_styles,
    resolve_opt_out,
)

FRAMEWORK = "@android:style/Theme.Light.NoTitleBar"
ITEM = '<item name="android:windowOptOutEdgeToEdgeEnforcement">{}</item>'
MANIFEST = (
    '<meta-data android:name="io.flutter.embedding.android.NormalTheme" '
    'android:resource="@style/{}" />'
)


def styles(*defs, qualifier="values"):
    """defs: (name, parent or None, opt-out value or None)"""
    body = "<resources>\n"
    for name, parent, value in defs:
        attr = f' parent="{parent}"' if parent else ""
        item = ITEM.format(value) if value is not None else ""
        body += f'<style name="{name}"{attr}>\n{item}\n</style>\n'
    inputs = AppInputs()
    read_styles(body + "</resources>\n", f"{qualifier}/styles.xml", qualifier, inputs)
    return inputs.styles


def resolve(defs, name="NormalTheme"):
    return resolve_opt_out(styles(*defs), name, "values")


def test_parent_attribute():
    r = resolve([("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None)])
    assert (r.value, r.source, r.chain) == (True, "Base", ["NormalTheme", "Base"])
    assert r.clue.line == 3


def test_parent_attribute_without_style_prefix():
    r = resolve([("Base", FRAMEWORK, "true"), ("NormalTheme", "Base", None)])
    assert (r.value, r.source) == (True, "Base")


def test_dotted_name():
    r = resolve(
        [("NormalTheme", FRAMEWORK, "true"), ("NormalTheme.Video", None, None)],
        "NormalTheme.Video",
    )
    assert (r.value, r.source) == (True, "NormalTheme")


def test_explicit_parent_beats_dotted_prefix():
    r = resolve(
        [
            ("NormalTheme", FRAMEWORK, "true"),
            ("Plain", FRAMEWORK, None),
            ("NormalTheme.Video", "@style/Plain", None),
        ],
        "NormalTheme.Video",
    )
    assert r.value is None and r.chain == ["NormalTheme.Video", "Plain"]


def test_child_false_overrides_parent_true():
    r = resolve([("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "false")])
    assert (r.value, r.source) == (False, "NormalTheme")


def test_framework_parent_stops_the_chain():
    r = resolve([("NormalTheme", FRAMEWORK, None)])
    assert r.value is None and r.missing_parent is None


def test_missing_local_parent_is_reported():
    r = resolve([("NormalTheme", "@style/AppBase", None)])
    assert r.value is None and r.missing_parent == "AppBase"


def test_cycle_terminates():
    r = resolve([("A", "@style/NormalTheme", None), ("NormalTheme", "@style/A", None)])
    assert r.value is None and r.chain == ["NormalTheme", "A"]


def test_night_parent_falls_back_to_values():
    all_styles = styles(("Base", FRAMEWORK, "true")) + styles(
        ("NormalTheme", "@style/Base", None), qualifier="values-night"
    )
    r = resolve_opt_out(all_styles, "NormalTheme", "values-night")
    assert (r.value, r.source) == (True, "Base")


def test_requested_style_missing_returns_none():
    assert resolve([("Other", FRAMEWORK, "true")]) is None


# --- through the audit -------------------------------------------------------


def run(index, xml, night=None, theme="NormalTheme"):
    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    read_manifest(MANIFEST.format(theme), "AndroidManifest.xml", inputs)
    read_styles(xml, "values/styles.xml", "values", inputs)
    if night:
        read_styles(night, "values-night/styles.xml", "values-night", inputs)
    return audit("3.24.0", "3.27.0", inputs, index)


def xml(*defs):
    out = "<resources>\n"
    for name, parent, value in defs:
        attr = f' parent="{parent}"' if parent else ""
        out += (
            f'<style name="{name}"{attr}>\n'
            + (ITEM.format(value) + "\n" if value else "")
            + "</style>\n"
        )
    return out + "</resources>\n"


def finding(report, key):
    return next(f for f in report.findings if f.key == key)


def test_inherited_opt_out_is_not_affected_and_cites_parent_rule(index):
    report = run(
        index, xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    )
    f = finding(report, "opt_out")
    assert f.verdict == NOT_AFFECTED
    assert "부모 스타일 `Base`" in f.reason
    # manifest line, the NormalTheme declaration, then the item inside Base
    assert [c.line for c in f.clues] == [1, 5, 3]
    assert (
        "NormalTheme" in f.clues[1].text
        and "windowOptOutEdgeToEdgeEnforcement" in f.clues[2].text
    )
    assert "opt_out_parent" in [e.spec_key for e in f.evidence]
    assert all(e.snapshot_id == "flutter-3.27" for e in f.evidence)


def test_dotted_theme_inherits_opt_out(index):
    report = run(
        index,
        xml(("NormalTheme", FRAMEWORK, "true"), ("NormalTheme.Video", None, None)),
        theme="NormalTheme.Video",
    )
    assert finding(report, "opt_out").verdict == NOT_AFFECTED


def test_missing_parent_needs_check(index):
    f = finding(run(index, xml(("NormalTheme", "@style/AppBase", None))), "opt_out")
    assert f.verdict == NEEDS_CHECK and "`AppBase`" in f.check


def test_explicit_false_is_affected(index):
    f = finding(
        run(
            index,
            xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "false")),
        ),
        "opt_out",
    )
    assert f.verdict == AFFECTED and "`false`" in f.reason


@pytest.mark.parametrize("night_inherits", [True, False])
def test_night_style_inheriting_from_values_parent(index, night_inherits):
    day = xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    night = xml(("NormalTheme", "@style/Base" if night_inherits else FRAMEWORK, None))
    keys = [f.key for f in run(index, day, night).findings]
    assert ("opt_out_night" in keys) is not night_inherits


# --- review follow-ups (PR #19) ----------------------------------------------


def test_resource_reference_stops_inheritance():
    r = resolve(
        [
            ("Base", FRAMEWORK, "true"),
            ("NormalTheme", "@style/Base", "@bool/edge_opt_out"),
        ]
    )
    assert (
        r.value is None
        and r.source == "NormalTheme"
        and r.unresolved_value == "@bool/edge_opt_out"
    )


def test_resource_reference_needs_check(index):
    f = finding(
        run(
            index,
            xml(
                ("Base", FRAMEWORK, "true"),
                ("NormalTheme", "@style/Base", "@bool/edge_opt_out"),
            ),
        ),
        "opt_out",
    )
    assert f.verdict == NEEDS_CHECK and "`@bool/edge_opt_out`" in f.check


@pytest.mark.parametrize(
    "night_base_value, expect",
    [("false", "`false`"), (None, "opt-out 항목이 없습니다")],
)
def test_night_variant_of_parent_only(index, night_base_value, expect):
    """values/NormalTheme inherits true from values/Base, but only Base has a
    night variant. Android picks values-night/Base at night."""
    day = xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    night = xml(("Base", FRAMEWORK, night_base_value))
    report = run(index, day, night)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    f = finding(report, "opt_out_night")
    assert (
        f.verdict == NEEDS_CHECK
        and expect in f.reason
        and "values/NormalTheme → values-night/Base" in f.reason
    )


def test_night_variant_of_parent_that_keeps_opt_out(index):
    day = xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    night = xml(("Base", FRAMEWORK, "true"))
    assert "opt_out_night" not in [f.key for f in run(index, day, night).findings]


def test_best_match_follows_android_precedence():
    from fma.signals import best_match, device_config

    available = {
        "values",
        "values-night",
        "values-v35",
        "values-v36",
        "values-v31",
        "values-night-v35",
        "values-zh",
        "values-zh-rCN",
    }
    # Night ranks above platform version; v36 never applies to an API 35 device.
    assert (
        best_match(available, device_config("values-night-v35")) == "values-night-v35"
    )
    assert (
        best_match(available - {"values-night-v35"}, device_config("values-night"))
        == "values-night"
    )
    assert best_match(available, device_config("values")) == "values-v35"
    assert best_match({"values", "values-v31"}, device_config("values")) == "values-v31"
    # Locale ranks above night mode; an exact region match beats language only.
    assert (
        best_match(
            {"values", "values-zh", "values-night"}, device_config("values-zh-night")
        )
        == "values-zh"
    )
    assert best_match(available, device_config("values-zh-rCN")) == "values-zh-rCN"
    assert best_match({"values-zh"}, device_config("values-zh-rTW")) == "values-zh"
    assert best_match({"values-ko"}, device_config("values")) is None


def test_night_v35_theme_uses_night_parent_before_default(index):
    """Codex review on PR #19: values-night-v35/NormalTheme inherits from Base;
    with no values-night-v35/Base, Android picks values-night/Base, not
    values/Base."""
    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    read_manifest(MANIFEST.format("NormalTheme"), "AndroidManifest.xml", inputs)
    read_styles(
        xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "true")),
        "values/styles.xml",
        "values",
        inputs,
    )
    read_styles(
        xml(("Base", FRAMEWORK, "false")),
        "values-night/styles.xml",
        "values-night",
        inputs,
    )
    read_styles(
        xml(("NormalTheme", "@style/Base", None)),
        "values-night-v35/styles.xml",
        "values-night-v35",
        inputs,
    )

    r = resolve_opt_out(inputs.styles, "NormalTheme", "values-night-v35")
    assert (r.value, r.source) == (False, "Base")
    assert [s.qualifier for s in r.styles] == ["values-night-v35", "values-night"]

    report = audit("3.24.0", "3.27.0", inputs, index)
    night = [f for f in report.findings if f.key == "opt_out_night"]
    assert night and all(f.verdict == NEEDS_CHECK for f in night)
    assert any("values-night-v35" in f.reason and "`false`" in f.reason for f in night)


# --- local adversarial review follow-ups ---------------------------------------


def _inputs(*files):
    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    read_manifest(MANIFEST.format("NormalTheme"), "AndroidManifest.xml", inputs)
    for qualifier, text in files:
        read_styles(text, f"{qualifier}/styles.xml", qualifier, inputs)
    return inputs


def test_values_v35_day_variant_decides_the_main_verdict(index):
    inputs = _inputs(
        (
            "values",
            xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None)),
        ),
        ("values-v35", xml(("Base", FRAMEWORK, "false"))),
    )
    f = finding(audit("3.24.0", "3.27.0", inputs, index), "opt_out")
    assert f.verdict == AFFECTED and "`false`" in f.reason


def test_locale_variant_outranks_night(index):
    inputs = _inputs(
        (
            "values",
            xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None)),
        ),
        ("values-zh", xml(("Base", FRAMEWORK, "false"))),
        ("values-night", xml(("Base", FRAMEWORK, "true"))),
        ("values-zh-night", xml(("NormalTheme", "@style/Base", None))),
    )
    assert (
        resolve_opt_out(inputs.styles, "NormalTheme", "values-zh-night").value is False
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    # Two different style chains lose the opt-out, so both are reported:
    # values/NormalTheme → values-zh/Base, and values-zh-night/NormalTheme → values-zh/Base.
    variants = {
        f.title: f
        for f in report.findings
        if f.key in ("opt_out_variant", "opt_out_night")
    }
    assert set(variants) == {"`values-zh` 설정의 opt-out", "다크 모드 스타일의 opt-out"}
    assert (
        "values/NormalTheme → values-zh/Base"
        in variants["`values-zh` 설정의 opt-out"].reason
    )
    night = variants["다크 모드 스타일의 opt-out"].reason
    assert (
        "`values-zh-night`" in night
        and "values-zh-night/NormalTheme → values-zh/Base" in night
    )


def test_commented_out_style_is_ignored():
    inputs = AppInputs()
    read_styles(
        "<resources>\n"
        '<!-- <style name="NormalTheme"><item name="android:windowOptOutEdgeToEdgeEnforcement">true</item></style> -->\n'
        f'<style name="NormalTheme" parent="{FRAMEWORK}"></style>\n'
        "</resources>\n",
        "values/styles.xml",
        "values",
        inputs,
    )
    assert [(s.name, s.opt_out_value, s.clue.line) for s in inputs.styles] == [
        ("NormalTheme", None, 3)
    ]


def test_self_closing_style_is_read():
    inputs = AppInputs()
    read_styles(
        f'<resources>\n<style name="NormalTheme" parent="{FRAMEWORK}"/>\n</resources>\n',
        "values/styles.xml",
        "values",
        inputs,
    )
    assert [(s.name, s.parent, s.clue.line) for s in inputs.styles] == [
        ("NormalTheme", FRAMEWORK, 2)
    ]


def test_snippet_without_root_and_single_quotes():
    inputs = AppInputs()
    read_styles(
        "<style name='Base'>\n  <item name='android:windowOptOutEdgeToEdgeEnforcement'> true </item>\n</style>\n"
        "<style parent='@style/Base' name='NormalTheme'/>\n",
        "values/styles.xml",
        "values",
        inputs,
    )
    by_name = {s.name: s for s in inputs.styles}
    assert by_name["Base"].opt_out_value is True and by_name["Base"].opt_out.line == 2
    assert by_name["NormalTheme"].parent == "@style/Base"


def test_malformed_snippet_falls_back_to_scanner():
    inputs = AppInputs()
    # Unclosed <resources> and a stray '&' make expat fail.
    read_styles(
        '<resources>\n<!-- old & unused -->\n<style name="NormalTheme" parent="@style/Base">\n'
        '  <item name="android:windowOptOutEdgeToEdgeEnforcement">true</item>\n</style>\n& \n',
        "values/styles.xml",
        "values",
        inputs,
    )
    assert [(s.name, s.opt_out_value, s.opt_out.line) for s in inputs.styles] == [
        ("NormalTheme", True, 4)
    ]


def test_language_outranks_orientation_and_night(index):
    """Codex review on PR #19 (comment 4718584612), exact case."""
    inputs = _inputs(
        ("values", xml(("NormalTheme", FRAMEWORK, "true"))),
        ("values-en", xml(("Base", FRAMEWORK, "false"))),
        ("values-land-night", xml(("Base", FRAMEWORK, "true"))),
        ("values-en-land-night-v35", xml(("NormalTheme", "@style/Base", None))),
    )
    r = resolve_opt_out(inputs.styles, "NormalTheme", "values-en-land-night-v35")
    assert (r.value, [s.qualifier for s in r.styles]) == (
        False,
        ["values-en-land-night-v35", "values-en"],
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    assert any(
        f.key == "opt_out_night" and "values-en-land-night-v35" in f.reason
        for f in report.findings
    )


# --- Codex review round 3 on PR #19 ------------------------------------------


def test_theme_only_in_version_qualified_directory_does_not_crash(index):
    """comment 4718657075: NormalTheme only in values-v21."""
    inputs = _inputs(("values-v21", xml(("NormalTheme", FRAMEWORK, None))))
    f = finding(audit("3.24.0", "3.27.0", inputs, index), "opt_out")
    assert f.verdict == AFFECTED and "values-v21/styles.xml" in f.clues[1].file


def test_smallest_width_is_a_threshold(index):
    """comment 4718657083: values-sw720dp/NormalTheme → values-sw600dp/Base."""
    inputs = _inputs(
        (
            "values",
            xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "true")),
        ),
        ("values-sw600dp", xml(("Base", FRAMEWORK, "false"))),
        ("values-sw720dp", xml(("NormalTheme", "@style/Base", None))),
    )
    r = resolve_opt_out(inputs.styles, "NormalTheme", "values-sw720dp")
    assert (r.value, [s.qualifier for s in r.styles]) == (
        False,
        ["values-sw720dp", "values-sw600dp"],
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    assert [f.title for f in report.findings if f.key == "opt_out_variant"] == [
        "`values-sw720dp` 설정의 opt-out"
    ]


def test_combinations_of_supplied_qualifiers_are_checked(index):
    """comment 4718657091: English night mode combines values-en and values-night."""
    inputs = _inputs(
        (
            "values",
            xml(("NormalTheme", FRAMEWORK, "true"), ("Base", FRAMEWORK, "true")),
        ),
        ("values-en", xml(("NormalTheme", "@style/Base", None))),
        ("values-night", xml(("Base", FRAMEWORK, "false"))),
    )
    for q in ("values", "values-en", "values-night"):
        assert resolve_opt_out(inputs.styles, "NormalTheme", q).value is True
    assert (
        resolve_opt_out(inputs.styles, "NormalTheme", "values-en-night").value is False
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    night = [f for f in report.findings if f.key == "opt_out_night"]
    assert len(night) == 1 and "`values-en-night`" in night[0].reason


def test_too_many_combinations_reports_uncertainty(index, monkeypatch):
    from fma import rules

    monkeypatch.setattr(rules.Auditor, "MAX_CONFIGS", 3)
    inputs = _inputs(
        ("values", xml(("NormalTheme", FRAMEWORK, "true"))),
        ("values-en", xml(("Other", FRAMEWORK, None))),
        ("values-night", xml(("Other", FRAMEWORK, None))),
    )
    f = finding(audit("3.24.0", "3.27.0", inputs, index), "opt_out_variant")
    assert f.verdict == NEEDS_CHECK and "4개" in f.reason


# --- local adversarial review, round 2 -----------------------------------------


def test_notnight_variant_is_the_day_result(index):
    inputs = _inputs(
        ("values", xml(("NormalTheme", FRAMEWORK, "true"))),
        ("values-notnight", xml(("NormalTheme", FRAMEWORK, "false"))),
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    f = finding(report, "opt_out")
    assert f.verdict == AFFECTED and "values-notnight/styles.xml" in f.clues[1].file
    assert not [x for x in report.findings if x.key == "opt_out_night"]


def test_impossible_width_combinations_are_skipped(index):
    inputs = _inputs(
        (
            "values",
            xml(("NormalTheme", FRAMEWORK, "true"), ("Base", FRAMEWORK, "true")),
        ),
        ("values-w600dp", xml(("NormalTheme", "@style/Base", None))),
        ("values-sw720dp", xml(("Base", FRAMEWORK, "false"))),
    )
    titles = [
        f.title
        for f in audit("3.24.0", "3.27.0", inputs, index).findings
        if f.key == "opt_out_variant"
    ]
    # A device with sw720dp has a current width of at least 720dp, so values-w600dp
    # applies too: the real failing configuration is sw720dp with w720dp.
    assert titles == ["`values-sw720dp-w720dp` 설정의 opt-out"]


def test_larger_threshold_with_the_same_chain_is_not_repeated(index):
    inputs = _inputs(
        (
            "values",
            xml(("NormalTheme", FRAMEWORK, "true"), ("Base", FRAMEWORK, "false")),
        ),
        ("values-sw600dp", xml(("NormalTheme", "@style/Base", None))),
        ("values-sw720dp", xml(("Other", FRAMEWORK, None))),
    )
    titles = [
        f.title
        for f in audit("3.24.0", "3.27.0", inputs, index).findings
        if f.key == "opt_out_variant"
    ]
    assert titles == ["`values-sw600dp` 설정의 opt-out"]


def test_different_chain_with_the_same_outcome_is_reported(index):
    inputs = _inputs(
        ("values", xml(("NormalTheme", FRAMEWORK, "true"))),
        ("values-en", xml(("NormalTheme", FRAMEWORK, None))),
        ("values-en-night", xml(("NormalTheme", FRAMEWORK, None))),
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    files = sorted(
        f.clues[0].file
        for f in report.findings
        if f.key in ("opt_out_variant", "opt_out_night")
    )
    assert files == ["values-en-night/styles.xml", "values-en/styles.xml"]


# --- Codex review round 4: report uncertainty for unmodeled qualifiers -------


@pytest.mark.parametrize(
    "theme_dir, base_dir, kind",
    [
        ("values-xlarge", "values-large", "size"),  # comment 4719280792
        ("values-xhdpi", "values-hdpi", "density"),  # comment 4719280799
        ("values-b+en+US", "values-en", "BCP-47 locale"),  # comment 4719357723
    ],
)
def test_unmodeled_qualifiers_are_reported_not_asserted(
    index, theme_dir, base_dir, kind
):
    inputs = _inputs(
        (
            "values",
            xml(("NormalTheme", FRAMEWORK, "true"), ("Base", FRAMEWORK, "true")),
        ),
        (theme_dir, xml(("NormalTheme", "@style/Base", None))),
        (base_dir, xml(("Base", FRAMEWORK, "false"))),
    )
    report = audit("3.24.0", "3.27.0", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED  # the default day result
    f = next(
        f for f in report.findings if f.title == "정확히 판단하지 않는 리소스 한정자"
    )
    assert (
        f.verdict == NEEDS_CHECK and kind in f.reason and f"`{theme_dir}`" in f.reason
    )
    # The opt-out is not asserted for every configuration, so later checks run.
    assert "ui_mode" in [x.key for x in report.findings]


def test_clean_inputs_still_stop_after_opt_out(index):
    inputs = _inputs(
        ("values", xml(("NormalTheme", FRAMEWORK, "true"))),
        ("values-night", xml(("NormalTheme", FRAMEWORK, "true"))),
    )
    keys = [f.key for f in audit("3.24.0", "3.27.0", inputs, index).findings]
    assert keys == ["target_sdk", "opt_out"]
