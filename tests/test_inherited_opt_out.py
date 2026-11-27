"""Opt-out inherited through style parents (issue #4).

The 3.27 migration guide says a parent style that child styles inherit from
can carry the opt-out item alone. Android resolves a style's parent from its
`parent` attribute, or, without one, from the prefix of a dotted name.
"""

import pytest

from fma.rules import AFFECTED, NEEDS_CHECK, NOT_AFFECTED, audit
from fma.signals import AppInputs, read_gradle, read_manifest, read_styles, resolve_opt_out

FRAMEWORK = "@android:style/Theme.Light.NoTitleBar"
ITEM = '<item name="android:windowOptOutEdgeToEdgeEnforcement">{}</item>'
MANIFEST = ('<meta-data android:name="io.flutter.embedding.android.NormalTheme" '
            'android:resource="@style/{}" />')


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
    r = resolve([("NormalTheme", FRAMEWORK, "true"), ("NormalTheme.Video", None, None)], "NormalTheme.Video")
    assert (r.value, r.source) == (True, "NormalTheme")


def test_explicit_parent_beats_dotted_prefix():
    r = resolve([("NormalTheme", FRAMEWORK, "true"), ("Plain", FRAMEWORK, None),
                 ("NormalTheme.Video", "@style/Plain", None)], "NormalTheme.Video")
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
    all_styles = styles(("Base", FRAMEWORK, "true")) + styles(("NormalTheme", "@style/Base", None), qualifier="values-night")
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
        out += f'<style name="{name}"{attr}>\n' + (ITEM.format(value) + "\n" if value else "") + "</style>\n"
    return out + "</resources>\n"


def finding(report, key):
    return next(f for f in report.findings if f.key == key)


def test_inherited_opt_out_is_not_affected_and_cites_parent_rule(index):
    report = run(index, xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None)))
    f = finding(report, "opt_out")
    assert f.verdict == NOT_AFFECTED
    assert "부모 스타일 `Base`" in f.reason
    # manifest line, the NormalTheme declaration, then the item inside Base
    assert [c.line for c in f.clues] == [1, 5, 3]
    assert "NormalTheme" in f.clues[1].text and "windowOptOutEdgeToEdgeEnforcement" in f.clues[2].text
    assert "opt_out_parent" in [e.spec_key for e in f.evidence]
    assert all(e.snapshot_id == "flutter-3.27" for e in f.evidence)


def test_dotted_theme_inherits_opt_out(index):
    report = run(index, xml(("NormalTheme", FRAMEWORK, "true"), ("NormalTheme.Video", None, None)),
                 theme="NormalTheme.Video")
    assert finding(report, "opt_out").verdict == NOT_AFFECTED


def test_missing_parent_needs_check(index):
    f = finding(run(index, xml(("NormalTheme", "@style/AppBase", None))), "opt_out")
    assert f.verdict == NEEDS_CHECK and "`AppBase`" in f.check


def test_explicit_false_is_affected(index):
    f = finding(run(index, xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "false"))), "opt_out")
    assert f.verdict == AFFECTED and "`false`" in f.reason


@pytest.mark.parametrize("night_inherits", [True, False])
def test_night_style_inheriting_from_values_parent(index, night_inherits):
    day = xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    night = xml(("NormalTheme", "@style/Base" if night_inherits else FRAMEWORK, None))
    keys = [f.key for f in run(index, day, night).findings]
    assert ("opt_out_night" in keys) is not night_inherits


# --- review follow-ups (PR #19) ----------------------------------------------

def test_resource_reference_stops_inheritance():
    r = resolve([("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "@bool/edge_opt_out")])
    assert r.value is None and r.source == "NormalTheme" and r.unresolved_value == "@bool/edge_opt_out"


def test_resource_reference_needs_check(index):
    f = finding(run(index, xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "@bool/edge_opt_out"))),
                "opt_out")
    assert f.verdict == NEEDS_CHECK and "`@bool/edge_opt_out`" in f.check


@pytest.mark.parametrize("night_base_value, expect", [("false", "`false`"), (None, "opt-out 항목이 없습니다")])
def test_night_variant_of_parent_only(index, night_base_value, expect):
    """values/NormalTheme inherits true from values/Base, but only Base has a
    night variant. Android picks values-night/Base at night."""
    day = xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    night = xml(("Base", FRAMEWORK, night_base_value))
    report = run(index, day, night)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    f = finding(report, "opt_out_night")
    assert f.verdict == NEEDS_CHECK and expect in f.reason and "NormalTheme → Base" in f.reason


def test_night_variant_of_parent_that_keeps_opt_out(index):
    day = xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", None))
    night = xml(("Base", FRAMEWORK, "true"))
    assert "opt_out_night" not in [f.key for f in run(index, day, night).findings]


def test_compatible_qualifiers_follow_android_precedence():
    from fma.signals import compatible_qualifiers

    available = {"values-night-v35", "values-night", "values-v35", "values-v36", "values-v31"}
    assert compatible_qualifiers("values-night-v35", available) == [
        "values-night-v35", "values-night", "values-v35", "values-v31", "values"]
    assert compatible_qualifiers("values-night", available) == ["values-night", "values"]
    assert compatible_qualifiers("values", available) == ["values"]


def test_night_v35_theme_uses_night_parent_before_default(index):
    """Codex review on PR #19: values-night-v35/NormalTheme inherits from Base;
    with no values-night-v35/Base, Android picks values-night/Base, not
    values/Base."""
    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    read_manifest(MANIFEST.format("NormalTheme"), "AndroidManifest.xml", inputs)
    read_styles(xml(("Base", FRAMEWORK, "true"), ("NormalTheme", "@style/Base", "true")),
                "values/styles.xml", "values", inputs)
    read_styles(xml(("Base", FRAMEWORK, "false")), "values-night/styles.xml", "values-night", inputs)
    read_styles(xml(("NormalTheme", "@style/Base", None)), "values-night-v35/styles.xml", "values-night-v35", inputs)

    r = resolve_opt_out(inputs.styles, "NormalTheme", "values-night-v35")
    assert (r.value, r.source) == (False, "Base")
    assert [s.qualifier for s in r.styles] == ["values-night-v35", "values-night"]

    report = audit("3.24.0", "3.27.0", inputs, index)
    night = [f for f in report.findings if f.key == "opt_out_night"]
    assert night and all(f.verdict == NEEDS_CHECK for f in night)
    assert any("values-night-v35" in f.reason and "`false`" in f.reason for f in night)
