"""The 3.32 -> 3.35 upgrade, where the default targetSdk moves from 35 to 36
(Android 16). Android 16 ignores the opt-out for apps that target API 36, so
the apps that change are the ones that relied on it (issue #18)."""

from pathlib import Path

import pytest

from fma.rules import AFFECTED, NEEDS_CHECK, NOT_AFFECTED, audit
from fma.signals import AppInputs, discover, read_gradle, read_manifest, read_styles
from fma.versions import check_range, release_for

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
FRAMEWORK = "@android:style/Theme.Light.NoTitleBar"
ITEM = '<item name="android:windowOptOutEdgeToEdgeEnforcement">{}</item>'
MANIFEST = (
    '<meta-data android:name="io.flutter.embedding.android.NormalTheme" '
    'android:resource="@style/NormalTheme" />'
)


def xml(value):
    item = ITEM.format(value) if value else ""
    return f'<resources><style name="NormalTheme" parent="{FRAMEWORK}">{item}</style></resources>'


def inputs(*styles, gradle="targetSdk = flutter.targetSdkVersion"):
    inp = AppInputs()
    read_gradle(gradle, "build.gradle", inp)
    read_manifest(MANIFEST, "AndroidManifest.xml", inp)
    for qualifier, text in styles:
        read_styles(text, f"{qualifier}/styles.xml", qualifier, inp)
    return inp


def finding(report, key):
    return next(f for f in report.findings if f.key == key)


def test_range_is_supported():
    cur, tgt = check_range("3.32.5", "3.35.1")
    assert (cur.default_target_sdk, tgt.default_target_sdk) == (35, 36)
    assert release_for("3.35.0").snapshot_id == "flutter-3.35"


def test_opted_out_app_loses_the_opt_out_on_android16(index):
    report = audit("3.32.5", "3.35.1", discover(SAMPLES / "player_opt_out"), index)
    target = finding(report, "target_sdk")
    assert target.verdict == AFFECTED
    assert "API 35에서 API 36(Android 16)으로 바뀝니다" in target.reason
    f = finding(report, "opt_out")
    assert f.verdict == AFFECTED and "Android 16" in f.reason
    assert {e.snapshot_id for e in f.evidence} == {"flutter-3.35"}
    assert any("cannot opt-out" in e.quote for e in f.evidence)
    crash = finding(report, "opt_out_android16")
    assert crash.verdict == NEEDS_CHECK
    assert [e.later_correction for e in crash.evidence] == [True]
    mode = finding(report, "ui_mode_immersiveSticky")
    assert mode.verdict == AFFECTED
    assert any("ignore this value" in e.quote for e in mode.evidence)
    assert finding(report, "layout").verdict == AFFECTED


def test_app_without_opt_out_was_already_edge_to_edge(index):
    report = audit("3.32.5", "3.35.1", discover(SAMPLES / "player_default"), index)
    assert [f.key for f in report.findings] == ["target_sdk", "opt_out"]
    f = finding(report, "opt_out")
    assert f.verdict == NOT_AFFECTED and "targetSdk 35" in f.reason
    assert report.notes


def test_explicit_target_35_is_not_changed_by_the_upgrade(index):
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml("true")), gradle="targetSdk = 35"),
        index,
    )
    f = finding(report, "target_sdk")
    assert f.verdict == NOT_AFFECTED and "36으로 올리면" in f.reason
    assert [x.key for x in report.findings] == ["target_sdk"]


def test_explicit_target_36_was_already_android16(index):
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml("true")), gradle="targetSdk = 36"),
        index,
    )
    f = finding(report, "target_sdk")
    assert f.verdict == NOT_AFFECTED and "이미 targetSdk 36을" in f.reason


def test_version_resources_without_the_item_were_already_edge_to_edge(index):
    """values-v36 without the opt-out item (the later docs' crash workaround):
    Android 16 devices drew edge-to-edge before the upgrade, and Android 15
    devices behave the same with targetSdk 35 and 36."""
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml("true")), ("values-v36", xml(None))),
        index,
    )
    f = finding(report, "opt_out")
    assert f.verdict == NOT_AFFECTED and "values-v36" in f.reason
    assert [x.key for x in report.findings] == ["target_sdk", "opt_out"]


def test_opt_out_only_in_values_v36_is_lost(index):
    """Codex review on #32: the opt-out that only Android 16 devices select
    still applied at targetSdk 35 and is ignored at 36."""
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml(None)), ("values-v36", xml("true"))),
        index,
    )
    assert finding(report, "opt_out").verdict == AFFECTED
    assert finding(report, "opt_out_android16").verdict == NEEDS_CHECK


def test_missing_parent_on_android16_stays_open(index):
    """Codex review on #32: a values-v36 theme whose local parent is not in
    the input may inherit the item, so it is not reported as absent."""
    v36 = '<resources><style name="NormalTheme" parent="Base.Theme"/></resources>'
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml("true")), ("values-v36", v36)),
        index,
    )
    assert finding(report, "opt_out").verdict == NEEDS_CHECK
    assert all(f.key != "opt_out_android16" for f in report.findings)


def test_overlay_colors_stop_working_on_android16(index):
    inp = inputs(("values", xml("true")))
    from fma.signals import read_dart

    read_dart(
        "SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle(statusBarColor: Colors.red));",
        "lib/main.dart",
        inp,
    )
    f = finding(audit("3.32.5", "3.35.1", inp, index), "overlay_colors")
    assert f.verdict == AFFECTED and {e.snapshot_id for e in f.evidence} == {
        "flutter-3.35"
    }


def test_unknown_target_is_conditional_on_36(index):
    inp = inputs(("values", xml("true")), gradle="targetSdk = rootProject.ext.target")
    later = [f for f in audit("3.32.5", "3.35.1", inp, index).findings][1:]
    assert any(f.reason.startswith("targetSdk가 36이 된다면: ") for f in later)


@pytest.mark.parametrize("sample", ["player_default", "player_opt_out"])
def test_every_android16_spec_resolves(index, sample):
    report = audit("3.32.5", "3.35.1", discover(SAMPLES / sample), index)
    assert not [f.missing_evidence for f in report.findings if f.missing_evidence]


def test_docs_style_values_35_is_not_a_version_resource(index):
    """The later docs say `values-35`; Android's platform version qualifier is
    `v35`, so that directory is not a version resource and the API 36 device
    still selects the opt-out from `values`."""
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml("true")), ("values-35", xml(None))),
        index,
    )
    f = finding(report, "opt_out_android16")
    assert f.verdict == NEEDS_CHECK
    assert "`values-35`" in f.reason and "`values-v35`" in f.reason


def test_unchecked_directories_keep_the_android16_check_open(index):
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(
            ("values", xml("true")),
            ("values-v36", xml(None)),
            ("values-xhdpi", xml("true")),
        ),
        index,
    )
    assert finding(report, "opt_out").verdict == NOT_AFFECTED
    f = finding(report, "opt_out_variant")
    assert f.verdict == NEEDS_CHECK and "`values-xhdpi`" in f.reason


def test_opt_out_only_in_night_styles_is_lost(index):
    """Subagent review: a dark-mode style that opts out on Android 16 loses
    the opt-out at targetSdk 36, although the default style has none."""
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml(None)), ("values-night", xml("true"))),
        index,
    )
    f = finding(report, "opt_out")
    assert f.verdict == AFFECTED and "`values-night`" in f.reason
    assert finding(report, "opt_out_android16").verdict == NEEDS_CHECK
    assert any(x.key == "layout" for x in report.findings)


def test_night_opt_out_under_values_v36(index):
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(
            ("values", xml("true")),
            ("values-v36", xml(None)),
            ("values-night-v36", xml("true")),
        ),
        index,
    )
    f = finding(report, "opt_out")
    assert f.verdict == AFFECTED and "`values-night`" in f.reason


def test_night_styles_without_the_item_stay_unaffected(index):
    report = audit(
        "3.32.5",
        "3.35.1",
        inputs(("values", xml(None)), ("values-night", xml(None))),
        index,
    )
    assert [(f.key, f.verdict) for f in report.findings] == [
        ("target_sdk", AFFECTED),
        ("opt_out", NOT_AFFECTED),
    ]


@pytest.mark.parametrize(
    "text, quote",
    [
        ("- other item\n- the needle sentence\n- trailing item", "the needle sentence"),
        ("- outer\n  - the needle sentence\n- trailing", "the needle sentence"),
        # Numbered items read as one argument, so the list is quoted whole.
        (
            "1. other item\n2. the needle sentence",
            "1. other item 2. the needle sentence",
        ),
    ],
)
def test_quote_is_the_bullet_item_that_holds_the_sentence(text, quote):
    from fma.corpus import Chunk
    from fma.evidence import quote_for

    chunk = Chunk("c#0", "c", "flutter-3.35", "release-notes", "t", "h", text, "u", "r")
    assert quote_for(chunk, "needle sentence") == quote
