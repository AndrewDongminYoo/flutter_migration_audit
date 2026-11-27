from pathlib import Path

import pytest

from fma.signals import AppInputs, discover, read_dart, read_gradle, read_manifest, read_paths, read_styles
from fma.versions import UnsupportedVersion, check_range, release_for

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.mark.parametrize(
    "line, raw",
    [
        ("        targetSdk = flutter.targetSdkVersion", "flutter.targetSdkVersion"),
        ("        targetSdk = 34", "34"),
        ("        targetSdkVersion 34", "34"),
        ("        targetSdkVersion flutter.targetSdkVersion", "flutter.targetSdkVersion"),
        ('        targetSdk = rootProject.ext.targetSdk', "rootProject.ext.targetSdk"),
    ],
)
def test_gradle_target_sdk_forms(line, raw):
    inputs = AppInputs()
    read_gradle(f"android {{\n  defaultConfig {{\n{line}\n  }}\n}}\n", "build.gradle", inputs)
    assert inputs.target_sdk.raw == raw
    assert inputs.target_sdk.clue.line == 3


def test_gradle_ignores_commented_target():
    inputs = AppInputs()
    read_gradle("// targetSdk = 30\n        targetSdk = flutter.targetSdkVersion\n", "build.gradle", inputs)
    assert inputs.target_sdk.uses_flutter_default
    assert inputs.target_sdk.clue.line == 2


def test_styles_opt_out_and_qualifier():
    text = (
        '<resources>\n'
        '  <style name="LaunchTheme" parent="x">\n  </style>\n'
        '  <style name="NormalTheme" parent="x">\n'
        '    <item name="android:windowOptOutEdgeToEdgeEnforcement">true</item>\n'
        '  </style>\n</resources>\n'
    )
    inputs = AppInputs()
    read_styles(text, "values-night/styles.xml", "values-night", inputs)
    by_name = {s.name: s for s in inputs.styles}
    assert by_name["LaunchTheme"].opt_out is None
    assert by_name["NormalTheme"].opt_out.line == 5
    assert by_name["NormalTheme"].qualifier == "values-night"


def test_styles_opt_out_false_is_recorded_as_false():
    inputs = AppInputs()
    read_styles('<style name="NormalTheme"><item name="android:windowOptOutEdgeToEdgeEnforcement">false</item></style>',
                "styles.xml", "values", inputs)
    assert inputs.styles[0].opt_out_value is False
    assert inputs.styles[0].opt_out is not None


def test_manifest_normal_theme():
    inputs = AppInputs()
    read_manifest((SAMPLES / "player_default/android/app/src/main/AndroidManifest.xml").read_text(), "m", inputs)
    assert inputs.normal_theme[0] == "NormalTheme"


def test_dart_clues():
    inputs = AppInputs()
    read_dart(
        "// SystemChrome.setEnabledSystemUIMode(SystemUiMode.leanBack);\n"
        "SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);\n"
        "return Scaffold(body: SafeArea(child: x));\n"
        "AppBar(systemOverlayStyle: SystemUiOverlayStyle(statusBarColor: Colors.red));\n",
        "a.dart", inputs,
    )
    assert [m for m, _ in inputs.ui_modes] == ["edgeToEdge"]
    assert len(inputs.safe_areas) == len(inputs.scaffolds) == len(inputs.app_bars) == len(inputs.overlay_colors) == 1


def test_discover_sample_reads_app_module_only():
    inputs = discover(SAMPLES / "player_default")
    assert inputs.files == [
        "android/app/build.gradle",
        "android/app/src/main/AndroidManifest.xml",
        "android/app/src/main/res/values/styles.xml",
        "android/app/src/main/res/values-night/styles.xml",
        "lib/player_screen.dart",
    ]


def test_loose_styles_file_defaults_to_values(tmp_path):
    p = tmp_path / "styles.xml"
    p.write_text('<style name="NormalTheme"></style>')
    assert read_paths([p]).styles[0].qualifier == "values"


def test_version_range():
    cur, tgt = check_range("3.24.5", "3.27.1")
    assert (cur.default_target_sdk, tgt.default_target_sdk) == (34, 35)
    assert release_for("3.27.0-0.1.pre").snapshot_id == "flutter-3.27"
    for a, b in [("3.27.0", "3.24.0"), ("3.22.0", "3.27.0"), ("3.24.0", "3.29.0"), ("x", "3.27.0")]:
        with pytest.raises(UnsupportedVersion):
            check_range(a, b)
