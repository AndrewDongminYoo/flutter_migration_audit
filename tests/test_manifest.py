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
