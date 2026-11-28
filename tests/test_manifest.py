"""Reading the app theme from AndroidManifest.xml (#33)."""

import pytest

from fma.rules import NEEDS_CHECK, NOT_AFFECTED, audit
from fma.signals import AppInputs, read_gradle, read_manifest, read_styles

META = "io.flutter.embedding.android.NormalTheme"


def read(text: str) -> AppInputs:
    inputs = AppInputs()
    read_manifest(text, "AndroidManifest.xml", inputs)
    return inputs


@pytest.mark.parametrize(
    "meta",
    [
        f'<meta-data android:name="{META}" android:resource="@style/AppTheme"/>',
        f'<meta-data android:resource="@style/AppTheme" android:name="{META}"/>',
        f"<meta-data android:name='{META}' android:resource='@style/AppTheme'/>",
        f'<meta-data\n  android:resource = "@style/AppTheme"\n  android:name="{META}" />',
    ],
)
def test_normal_theme_in_any_attribute_order_and_quotes(meta):
    inputs = read(f'<activity android:name=".MainActivity">\n{meta}\n</activity>')
    assert inputs.normal_theme and inputs.normal_theme[0] == "AppTheme"


def test_meta_data_snippet_without_an_activity():
    """README: a part of the manifest is enough."""
    inputs = read(
        f'<meta-data android:name="{META}" android:resource="@style/AppTheme"/>'
    )
    assert inputs.normal_theme[0] == "AppTheme"


def test_commented_out_meta_data_is_ignored():
    inputs = read(
        '<activity android:name=".MainActivity">\n'
        f'<!-- <meta-data android:name="{META}" android:resource="@style/Old"/> -->\n'
        "</activity>"
    )
    assert inputs.normal_theme is None


def test_launch_theme_from_the_activity_and_line_numbers():
    inputs = read(
        '<application android:theme="@style/AppBase">\n'
        "  <activity\n"
        '    android:name=".MainActivity"\n'
        '    android:theme="@style/LaunchTheme">\n'
        f'    <meta-data android:name="{META}"\n'
        '      android:resource="@style/NormalTheme"/>\n'
        "  </activity>\n"
        "</application>"
    )
    assert inputs.launch_theme[0] == "LaunchTheme"
    assert inputs.launch_theme[1].line == 4
    assert inputs.normal_theme[1].line == 6


def test_launch_theme_falls_back_to_the_application_theme():
    inputs = read(
        '<application android:theme="@style/AppBase">\n'
        '  <activity android:name=".MainActivity"/>\n'
        "</application>"
    )
    assert inputs.launch_theme[0] == "AppBase"


def test_the_activity_with_the_meta_data_is_chosen():
    inputs = read(
        '<activity android:name=".Settings" android:theme="@style/Other"/>\n'
        '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n'
        f'  <meta-data android:name="{META}" android:resource="@style/NormalTheme"/>\n'
        "</activity>"
    )
    assert inputs.launch_theme[0] == "LaunchTheme"


def test_without_meta_data_the_launcher_activity_is_chosen():
    inputs = read(
        '<activity android:name=".Settings" android:theme="@style/Other"/>\n'
        '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n'
        "  <intent-filter>\n"
        '    <category android:name="android.intent.category.LAUNCHER"/>\n'
        "  </intent-filter>\n"
        "</activity>"
    )
    assert inputs.normal_theme is None
    assert inputs.launch_theme[0] == "LaunchTheme"


def test_framework_theme_is_not_an_app_style():
    inputs = read(
        '<activity android:name=".A" android:theme="@android:style/Theme.Black"/>'
    )
    assert inputs.launch_theme is None


# --- the theme the rules judge ----------------------------------------------


FRAMEWORK = "@android:style/Theme.Light.NoTitleBar"
OPT_OUT = '<item name="android:windowOptOutEdgeToEdgeEnforcement">true</item>'


def styles(**opted):
    return (
        "<resources>"
        + "".join(
            f'<style name="{n}" parent="{FRAMEWORK}">{OPT_OUT if on else ""}</style>'
            for n, on in opted.items()
        )
        + "</resources>"
    )


def app(manifest, styles_xml):
    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    read_manifest(manifest, "AndroidManifest.xml", inputs)
    read_styles(styles_xml, "values/styles.xml", "values", inputs)
    return inputs


def finding(report, key):
    return next((f for f in report.findings if f.key == key), None)


ACTIVITY = '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n{}\n</activity>'
REVERSED = f'<meta-data android:resource="@style/AppTheme" android:name="{META}"/>'


def test_reversed_attributes_judge_the_named_theme(index):
    """#33: the opt-out on AppTheme counts although NormalTheme has none."""
    inputs = app(
        ACTIVITY.format(REVERSED),
        styles(LaunchTheme=True, AppTheme=True, NormalTheme=False),
    )
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out")
    assert f.verdict == NOT_AFFECTED and "`AppTheme`" in f.reason


def test_without_meta_data_the_launch_theme_is_judged(index):
    inputs = app(ACTIVITY.format(""), styles(LaunchTheme=True, NormalTheme=False))
    report = audit("3.24.5", "3.27.1", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    assert any("`LaunchTheme`" in n for n in report.notes)


def test_manifest_without_a_theme_needs_check(index):
    inputs = app('<application android:label="a"/>', styles(NormalTheme=True))
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out")
    assert f.verdict == NEEDS_CHECK and "AndroidManifest.xml" in f.reason


def test_launch_theme_without_the_opt_out_is_reported(index):
    meta = f'<meta-data android:name="{META}" android:resource="@style/NormalTheme"/>'
    inputs = app(ACTIVITY.format(meta), styles(LaunchTheme=False, NormalTheme=True))
    report = audit("3.24.5", "3.27.1", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    f = finding(report, "launch_theme")
    assert f.verdict == NEEDS_CHECK and "`LaunchTheme`" in f.reason
    assert any("after the launch" in e.quote for e in f.evidence)


def test_matching_launch_theme_adds_nothing(index):
    meta = f'<meta-data android:name="{META}" android:resource="@style/NormalTheme"/>'
    inputs = app(ACTIVITY.format(meta), styles(LaunchTheme=True, NormalTheme=True))
    assert finding(audit("3.24.5", "3.27.1", inputs, index), "launch_theme") is None


def test_launch_theme_opt_out_on_android16_is_reported(index):
    meta = f'<meta-data android:name="{META}" android:resource="@style/NormalTheme"/>'
    inputs = app(ACTIVITY.format(meta), styles(LaunchTheme=True, NormalTheme=False))
    report = audit("3.32.5", "3.35.1", inputs, index)
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    assert finding(report, "launch_theme").verdict == NEEDS_CHECK


def test_cdata_is_not_read_as_tags():
    inputs = read(
        '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n'
        f'<![CDATA[ <meta-data android:name="{META}" android:resource="@style/Fake"/> ]]>\n'
        "</activity>"
    )
    assert inputs.normal_theme is None
    assert inputs.launch_theme[0] == "LaunchTheme"


def test_launcher_alias_points_to_its_activity():
    inputs = read(
        '<activity android:name=".Settings" android:theme="@style/Other"/>\n'
        '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme"/>\n'
        '<activity-alias android:name=".Launcher" android:targetActivity=".MainActivity">\n'
        "  <intent-filter>\n"
        '    <category android:name="android.intent.category.LAUNCHER"/>\n'
        "  </intent-filter>\n"
        "</activity-alias>"
    )
    assert inputs.launch_theme[0] == "LaunchTheme"


NIGHT_META = f'<meta-data android:name="{META}" android:resource="@style/NormalTheme"/>'


def test_launch_theme_mismatch_only_at_night(index):
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=True, NormalTheme=True)
    )
    read_styles(
        styles(LaunchTheme=True, NormalTheme=False),
        "values-night/styles.xml",
        "values-night",
        inputs,
    )
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "launch_theme")
    assert f is not None and f.verdict == NEEDS_CHECK and "`values-night`" in f.reason


def test_launch_theme_is_conditional_on_an_unknown_target(index):
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=False, NormalTheme=True)
    )
    inputs.target_sdk = None
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "launch_theme")
    assert f.reason.startswith("targetSdk가 35가 된다면: ")


def test_android16_launch_theme_without_opt_out_adds_nothing(index):
    """At targetSdk 36 Android 16 ignores both opt-outs: the normal theme's
    loss is the opt_out finding, and the launch screen does not change."""
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=False, NormalTheme=True)
    )
    assert finding(audit("3.32.5", "3.35.1", inputs, index), "launch_theme") is None


def test_android16_launch_theme_loses_its_opt_out(index):
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=True, NormalTheme=False)
    )
    f = finding(audit("3.32.5", "3.35.1", inputs, index), "launch_theme")
    assert f.verdict == NEEDS_CHECK
    assert "실행 화면" in f.reason and "맞추세요" not in (f.check or "")
    assert any("cannot opt-out" in e.quote for e in f.evidence)


def alias_manifest(target, *activities):
    return "\n".join(
        f'<activity android:name="{n}" android:theme="@style/{t}"/>'
        for n, t in activities
    ) + (
        f'\n<activity-alias android:name=".L" android:targetActivity="{target}">'
        '<intent-filter><category android:name="android.intent.category.LAUNCHER"/>'
        "</intent-filter></activity-alias>"
    )


def test_alias_matches_the_full_activity_name():
    inputs = read(
        alias_manifest(
            "com.target.MainActivity",
            ("com.first.MainActivity", "Wrong"),
            ("com.target.MainActivity", "Right"),
        )
    )
    assert inputs.launch_theme[0] == "Right"


def test_relative_alias_target_matches_a_qualified_activity():
    inputs = read(
        alias_manifest(
            ".MainActivity",
            ("com.a.Settings", "Wrong"),
            ("com.a.MainActivity", "Right"),
        )
    )
    assert inputs.launch_theme[0] == "Right"


def test_ambiguous_alias_target_chooses_nothing():
    inputs = read(
        alias_manifest(
            ".MainActivity", ("com.a.MainActivity", "A"), ("com.b.MainActivity", "B")
        )
    )
    assert inputs.launch_theme is None


def test_launch_theme_with_too_many_configurations_needs_check(index, monkeypatch):
    from fma.rules import Auditor

    monkeypatch.setattr(Auditor, "MAX_CONFIGS", 1)
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=True, NormalTheme=True)
    )
    for q in ("values-night", "values-en", "values-ko"):
        read_styles(
            styles(LaunchTheme=True, NormalTheme=q != "values-night"),
            f"{q}/styles.xml",
            q,
            inputs,
        )
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "launch_theme")
    assert f is not None and f.verdict == NEEDS_CHECK and "조합" in f.reason


def many_configs(inputs):
    for q in ("values-night", "values-en", "values-ko"):
        read_styles(
            styles(LaunchTheme=True, NormalTheme=True), f"{q}/styles.xml", q, inputs
        )
    return inputs


def test_unresolved_default_is_not_called_equal(index, monkeypatch):
    from fma.rules import Auditor

    monkeypatch.setattr(Auditor, "MAX_CONFIGS", 1)
    broken = (
        '<resources><style name="LaunchTheme" parent="MissingBase"/>'
        '<style name="NormalTheme" parent="MissingBase"/></resources>'
    )
    inputs = many_configs(app(ACTIVITY.format(NIGHT_META), broken))
    assert finding(audit("3.24.5", "3.27.1", inputs, index), "launch_theme") is None


def test_android16_skipped_configurations_name_the_android16_check(index, monkeypatch):
    from fma.rules import Auditor

    monkeypatch.setattr(Auditor, "MAX_CONFIGS", 1)
    inputs = many_configs(
        app(ACTIVITY.format(NIGHT_META), styles(LaunchTheme=True, NormalTheme=True))
    )
    f = finding(audit("3.32.5", "3.35.1", inputs, index), "launch_theme")
    assert f.verdict == NEEDS_CHECK and "실행 화면 스타일에만" in f.check
    assert any("cannot opt-out" in e.quote for e in f.evidence)


def test_a_later_manifest_without_themes_keeps_the_themes():
    """Codex review on #34: src/profile/AndroidManifest.xml after src/main."""
    inputs = AppInputs()
    read_manifest(
        f'<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n'
        f'<meta-data android:name="{META}" android:resource="@style/NormalTheme"/>\n</activity>',
        "main/AndroidManifest.xml",
        inputs,
    )
    read_manifest(
        '<manifest><uses-permission android:name="android.permission.INTERNET"/></manifest>',
        "profile/AndroidManifest.xml",
        inputs,
    )
    assert inputs.normal_theme[0] == "NormalTheme"
    assert inputs.launch_theme[0] == "LaunchTheme"


def test_explicit_framework_theme_is_not_replaced_by_the_application_theme():
    """Codex review on #34."""
    inputs = read(
        '<application android:theme="@style/AppBase">\n'
        '<activity android:name=".MainActivity" android:theme="@android:style/Theme.Light.NoTitleBar"/>\n'
        "</application>"
    )
    assert inputs.launch_theme is None
    assert inputs.framework_theme[0] == "@android:style/Theme.Light.NoTitleBar"


def test_framework_theme_needs_check(index):
    inputs = app(
        '<application android:theme="@style/AppBase">\n'
        '<activity android:name=".MainActivity" android:theme="@android:style/Theme.Light.NoTitleBar"/>\n'
        "</application>",
        styles(AppBase=True),
    )
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out")
    assert (
        f.verdict == NEEDS_CHECK and "@android:style/Theme.Light.NoTitleBar" in f.reason
    )


def test_unclosed_activity_snippet_keeps_its_meta_data():
    """Codex review on #34: a snippet may omit </activity>."""
    inputs = read(
        '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n'
        f'<meta-data android:name="{META}" android:resource="@style/AppTheme"/>'
    )
    assert inputs.normal_theme[0] == "AppTheme"


def test_main_manifest_theme_wins_over_a_build_type_manifest(tmp_path):
    """Local review: src/debug sorts before src/main, src/profile after it.
    The base source set (main) is judged either way."""
    from fma.signals import read_paths

    for variant in ("debug", "profile"):
        d = tmp_path / variant
        (d / "src/main").mkdir(parents=True)
        (d / f"src/{variant}").mkdir(parents=True)
        (d / "src/main/AndroidManifest.xml").write_text(
            f'<activity android:name=".MainActivity">\n<meta-data android:name="{META}" android:resource="@style/MainTheme"/>\n</activity>'
        )
        (d / f"src/{variant}/AndroidManifest.xml").write_text(
            f'<activity android:name=".MainActivity">\n<meta-data android:name="{META}" android:resource="@style/VariantTheme"/>\n</activity>'
        )
        inputs = read_paths(sorted(d.rglob("AndroidManifest.xml")), d)
        assert inputs.normal_theme[0] == "MainTheme", variant
        assert [t[0] for t in inputs.other_themes] == ["VariantTheme"], variant


def test_other_manifest_theme_is_noted(index):
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=True, NormalTheme=True)
    )
    read_manifest(
        f'<activity android:name=".MainActivity">\n<meta-data android:name="{META}" android:resource="@style/DebugTheme"/>\n</activity>',
        "debug/AndroidManifest.xml",
        inputs,
    )
    report = audit("3.24.5", "3.27.1", inputs, index)
    assert any(
        "`DebugTheme`" in n and "debug/AndroidManifest.xml" in n for n in report.notes
    )


def test_unclosed_activity_ends_at_the_next_activity():
    inputs = read(
        '<activity android:name=".Old" android:theme="@style/OldTheme">\n'
        '<activity android:name=".MainActivity" android:theme="@style/MainTheme">\n'
        '<intent-filter><category android:name="android.intent.category.LAUNCHER"/></intent-filter>\n'
        "</activity>"
    )
    assert inputs.launch_theme[0] == "MainTheme"


def test_framework_normal_theme_is_not_replaced_by_the_launch_theme(index):
    """Codex review on #34."""
    meta = f'<meta-data android:name="{META}" android:resource="@android:style/Theme.Light.NoTitleBar"/>'
    inputs = app(ACTIVITY.format(meta), styles(LaunchTheme=True))
    assert inputs.normal_theme is None
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out")
    assert (
        f.verdict == NEEDS_CHECK and "@android:style/Theme.Light.NoTitleBar" in f.reason
    )


def test_a_later_manifest_does_not_fill_the_base_manifest_gaps():
    """Codex review on #34: main has no meta-data, debug adds one."""
    inputs = AppInputs()
    read_manifest(
        '<activity android:name=".MainActivity" android:theme="@style/MainTheme"/>',
        "main/AndroidManifest.xml",
        inputs,
    )
    read_manifest(
        f'<activity android:name=".MainActivity">\n<meta-data android:name="{META}" android:resource="@style/DebugTheme"/>\n</activity>',
        "debug/AndroidManifest.xml",
        inputs,
    )
    assert inputs.normal_theme is None
    assert inputs.launch_theme[0] == "MainTheme"
    assert [t[0] for t in inputs.other_themes] == ["DebugTheme"]


TWO_FLUTTER_ACTIVITIES = (
    '<activity android:name=".Other" android:theme="@style/OtherLaunch">\n'
    f'<meta-data android:name="{META}" android:resource="@style/OtherTheme"/>\n</activity>\n'
    '<activity android:name=".MainActivity" android:theme="@style/LaunchTheme">\n'
    f'<meta-data android:name="{META}" android:resource="@style/NormalTheme"/>\n'
    "{}</activity>"
)
LAUNCHER = '<intent-filter><category android:name="android.intent.category.LAUNCHER"/></intent-filter>\n'


def test_launcher_wins_among_activities_with_meta_data():
    inputs = read(TWO_FLUTTER_ACTIVITIES.format(LAUNCHER))
    assert inputs.normal_theme[0] == "NormalTheme"
    assert inputs.launch_theme[0] == "LaunchTheme"


def test_several_activities_with_meta_data_and_no_launcher_choose_nothing(index):
    inputs = app(
        TWO_FLUTTER_ACTIVITIES.format(""), styles(OtherTheme=True, NormalTheme=False)
    )
    assert inputs.normal_theme is None
    assert sorted(t[0] for t in inputs.ambiguous_themes) == [
        "NormalTheme",
        "OtherTheme",
    ]
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out")
    assert (
        f.verdict == NEEDS_CHECK
        and "`OtherTheme`" in f.reason
        and "`NormalTheme`" in f.reason
    )


def test_application_level_meta_data_is_not_a_flutter_theme():
    inputs = read(
        '<application android:theme="@style/AppBase">\n'
        f'<meta-data android:name="{META}" android:resource="@style/AppTheme"/>\n'
        "</application>"
    )
    assert inputs.normal_theme is None
    assert inputs.launch_theme[0] == "AppBase"


def test_removed_meta_data_is_not_a_declaration_and_merge_directives_are_noted(index):
    inputs = app(
        ACTIVITY.format(NIGHT_META), styles(LaunchTheme=True, NormalTheme=True)
    )
    read_manifest(
        '<activity android:name=".MainActivity">\n'
        f'<meta-data android:name="{META}" tools:node="remove"/>\n</activity>',
        "debug/AndroidManifest.xml",
        inputs,
    )
    assert inputs.normal_theme[0] == "NormalTheme"
    report = audit("3.24.5", "3.27.1", inputs, index)
    assert any(
        "tools:node" in n and "debug/AndroidManifest.xml" in n for n in report.notes
    )


def test_explicit_manifests_outside_src_main_keep_the_given_order(tmp_path):
    from fma.signals import read_paths

    for d, theme in (("z-base", "BaseTheme"), ("a-debug", "DebugTheme")):
        (tmp_path / d).mkdir()
        (tmp_path / d / "AndroidManifest.xml").write_text(
            f'<activity android:name=".MainActivity">\n<meta-data android:name="{META}" android:resource="@style/{theme}"/>\n</activity>'
        )
    inputs = read_paths(
        [
            tmp_path / "z-base/AndroidManifest.xml",
            tmp_path / "a-debug/AndroidManifest.xml",
        ]
    )
    assert inputs.normal_theme[0] == "BaseTheme"


def test_a_checkout_named_main_is_not_the_main_source_set(tmp_path):
    """Codex review on #34."""
    from fma.signals import discover

    root = tmp_path / "main" / "app"
    for variant, theme in (("main", "MainTheme"), ("debug", "DebugTheme")):
        d = root / "android/app/src" / variant
        d.mkdir(parents=True)
        (d / "AndroidManifest.xml").write_text(
            f'<activity android:name=".MainActivity">\n<meta-data android:name="{META}" android:resource="@style/{theme}"/>\n</activity>'
        )
    assert discover(root).normal_theme[0] == "MainTheme"


def test_meta_data_right_after_the_activity_end_is_outside_it():
    """Codex review on #34."""
    inputs = read(
        "<application>"
        f'<activity android:name=".MainActivity"><meta-data android:name="{META}" android:resource="@style/Actual"/></activity>'
        f'<meta-data android:name="{META}" android:resource="@style/Ignored"/>'
        "</application>"
    )
    assert inputs.normal_theme[0] == "Actual"
