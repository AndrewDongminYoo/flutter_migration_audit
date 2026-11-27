import json
from dataclasses import replace
from pathlib import Path

import pytest

from fma import rules
from fma.cli import main
from fma.rules import AFFECTED, NEEDS_CHECK, NOT_AFFECTED, audit
from fma.signals import AppInputs, discover, read_dart, read_gradle, read_manifest, read_styles

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
MANIFEST = (SAMPLES / "player_default/android/app/src/main/AndroidManifest.xml").read_text()
STYLES_PLAIN = '<style name="NormalTheme" parent="x">\n</style>\n'
STYLES_OPT_OUT = ('<style name="NormalTheme" parent="x">\n'
                  '  <item name="android:windowOptOutEdgeToEdgeEnforcement">true</item>\n</style>\n')


def verdicts(report):
    return {f.key: f.verdict for f in report.findings}


def make(gradle="targetSdk = flutter.targetSdkVersion", styles=STYLES_PLAIN, night=None, dart=None, manifest=MANIFEST):
    inputs = AppInputs()
    if gradle is not None:
        read_gradle(gradle, "build.gradle", inputs)
    if manifest is not None:
        read_manifest(manifest, "AndroidManifest.xml", inputs)
    if styles is not None:
        read_styles(styles, "values/styles.xml", "values", inputs)
    if night is not None:
        read_styles(night, "values-night/styles.xml", "values-night", inputs)
    if dart is not None:
        read_dart(dart, "main.dart", inputs)
    return inputs


def run(index, inputs):
    return audit("3.24.0", "3.27.0", inputs, index)


# --- the two public samples: same code, different settings ----------------

def test_samples_differ_only_in_opt_out_setting():
    a, b = SAMPLES / "player_default", SAMPLES / "player_opt_out"
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    changed = [str(p) for p in files_a if (a / p).read_text() != (b / p).read_text()]
    assert all(p.endswith("styles.xml") for p in changed) and changed


def test_sample_default_is_affected(index):
    report = run(index, discover(SAMPLES / "player_default"))
    assert verdicts(report) == {
        "target_sdk": AFFECTED,
        "opt_out": AFFECTED,
        "ui_mode_immersiveSticky": AFFECTED,
        "ui_mode_manual": AFFECTED,
        "layout": AFFECTED,
    }


def test_sample_opt_out_is_not_affected(index):
    report = run(index, discover(SAMPLES / "player_opt_out"))
    assert verdicts(report) == {"target_sdk": AFFECTED, "opt_out": NOT_AFFECTED}


@pytest.mark.parametrize("sample", ["player_default", "player_opt_out"])
def test_every_judgement_has_clue_evidence_and_test(index, sample):
    report = run(index, discover(SAMPLES / sample))
    for f in report.findings:
        assert f.clues, f.key
        assert f.evidence, f.key
        assert all(ev.snapshot_id == "flutter-3.27" for ev in f.evidence), f.key
        assert f.tests or f.verdict == NOT_AFFECTED and f.key == "target_sdk", f.key


# --- targetSdk branches ----------------------------------------------------

def test_explicit_target_below_35_stops_early(index):
    report = run(index, make(gradle="targetSdk = 34"))
    assert verdicts(report) == {"target_sdk": NOT_AFFECTED}
    assert report.notes


def test_explicit_target_35_is_not_caused_by_upgrade(index):
    assert verdicts(run(index, make(gradle="targetSdk = 35"))) == {"target_sdk": NOT_AFFECTED}


def test_target_36_is_outside_this_range(index):
    report = run(index, make(gradle="targetSdk = 36"))
    assert verdicts(report) == {"target_sdk": NEEDS_CHECK}
    assert "Android 16" in report.findings[0].check


def test_unknown_target_makes_everything_conditional(index):
    report = run(index, make(gradle="targetSdk = rootProject.ext.target", dart="Scaffold(\n"))
    assert set(verdicts(report).values()) == {NEEDS_CHECK}
    layout = next(f for f in report.findings if f.key == "layout")
    assert layout.reason.startswith("targetSdk가 35가 된다면")
    assert layout.evidence  # evidence is still shown


def test_missing_gradle_asks_for_it(index):
    report = run(index, make(gradle=None, styles=None))
    f = report.findings[0]
    assert (f.key, f.verdict) == ("target_sdk", NEEDS_CHECK)
    assert "targetSdk" in f.check


# --- opt-out branches ------------------------------------------------------

def test_night_style_without_opt_out_cites_later_correction(index):
    report = run(index, make(styles=STYLES_OPT_OUT, night=STYLES_PLAIN))
    assert verdicts(report) == {"target_sdk": AFFECTED, "opt_out": NOT_AFFECTED, "opt_out_night": NEEDS_CHECK}
    night = next(f for f in report.findings if f.key == "opt_out_night")
    assert [ev.later_correction for ev in night.evidence] == [True]


def test_manifest_theme_missing_from_styles(index):
    manifest = MANIFEST.replace("@style/NormalTheme", "@style/AppTheme")
    report = run(index, make(manifest=manifest))
    assert verdicts(report)["opt_out"] == NEEDS_CHECK


# --- code branches ---------------------------------------------------------

def test_already_migrated_app(index):
    dart = "SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);\nreturn Scaffold(\n"
    report = run(index, make(dart=dart))
    v = verdicts(report)
    assert v["ui_mode_edgeToEdge"] == NOT_AFFECTED and v["layout"] == NOT_AFFECTED


def test_safe_area_and_app_bar(index):
    assert verdicts(run(index, make(dart="Scaffold(body: SafeArea(child: x))\n")))["layout"] == NOT_AFFECTED
    assert verdicts(run(index, make(dart="Scaffold(appBar: AppBar(), body: x)\n")))["layout"] == NEEDS_CHECK


def test_no_ui_mode_call_needs_check(index):
    v = verdicts(run(index, make(dart="Scaffold(body: SafeArea(child: x))\n")))
    assert v["ui_mode"] == NEEDS_CHECK


def test_overlay_colors_stop_without_evidence(index):
    report = run(index, make(dart="SystemUiOverlayStyle(statusBarColor: Colors.red)\n"))
    f = next(f for f in report.findings if f.key == "overlay_colors")
    assert f.verdict == NEEDS_CHECK and not f.evidence and f.tests


def test_missing_evidence_downgrades_verdict(index, monkeypatch):
    broken = replace(rules.E["edge_default"], must_contain="this sentence is not in any doc")
    monkeypatch.setitem(rules.E, "edge_default", broken)
    report = run(index, make())
    f = next(f for f in report.findings if f.key == "opt_out")
    assert f.verdict == NEEDS_CHECK and f.missing_evidence == ["edge_default"]


# --- CLI -------------------------------------------------------------------

def test_cli_json(index, capsys):
    assert main(["audit", "--from", "3.24.5", "--to", "3.27.1", "--input", str(SAMPLES / "player_opt_out"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [f["verdict_label"] for f in data["findings"]] == ["영향 있음", "영향 없음"]


def test_cli_rejects_unsupported_range(index, capsys):
    assert main(["audit", "--from", "3.27.0", "--to", "3.29.0", "--input", str(SAMPLES / "player_default")]) == 2
    assert "스냅샷이 없습니다" in capsys.readouterr().err
    assert main(["audit", "--from", "3.24.0", "--to", "3.24.5", "--input", str(SAMPLES / "player_default")]) == 2
    assert "3.24.x → 3.27.x" in capsys.readouterr().err


def test_cli_requires_exactly_one_input_form(capsys):
    assert main(["audit", "--from", "3.24.0", "--to", "3.27.0"]) == 2
