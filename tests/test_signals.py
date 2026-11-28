from pathlib import Path

import pytest

from fma.signals import (
    AppInputs,
    discover,
    read_dart,
    read_gradle,
    read_manifest,
    read_paths,
    read_styles,
)
from fma.versions import UnsupportedVersion, check_range, release_for

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.mark.parametrize(
    "line, raw",
    [
        ("        targetSdk = flutter.targetSdkVersion", "flutter.targetSdkVersion"),
        ("        targetSdk = 34", "34"),
        ("        targetSdkVersion 34", "34"),
        (
            "        targetSdkVersion flutter.targetSdkVersion",
            "flutter.targetSdkVersion",
        ),
        ("        targetSdk = rootProject.ext.targetSdk", "rootProject.ext.targetSdk"),
    ],
)
def test_gradle_target_sdk_forms(line, raw):
    inputs = AppInputs()
    read_gradle(
        f"android {{\n  defaultConfig {{\n{line}\n  }}\n}}\n", "build.gradle", inputs
    )
    assert inputs.target_sdk.raw == raw
    assert inputs.target_sdk.clue.line == 3


def test_gradle_ignores_commented_target():
    inputs = AppInputs()
    read_gradle(
        "// targetSdk = 30\n        targetSdk = flutter.targetSdkVersion\n",
        "build.gradle",
        inputs,
    )
    assert inputs.target_sdk.uses_flutter_default
    assert inputs.target_sdk.clue.line == 2


def test_styles_opt_out_and_qualifier():
    text = (
        "<resources>\n"
        '  <style name="LaunchTheme" parent="x">\n  </style>\n'
        '  <style name="NormalTheme" parent="x">\n'
        '    <item name="android:windowOptOutEdgeToEdgeEnforcement">true</item>\n'
        "  </style>\n</resources>\n"
    )
    inputs = AppInputs()
    read_styles(text, "values-night/styles.xml", "values-night", inputs)
    by_name = {s.name: s for s in inputs.styles}
    assert by_name["LaunchTheme"].opt_out is None
    assert by_name["NormalTheme"].opt_out.line == 5
    assert by_name["NormalTheme"].qualifier == "values-night"


def test_styles_opt_out_false_is_recorded_as_false():
    inputs = AppInputs()
    read_styles(
        '<style name="NormalTheme"><item name="android:windowOptOutEdgeToEdgeEnforcement">false</item></style>',
        "styles.xml",
        "values",
        inputs,
    )
    assert inputs.styles[0].opt_out_value is False
    assert inputs.styles[0].opt_out is not None


def test_manifest_normal_theme():
    inputs = AppInputs()
    read_manifest(
        (
            SAMPLES / "player_default/android/app/src/main/AndroidManifest.xml"
        ).read_text(),
        "m",
        inputs,
    )
    assert inputs.normal_theme[0] == "NormalTheme"


def test_dart_clues():
    inputs = AppInputs()
    read_dart(
        "// SystemChrome.setEnabledSystemUIMode(SystemUiMode.leanBack);\n"
        "SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);\n"
        "return Scaffold(body: SafeArea(child: x));\n"
        "AppBar(systemOverlayStyle: SystemUiOverlayStyle(statusBarColor: Colors.red));\n",
        "a.dart",
        inputs,
    )
    assert [m for m, _ in inputs.ui_modes] == ["edgeToEdge"]
    assert (
        len(inputs.safe_areas)
        == len(inputs.scaffolds)
        == len(inputs.app_bars)
        == len(inputs.overlay_colors)
        == 1
    )


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
    for a, b in [
        ("3.27.0", "3.24.0"),
        ("3.22.0", "3.27.0"),
        ("3.24.0", "3.29.0"),
        ("x", "3.27.0"),
    ]:
        with pytest.raises(UnsupportedVersion):
            check_range(a, b)


# --- upgrade ranges (issue #18) ------------------------------------------


@pytest.fixture
def extra_range(monkeypatch):
    """A second supported range, 3.27 → 3.29 with targetSdk 36. The real
    second range lands with its docs snapshot; this checks the plumbing."""
    from fma import versions

    fake = versions.Release((3, 29), "flutter-3.29", 36)
    monkeypatch.setitem(versions.RELEASES, (3, 29), fake)
    monkeypatch.setattr(
        versions, "SUPPORTED_RANGES", (*versions.SUPPORTED_RANGES, ((3, 27), (3, 29)))
    )
    return fake


def test_every_supported_range_is_accepted(extra_range):
    from fma.versions import target_releases

    assert check_range("3.27.1", "3.29.0")[1] == extra_range
    assert check_range("3.24.5", "3.27.1")[1].snapshot_id == "flutter-3.27"
    assert [r.snapshot_id for r in target_releases()][-1] == "flutter-3.29"
    with pytest.raises(UnsupportedVersion) as e:
        check_range("3.24.0", "3.29.0")  # skipping a range is not supported
    assert str(e.value).startswith("Flutter 3.24.x → 3.27.x, ")
    assert "3.27.x → 3.29.x 구간만 분석합니다" in str(e.value)


def test_cli_scope_covers_every_target_release(extra_range):
    from fma.retrieval import cli_scope

    snapshots = {s for s, _ in cli_scope()}
    assert {"flutter-3.27", "flutter-3.29"} <= snapshots


def test_device_api_selects_version_directories():
    from fma.signals import best_match, device_config

    dirs = {"values", "values-v35", "values-v36"}
    assert best_match(dirs, device_config("values", 35)) == "values-v35"
    assert best_match(dirs, device_config("values", 36)) == "values-v36"


def test_evidence_label_names_any_release_snapshot():
    from fma.evidence import Evidence

    ev = Evidence("k", "q", "t", "h", "u", "flutter-3.35", "3.35.0", False, 1)
    assert ev.source_label() == "Flutter 3.35 문서 (flutter/flutter 3.35.0)"


def test_report_text_follows_the_target_release(extra_range, index):
    from fma.rules import audit
    from fma.signals import AppInputs

    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    f = audit("3.27.0", "3.29.0", inputs, index).findings[0]
    # Korean particles after the number change in the range that adds API 36.
    assert "API 35에서 API 36(Android 16)" in f.reason
    assert (
        "Android 16(API 36) 에뮬레이터에서 Flutter 3.27 빌드와 Flutter 3.29"
        in f.tests[0]
    )
