"""Styles in build-type source sets such as src/debug (#35)."""

import shutil
from pathlib import Path

from fma.rules import AFFECTED, NEEDS_CHECK, audit
from fma.signals import discover

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
OPT_OUT = '<item name="android:windowOptOutEdgeToEdgeEnforcement">true</item>'


def project(tmp_path, sample="player_default"):
    root = tmp_path / sample
    shutil.copytree(SAMPLES / sample, root)
    return root


def add_debug_styles(root, opted=True):
    main = (root / "android/app/src/main/res/values/styles.xml").read_text()
    tag = '<style name="NormalTheme" parent="@android:style/Theme.Light.NoTitleBar">'
    text = main.replace(tag, tag + OPT_OUT) if opted else main
    d = root / "android/app/src/debug/res/values"
    d.mkdir(parents=True)
    (d / "styles.xml").write_text(text)


def finding(report, key):
    return next((f for f in report.findings if f.key == key), None)


def test_debug_styles_do_not_decide_the_opt_out(tmp_path, index):
    root = project(tmp_path)
    add_debug_styles(root)
    inputs = discover(root)
    assert all("src/debug" not in s.clue.file for s in inputs.styles)
    report = audit("3.24.5", "3.27.1", inputs, index)
    assert finding(report, "opt_out").verdict == AFFECTED
    assert any(
        "src/debug/res/values/styles.xml" in n and "`NormalTheme`" in n
        for n in report.notes
    )


def test_matching_debug_styles_add_no_note(tmp_path, index):
    root = project(tmp_path)
    add_debug_styles(root, opted=False)
    report = audit("3.24.5", "3.27.1", discover(root), index)
    assert not any("src/debug" in n for n in report.notes)


def test_night_wording_does_not_repeat_the_chain(index):
    """The night finding read "스타일 체인(...)에서 적용되는 스타일 체인에"."""
    from fma.signals import AppInputs, read_gradle, read_styles

    inputs = AppInputs()
    read_gradle("targetSdk = flutter.targetSdkVersion", "build.gradle", inputs)
    framework = "@android:style/Theme.Light.NoTitleBar"
    read_styles(
        f'<resources><style name="NormalTheme" parent="{framework}">{OPT_OUT}</style></resources>',
        "values/styles.xml",
        "values",
        inputs,
    )
    read_styles(
        f'<resources><style name="NormalTheme" parent="{framework}"/></resources>',
        "values-night/styles.xml",
        "values-night",
        inputs,
    )
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out_night")
    assert f.verdict == NEEDS_CHECK
    assert f.reason.count("스타일 체인") == 1, f.reason


def test_source_set_needs_a_source_set_shaped_suffix():
    from fma.signals import source_set

    assert source_set(Path("app/src/debug/res/values/styles.xml")) == "debug"
    assert (
        source_set(
            Path("outer/src/main/proj/android/app/src/debug/AndroidManifest.xml")
        )
        == "debug"
    )
    assert source_set(Path("android/app/src/main/AndroidManifest.xml")) == "main"
    assert source_set(Path("src/debug/notes/styles.xml")) is None


def test_explicit_styles_under_an_unrelated_src_are_judged(tmp_path):
    from fma.signals import read_paths

    f = tmp_path / "src/project/res/values/styles.xml"
    f.parent.mkdir(parents=True)
    f.write_text('<resources><style name="NormalTheme"/></resources>')
    inputs = read_paths([f])
    assert [s.name for s in inputs.styles] == ["NormalTheme"]


def test_checkout_under_src_main_keeps_main_manifest_first(tmp_path):
    root = tmp_path / "outer/src/main/project"
    shutil.copytree(SAMPLES / "player_default", root)
    d = root / "android/app/src/debug"
    d.mkdir(parents=True)
    (d / "AndroidManifest.xml").write_text(
        '<activity android:name=".MainActivity">\n'
        '<meta-data android:name="io.flutter.embedding.android.NormalTheme" android:resource="@style/DebugTheme"/>\n'
        "</activity>"
    )
    inputs = discover(root)
    assert inputs.normal_theme[0] == "NormalTheme"


def test_variant_with_another_parent_is_noted(tmp_path, index):
    root = project(tmp_path)
    main = (root / "android/app/src/main/res/values/styles.xml").read_text()
    d = root / "android/app/src/debug/res/values"
    d.mkdir(parents=True)
    (d / "styles.xml").write_text(
        main.replace(
            '<style name="NormalTheme" parent="@android:style/Theme.Light.NoTitleBar">',
            '<style name="NormalTheme" parent="LaunchTheme">',
        )
    )
    report = audit("3.24.5", "3.27.1", discover(root), index)
    assert any("src/debug" in n and "`NormalTheme`" in n for n in report.notes)


def test_unrelated_variant_style_adds_no_note(tmp_path, index):
    root = project(tmp_path)
    d = root / "android/app/src/debug/res/values"
    d.mkdir(parents=True)
    (d / "styles.xml").write_text(
        '<resources><style name="UnrelatedTheme"/></resources>'
    )
    report = audit("3.24.5", "3.27.1", discover(root), index)
    assert not any("src/debug" in n for n in report.notes)


def test_variant_only_styles_say_main_styles_are_missing(tmp_path, index):
    from fma.signals import read_paths

    root = project(tmp_path)
    add_debug_styles(root)
    inputs = read_paths(
        [
            root / "android/app/build.gradle",
            root / "android/app/src/debug/res/values/styles.xml",
        ],
        root,
    )
    f = finding(audit("3.24.5", "3.27.1", inputs, index), "opt_out")
    assert f.verdict == NEEDS_CHECK and "src/main" in f.reason
