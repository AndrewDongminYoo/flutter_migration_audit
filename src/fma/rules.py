"""Audit rules for Android system bars and edge-to-edge across a Flutter upgrade.

Each rule reads app clues, picks a verdict, and names the doc evidence that
backs it. If the evidence cannot be found in the right version of the docs,
the verdict drops to "needs check": the audit does not state what the docs
do not say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .evidence import Evidence, Spec, resolve
from .korean import josa
from .retrieval import Retriever
from .signals import (
    THRESHOLD_KINDS,
    AppInputs,
    Clue,
    OptOutResolution,
    config_name,
    device_config,
    normalize_config,
    qualifier_parts,
    resolve_opt_out,
    unchecked_qualifiers,
)
from .versions import EDGE_TO_EDGE_API, Release, android_name, check_range

AFFECTED, NOT_AFFECTED, NEEDS_CHECK = "affected", "not_affected", "needs_check"
OPT_OUT_TITLE = "edge-to-edge opt-out 설정"
LABELS = {
    AFFECTED: "영향 있음",
    NOT_AFFECTED: "영향 없음",
    NEEDS_CHECK: "추가 확인 필요",
}

BC = frozenset({"breaking-change"})
API = frozenset({"api"})
RELEASE_NOTES = frozenset({"release-notes"})
GUIDE = frozenset({"guide"})
EDGE_QUERY = "SystemUiMode edge-to-edge default Android SDK 15 targetSdkVersion opt out"

E = {
    "target_default": Spec(
        "target_default",
        EDGE_QUERY + " flutter.targetSdkVersion 3.27",
        "If your app targets `flutter.targetSdkVersion`",
        kinds=BC,
    ),
    "target_explicit": Spec(
        "target_explicit",
        EDGE_QUERY + " Prior to Flutter 3.27 Android 14",
        "your app _will_ be impacted when you choose to target Android 15",
        kinds=BC,
    ),
    "edge_default": Spec(
        "edge_default",
        EDGE_QUERY + " automatically displays",
        "your app automatically displays in edge-to-edge mode",
        kinds=BC,
    ),
    "unset_mode": Spec(
        "unset_mode",
        EDGE_QUERY + " unset SystemUiMode non-edge-to-edge behavior",
        "including an unset `SystemUiMode`",
        kinds=BC,
    ),
    "already_migrated": Spec(
        "already_migrated",
        EDGE_QUERY + " SystemChrome.setEnabledSystemUIMode already migrated",
        "then your app is already migrated",
        kinds=BC,
    ),
    "opt_out_works": Spec(
        "opt_out_works",
        "opt out edge-to-edge windowOptOutEdgeToEdgeEnforcement styles.xml NormalTheme style",
        "This modified style opts your app out",
        kinds=BC,
    ),
    "opt_out_parent": Spec(
        "opt_out_parent",
        "parent style child styles opt out modify the parent only windowOptOutEdgeToEdgeEnforcement",
        "you can modify the parent only",
        kinds=BC,
    ),
    "opt_out_temporary": Spec(
        "opt_out_temporary",
        EDGE_QUERY + " workaround temporary migrate before",
        "Android plans for the workaround detailed here to be temporary",
        kinds=BC,
    ),
    "launch_switch": Spec(
        "launch_switch",
        "splash screen launch theme normal theme FlutterActivity NormalTheme meta-data switch",
        "to be applied to `FlutterActivity` after the launch screen is gone",
        heading="Initializing the app",
    ),
    "opt_out_night": Spec(
        "opt_out_night",
        "opt out edge-to-edge windowOptOutEdgeToEdgeEnforcement night mode styles values-night",
        "apply the same change in the night mode styles file",
        snapshot="later_correction",
        kinds=BC,
    ),
    "edge_api": Spec(
        "edge_api",
        "SystemUiMode edgeToEdge status navigation elements rendered over the application",
        "status and navigation elements rendered over the application",
        kinds=API,
        heading="SystemUiMode.edgeToEdge",
    ),
    "safe_area": Spec(
        "safe_area",
        "SafeArea insets status bar Android operating system UI cutouts",
        "such as the status bar on Android",
        kinds=GUIDE,
    ),
    "safe_area_scaffold": Spec(
        "safe_area_scaffold",
        "wrap the body of a Scaffold widget in SafeArea",
        "wrap the body of a `Scaffold` widget in `SafeArea`",
        kinds=GUIDE,
    ),
    "app_bar_primary": Spec(
        "app_bar_primary",
        "AppBar primary padded on top height of the system status bar",
        "padded on top by the height of the system status bar",
        kinds=API,
        heading="AppBar.primary",
    ),
    # Probe: does the target doc say how overlay colors behave under
    # edge-to-edge? If it ever resolves, the rule can use it.
    "overlay_color_edge": Spec(
        "overlay_color_edge",
        "SystemUiOverlayStyle statusBarColor edge-to-edge Android 15",
        "edge-to-edge",
        kinds=API,
        heading="SystemUiOverlayStyle.statusBarColor",
    ),
}


def mode_spec(mode: str) -> Spec:
    return Spec(
        f"mode_{mode}",
        f"SystemUiMode {mode} Android SDK 15 API 35 must migrate edge-to-edge",
        "must migrate using the instructions in",
        kinds=API,
        heading=f"SystemUiMode.{mode}",
    )


# Evidence for a target release whose default targetSdk is 36 (Android 16).
# The 3.35 docs already say that an app targeting 36 cannot opt out. The
# crash warning and the version-specific resources were added to the website
# in 2026-02, after the 3.35 window, so they are a later correction.
A16 = {
    "target_default": Spec(
        "target_default_36",
        "Flutter 3.35 release notes Android 16 Bumping Framework Default TargetSdk to 36",
        "Bumping Framework Default TargetSdk to 36",
        kinds=RELEASE_NOTES,
        heading="Android",
    ),
    "opt_out_ignored": Spec(
        "opt_out_ignored",
        EDGE_QUERY + " targets Android SDK version 16 or later cannot opt-out",
        "and you cannot opt-out",
        kinds=BC,
    ),
    "modes_no_opt_out": Spec(
        "modes_no_opt_out",
        "SystemChrome setEnabledSystemUIMode Android SDK 16 API 36 other SystemUiModes will NOT work no way to opt out",
        "There is no way to opt out of",
        kinds=API,
        heading="SystemChrome.setEnabledSystemUIMode",
    ),
    "overlay_color_api36": Spec(
        "overlay_color_api36",
        "SystemChrome setSystemUIOverlayStyle Android SDK 16 API 36 statusBarColor systemNavigationBarColor will not work",
        "systemNavigationBarColor] will not work.",
        kinds=API,
        heading="SystemChrome.setSystemUIOverlayStyle",
    ),
    "opt_out_crash": Spec(
        "opt_out_crash",
        "Android 16 or later opt out of edge-to-edge might cause your app to crash version-specific resources",
        "might cause your app to crash",
        snapshot="later_correction",
        kinds=BC,
        heading="Android 16 (or later)",
    ),
}


def mode_ignored_spec(mode: str) -> Spec:
    return Spec(
        f"mode_ignored_{mode}",
        f"SystemUiMode {mode} Android SDK 16 API 36 Android system will ignore this value",
        "then the Android system will ignore this value",
        kinds=API,
        heading=f"SystemUiMode.{mode}",
    )


UI_MODES = ("leanBack", "immersive", "immersiveSticky", "edgeToEdge", "manual")


def all_specs(release: Release) -> list[Spec]:
    """Every spec the rules for an upgrade to `release` can request."""
    specs = list(E.values())
    if release.default_target_sdk > EDGE_TO_EDGE_API:
        return specs + list(A16.values()) + [mode_ignored_spec(m) for m in UI_MODES]
    return specs + [mode_spec(m) for m in UI_MODES]


@dataclass
class Finding:
    key: str
    title: str
    verdict: str
    reason: str
    clues: list[Clue] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    check: str | None = None
    missing_evidence: list[str] = field(default_factory=list)


@dataclass
class Report:
    current: str
    target: str
    files: list[str]
    findings: list[Finding]
    notes: list[str]
    retriever: str | None = None


class Auditor:
    def __init__(self, cur: Release, tgt: Release, inputs: AppInputs, index: Retriever):
        self.cur, self.tgt, self.inputs, self.index = cur, tgt, inputs, index
        self.findings: list[Finding] = []
        self.notes: list[str] = []
        self.conditional = False  # targetSdk after upgrade is unknown

    def add(
        self, key, title, verdict, reason, clues=(), specs=(), tests=(), check=None
    ):
        finding = Finding(
            key, title, verdict, reason, list(clues), tests=list(tests), check=check
        )
        for spec in specs:
            ev = resolve(spec, self.tgt, self.index)
            if ev:
                finding.evidence.append(ev)
            else:
                finding.missing_evidence.append(spec.key)
        if finding.missing_evidence and verdict != NEEDS_CHECK:
            finding.verdict = NEEDS_CHECK
            finding.check = (
                finding.check
                or "근거 문서를 찾지 못했습니다. 판단 전에 공식 문서를 직접 확인하세요."
            )
        if self.conditional and finding.verdict != NEEDS_CHECK:
            n = self.tgt.default_target_sdk
            finding.reason = f"targetSdk가 {josa(n, '이/가')} 된다면: " + finding.reason
            finding.verdict = NEEDS_CHECK
            finding.check = finding.check or "targetSdk 값을 먼저 확인하세요."
        self.findings.append(finding)
        return finding

    # -- rules -------------------------------------------------------------

    def target_sdk(self) -> bool:
        """Return True if later rules apply (target reaches EDGE_TO_EDGE_API or is unknown)."""
        inp, cur, tgt = (
            self.inputs,
            self.cur.default_target_sdk,
            self.tgt.default_target_sdk,
        )
        ts = inp.target_sdk
        title = "targetSdk 변화"
        compare = (
            f"{self.device} 에뮬레이터에서 {self.cur_label} 빌드와 {self.tgt_label} "
            "빌드의 첫 화면을 열고 상단 상태바·하단 내비게이션 바 주변을 비교한다."
        )
        if not inp.gradle_provided or ts is None:
            where = (
                "build.gradle을 받지 못했습니다"
                if not inp.gradle_provided
                else "build.gradle에서 targetSdk 줄을 찾지 못했습니다"
            )
            self.add(
                "target_sdk",
                title,
                NEEDS_CHECK,
                f"{where}. 기본값(flutter.targetSdkVersion)을 쓰면 {cur}에서 {josa(tgt, '으로/로')} 바뀝니다.",
                specs=[self.target_default_spec],
                check="android/app/build.gradle(.kts)의 targetSdk 값을 확인하세요.",
            )
            self.conditional = True
            return True
        if ts.uses_flutter_default:
            self.add(
                "target_sdk",
                title,
                AFFECTED,
                f"targetSdk가 flutter.targetSdkVersion을 따르므로 API {cur}에서 {josa(f'API {tgt}({android_name(tgt)})', '으로/로')} 바뀝니다.",
                [ts.clue],
                [self.target_default_spec],
                [compare],
            )
            return True
        if ts.explicit is not None and ts.explicit < EDGE_TO_EDGE_API:
            self.add(
                "target_sdk",
                title,
                NOT_AFFECTED,
                f"targetSdk를 {josa(ts.explicit, '으로/로')} 직접 지정해서 이번 업그레이드로는 바뀌지 않습니다. "
                f"{josa(EDGE_TO_EDGE_API, '으로/로')} 올리는 시점에 같은 영향이 생깁니다.",
                [ts.clue],
                [E["target_explicit"]],
            )
            self.notes.append(
                f"targetSdk가 {EDGE_TO_EDGE_API} 미만으로 고정되어 있어 시스템 바 관련 나머지 항목은 확인하지 않았습니다."
            )
            return False
        if ts.explicit is not None and ts.explicit < tgt:
            # Only when the target raises the default past EDGE_TO_EDGE_API
            # (35 -> 36): an explicit 35 does not move with Flutter.
            self.add(
                "target_sdk",
                title,
                NOT_AFFECTED,
                f"targetSdk를 {josa(ts.explicit, '으로/로')} 직접 지정해서 이번 업그레이드로는 바뀌지 않습니다. "
                f"{josa(tgt, '으로/로')} 올리면 {android_name(tgt)} 동작 변경의 영향을 받을 수 있으니, 그때 다시 분석하세요.",
                [ts.clue],
                [A16["opt_out_ignored"]],
            )
            self.notes.append(
                f"targetSdk가 {josa(ts.explicit, '으로/로')} 고정되어 있어 나머지 항목은 이번 업그레이드의 영향으로 보지 않았습니다."
            )
            return False
        if ts.explicit is not None and ts.explicit == tgt:
            self.add(
                "target_sdk",
                title,
                NOT_AFFECTED,
                f"이미 targetSdk {josa(tgt, '을/를')} 직접 지정하고 있어 Flutter 버전과 관계없이 "
                f"{self.already_state} 이번 업그레이드로 바뀌는 것은 없습니다.",
                [ts.clue],
                [self.already_spec],
            )
            self.notes.append(
                f"업그레이드 전부터 targetSdk {josa(tgt, '이었/였')}으므로 나머지 항목은 이번 업그레이드의 영향으로 보지 않았습니다."
            )
            return False
        if ts.explicit is not None:
            self.add(
                "target_sdk",
                title,
                NEEDS_CHECK,
                f"targetSdk {josa(ts.explicit, '은/는')} {josa(f'이번 구간 문서({self.tgt_label} 기준 {android_name(tgt)})', '이/가')} 다루지 않는 값입니다.",
                [ts.clue],
                check=f"{android_name(tgt + 1)} 이상을 대상으로 할 때의 동작은 이 구간 문서로 판단할 수 없습니다. "
                f"{android_name(tgt + 1)} 동작 변경 문서를 직접 확인하세요.",
            )
            return False
        self.add(
            "target_sdk",
            title,
            NEEDS_CHECK,
            f"targetSdk가 `{ts.raw}` 식으로 설정되어 있어 실제 값을 알 수 없습니다.",
            [ts.clue],
            [self.target_default_spec],
            check=f"`{ts.raw}` 식이 가리키는 값을 확인하세요. flutter.targetSdkVersion이면 {cur}→{josa(tgt, '으로/로')} 바뀝니다.",
        )
        self.conditional = True
        return True

    already_state = "edge-to-edge가 적용되던 상태입니다."

    @property
    def target_default_spec(self) -> Spec:
        return E["target_default"]

    @property
    def already_spec(self) -> Spec:
        return E["edge_default"]

    def theme(self) -> tuple[str | None, list[Clue]]:
        """The theme the app screen uses: the NormalTheme meta-data, else the
        activity's own theme, which Flutter keeps without the meta-data.
        None when a manifest was given but names neither. Without a manifest,
        the template's NormalTheme."""
        inp = self.inputs
        if inp.ambiguous_themes:
            return None, []  # several FlutterActivities, none the launcher
        if inp.normal_framework and not inp.normal_theme:
            return None, []  # the meta-data names a theme styles.xml cannot hold
        found = inp.normal_theme or inp.launch_theme
        if found:
            return found[0], [found[1]]
        return (None if inp.manifest_provided else "NormalTheme"), []

    def opt_out_state(self, api: int) -> OptOutResolution | None:
        """Resolve the theme's opt-out on a device that runs `api`. Return the
        resolution when the value is known (set, `false`, or absent);
        otherwise add a "needs check" finding and return None."""
        inp = self.inputs
        title = OPT_OUT_TITLE
        if not inp.styles_provided:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                "styles.xml을 받지 못해 opt-out 여부를 알 수 없습니다.",
                specs=[E["edge_default"]],
                check="res/values/styles.xml의 NormalTheme에 "
                "android:windowOptOutEdgeToEdgeEnforcement 항목이 있는지 확인하세요.",
            )
            return None
        theme_name, clues = self.theme()
        if theme_name is None:
            framework = inp.normal_framework or inp.framework_theme
            if inp.ambiguous_themes:
                names = ", ".join(f"`{t}`" for t, _ in inp.ambiguous_themes)
                reason = (
                    f"NormalTheme meta-data가 있는 activity가 여럿이고({names}) 그중 실행 activity를 "
                    "정할 수 없어, 어느 스타일의 opt-out을 봐야 할지 알 수 없습니다."
                )
                framework = None
            elif framework:
                reason = (
                    f"FlutterActivity가 앱 스타일이 아닌 `{framework[0]}` 테마를 써서, "
                    "styles.xml에서 opt-out 여부를 판단할 수 없습니다."
                )
            else:
                reason = (
                    "AndroidManifest.xml에서 FlutterActivity의 테마(NormalTheme meta-data나 "
                    "android:theme)를 찾지 못해, 어느 스타일의 opt-out을 봐야 할지 알 수 없습니다."
                )
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                reason,
                (
                    [c for _, c in inp.ambiguous_themes]
                    if inp.ambiguous_themes
                    else [framework[1]] if framework else []
                ),
                specs=[E["launch_switch"]],
                check=(
                    "실제로 실행되는 FlutterActivity가 어느 것인지 확인하고, 그 activity의 NormalTheme 스타일을 확인하세요."
                    if inp.ambiguous_themes
                    else (
                        "이 테마에 opt-out 항목이 있는지, 코드에서 테마를 바꾸는지 확인하세요."
                        if framework
                        else "FlutterActivity가 쓰는 테마를 확인하고, 그 activity가 들어 있는 AndroidManifest.xml을 넣어 주세요."
                    )
                ),
            )
            return None
        judged = {(st.qualifier, st.name): st.opt_out_raw for st in inp.styles}
        for st in inp.variant_styles:
            key = (st.qualifier, st.name)
            if key in judged and judged[key] == st.opt_out_raw:
                continue  # the same opt-out as the judged style
            note = (
                f"`{st.clue.file}`의 {st.clue.line}행은 빌드 유형별 소스 세트에서 `{st.name}` 스타일을 "
                "다르게 정의합니다. opt-out은 기본 소스 세트(main)의 스타일로 판단했으므로, "
                "이 소스 세트를 쓰는 빌드에서는 결과가 다를 수 있습니다."
            )
            if note not in self.notes:
                self.notes.append(note)
        for clue in inp.merge_directives:
            note = (
                f"`{clue.file}`의 {clue.line}행에 manifest 병합 지시(tools:node 등)가 있습니다. "
                "병합 결과는 계산하지 않았으므로, 이 manifest를 쓰는 빌드에서는 테마가 다를 수 있습니다."
            )
            if note not in self.notes:
                self.notes.append(note)
        for other, clue in inp.other_themes:
            note = (
                f"`{clue.file}`의 {clue.line}행은 `{other}` 테마를 지정하지만, "
                "먼저 읽은 기본 manifest의 테마로 판단했습니다. 이 manifest를 쓰는 빌드에서는 결과가 다를 수 있습니다."
            )
            if note not in self.notes:
                self.notes.append(note)
        if not inp.normal_theme and inp.launch_theme:
            note = (
                f"AndroidManifest.xml에 NormalTheme meta-data가 없어, FlutterActivity가 계속 쓰는 "
                f"`{theme_name}` 스타일로 판단했습니다."
            )
            if note not in self.notes:
                self.notes.append(note)
        day = resolve_opt_out(inp.styles, theme_name, "values", api)
        if day is None:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                f"앱이 쓰는 `{theme_name}` 스타일이 제공된 res/values/styles.xml에 없습니다.",
                clues,
                check=f"`{theme_name}` 스타일 정의를 찾아 opt-out 항목을 확인하세요.",
            )
            return None
        own = day.styles[0]  # the theme as Android selects it (may be values-v21 etc.)
        if day.value:
            return day
        if day.unresolved_value:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                f"`{day.source}`의 opt-out 항목 값이 `{day.unresolved_value}`라서 참인지 거짓인지 알 수 없습니다. "
                "이 항목이 있으면 부모 스타일의 값은 쓰이지 않습니다.",
                clues + [day.clue],
                [E["opt_out_works"]],
                check=f"`{day.unresolved_value}` 리소스가 가리키는 값(예: res/values/bools.xml)을 확인하세요.",
            )
            return None
        if day.missing_parent:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                f"`{theme_name}` 스타일의 부모인 `{day.missing_parent}` 스타일이 제공된 styles.xml에 없어, "
                "opt-out 항목을 상속받는지 확인할 수 없습니다.",
                clues + [own.clue],
                [E["opt_out_parent"]],
                check=f"`{day.missing_parent}` 스타일 정의가 들어 있는 styles.xml을 함께 넣어 주세요.",
            )
            return None
        return day

    def opt_out(self) -> bool | None:
        """Return True if opted out, False if not, None if unknown."""
        day = self.opt_out_state(self.api)
        if day is None:
            return None
        inp = self.inputs
        title = OPT_OUT_TITLE
        theme_name, clues = self.theme()
        assert theme_name is not None  # opt_out_state resolved it
        own = day.styles[0]
        inherited = day.source is not None and day.source != theme_name
        if day.value:
            caveat = (
                ""
                if inp.manifest_provided
                else " (AndroidManifest.xml을 받지 못해 이 스타일이 실제로 쓰이는지는 확인하지 않았습니다.)"
            )
            where = (
                f"`{theme_name}` 스타일이 부모인 `{day.source}` 스타일에서 opt-out 항목을 상속받아"
                if inherited
                else f"`{theme_name}`에 opt-out 항목이 있어"
            )
            specs = [E["opt_out_works"], E["opt_out_temporary"]]
            if inherited:
                specs.insert(1, E["opt_out_parent"])
            self.add(
                "opt_out",
                title,
                NOT_AFFECTED,
                f"{where} {self.android} 기기에서도 기존처럼 시스템 바 바깥에 그려집니다. "
                "다만 문서는 이 방법을 임시 조치로 안내합니다." + caveat,
                clues + ([own.clue] if inherited else []) + [day.clue],
                specs,
                [
                    f"{self.device} 에뮬레이터에서 첫 화면 상단 콘텐츠가 상태바 아래로 들어가지 않는지 확인한다."
                ],
            )
            if self.opt_out_variants(theme_name):
                # Some configuration may lose the opt-out, so the checks that
                # assume edge-to-edge still run.
                return None
            return True
        if day.value is False:
            reason = (
                "opt-out 항목이 `false`로 설정되어 있어"
                + (f"(`{day.source}`에서 상속)" if inherited else "")
                + f" {android_name(EDGE_TO_EDGE_API)} 이상 기기에서 앱이 edge-to-edge로 그려집니다."
            )
            extra = [day.clue]
        else:
            reason = (
                f"`{theme_name}` 스타일과 그 부모 스타일에 opt-out 항목이 없어 "
                f"{android_name(EDGE_TO_EDGE_API)} 이상 기기에서 앱이 edge-to-edge로 그려집니다."
            )
            extra = []
        self.add(
            "opt_out",
            title,
            AFFECTED,
            reason,
            clues + [own.clue] + extra,
            [E["edge_default"]],
            [
                f"{self.device} 에뮬레이터에서 앱 화면이 상태바·내비게이션 바 뒤까지 그려지는지 확인한다."
            ],
        )
        return False

    MAX_CONFIGS = 256

    def variant_configs(self, unmodeled: set[str]) -> tuple[list[dict] | None, int]:
        """Every device configuration other than the default that the
        supplied qualifier values can produce on a device that runs
        `self.api`, smallest first, with the number of combinations. The list
        is None when the combinations exceed MAX_CONFIGS."""
        inp = self.inputs
        values: dict[str, set] = {}
        for q in {s.qualifier for s in inp.styles} - unmodeled:
            for kind, value in qualifier_parts(q).items():
                if kind == "version":
                    continue  # every configuration runs the audited device API
                values.setdefault(kind, set()).add(value)
        kinds = sorted(values)

        def options(kind: str) -> list:
            # A device is always in day or night mode, so both are checked
            # whenever any directory uses the night qualifier, even when
            # only values-notnight is supplied. Other kinds may be unset.
            if kind == "night":
                return ["notnight", "night"]
            return [None, *sorted(values[kind], key=str)]

        combos = 1
        for kind in kinds:
            combos *= len(options(kind))
        if combos > self.MAX_CONFIGS:
            return None, combos
        default = device_config("values", self.api)
        configs = [dict(default)]
        for kind in kinds:
            configs = [
                c | ({kind: v} if v is not None else {})
                for c in configs
                for v in options(kind)
            ]
        normalized: list[dict] = []
        for c in configs:
            c = normalize_config(c, set(kinds))
            if c != default and c not in normalized:
                normalized.append(c)
        return sorted(normalized, key=len), combos

    def opt_out_variants(self, theme_name: str) -> bool:
        """Check the other device configurations the supplied resources can produce.

        The default result covers a day-mode device that runs `self.api`. Android resolves
        each style in the chain separately, so qualified variants of different
        ancestors can combine (values-en/NormalTheme with values-night/Base
        gives an English night-mode result neither directory shows alone).
        Every combination of the supplied qualifier values is resolved; only
        the smallest configurations that lose the opt-out are reported.
        """
        inp = self.inputs
        before = len(self.findings)
        unchecked = unchecked_qualifiers({s.qualifier for s in inp.styles})
        unmodeled = sorted(unchecked)
        if unmodeled:
            kinds_text = ", ".join(
                sorted({k for reasons in unchecked.values() for k in reasons})
            )
            self.add(
                "opt_out_variant",
                "정확히 판단하지 않는 리소스 한정자",
                NEEDS_CHECK,
                f"제공된 리소스에 이 도구가 Android 선택 규칙을 정확히 따라가지 않는 {josa(f'한정자({kinds_text})', '이/가')} 있습니다: "
                + ", ".join(f"`{q}`" for q in unmodeled)
                + ". 이 디렉터리의 스타일이 opt-out 판단에 영향을 주는지는 확인하지 않았습니다.",
                [s.clue for s in inp.styles if s.qualifier in unmodeled][:5],
                tests=[
                    f"해당 한정자에 맞는 {self.android} 기기나 에뮬레이터 설정(화면 밀도, 언어)에서 첫 화면 상단을 확인한다."
                ],
                check="이 디렉터리들의 스타일에서도 opt-out이 유지되는지 직접 확인하세요.",
            )
        configs, combos = self.variant_configs(set(unmodeled))
        if configs is None:
            self.add(
                "opt_out_variant",
                "다른 기기 설정의 opt-out",
                NEEDS_CHECK,
                f"제공된 리소스 한정자 조합이 {combos}개라서 모두 확인하지 않았습니다. "
                "기본 설정에서는 opt-out이 적용됩니다.",
                check="언어·다크 모드·화면 크기 등 한정자별로 opt-out이 유지되는지 직접 확인하세요.",
            )
            return True
        reported: list[tuple[dict, tuple]] = []

        for config in configs:
            result = resolve_opt_out(inp.styles, theme_name, config)
            if result is None or result.value:
                continue
            outcome = (
                tuple((s.qualifier, s.name) for s in result.styles),
                result.value,
                result.unresolved_value,
                result.missing_parent,
            )
            if any(o == outcome and covers(c, config) for c, o in reported):
                continue  # a smaller configuration with the same style chain already shows this
            reported.append((config, outcome))
            name = config_name(config)
            if result.unresolved_value:
                detail = f"opt-out 항목 값이 `{result.unresolved_value}`라서 직접 확인할 수 없습니다"
            elif result.value is False:
                detail = (
                    f"`{result.source}` 스타일이 opt-out 항목을 `false`로 덮어씁니다"
                )
            elif result.missing_parent:
                detail = f"부모인 `{result.missing_parent}` 스타일이 입력에 없어 확인할 수 없습니다"
            else:
                detail = "opt-out 항목이 없습니다"
            used = " → ".join(f"{s.qualifier}/{s.name}" for s in result.styles)
            clues = [s.clue for s in result.styles] + (
                [result.clue] if result.clue else []
            )
            if config.get("night") == "night":
                self.add(
                    "opt_out_night",
                    "다크 모드 스타일의 opt-out",
                    NEEDS_CHECK,
                    f"`{name}` 설정에서 Android가 고르는 {josa(f'스타일 체인({used})', '을/를')} 따라가면 {detail}. "
                    f"{self.tgt_label} 시점 문서는 다크 모드 스타일을 언급하지 않았고, 이후 문서에서 같은 항목을 넣으라는 안내가 추가됐습니다.",
                    clues,
                    [E["opt_out_night"]],
                    [
                        f"기기를 다크 모드로 바꾸고 {self.android} 에뮬레이터에서 첫 화면 상단을 다시 확인한다."
                    ],
                    check="다크 모드에서도 opt-out이 필요한지 확인하세요.",
                )
            else:
                self.add(
                    "opt_out_variant",
                    f"`{name}` 설정의 opt-out",
                    NEEDS_CHECK,
                    f"기본 설정에서는 opt-out이 적용되지만, `{name}` 설정에서 Android가 고르는 "
                    f"{josa(f'스타일 체인({used})', '을/를')} 따라가면 {detail}. "
                    f"{self.tgt_label} 문서는 이런 리소스 변형을 다루지 않으므로 기기에서 직접 확인해야 합니다.",
                    clues,
                    tests=[
                        f"{self.android} 에뮬레이터를 `{name}`에 해당하는 설정으로 바꾸고 첫 화면 상단을 다시 확인한다."
                    ],
                    check=f"`{name}` 설정에서도 opt-out이 필요한지 확인하세요.",
                )
        return len(self.findings) > before

    def ui_mode(self) -> None:
        inp = self.inputs
        title = "SystemUiMode 사용"
        if not inp.dart_provided:
            self.add(
                "ui_mode",
                title,
                NEEDS_CHECK,
                "Dart 코드를 받지 못했습니다.",
                specs=[E["unset_mode"]],
                check="앱에서 SystemChrome.setEnabledSystemUIMode 호출을 찾아 함께 넣어 주세요.",
            )
            return
        modes = {}
        for mode, clue in inp.ui_modes:
            modes.setdefault(mode, []).append(clue)
        if not modes:
            self.add(
                "ui_mode",
                title,
                NEEDS_CHECK,
                "제공된 코드에 setEnabledSystemUIMode 호출이 없습니다. 호출이 없는 앱도 기본 동작이 edge-to-edge로 바뀝니다.",
                specs=[E["unset_mode"]],
                check="앱 전체에서 setEnabledSystemUIMode 호출 여부를 확인하세요.",
            )
            return
        for mode, clues in modes.items():
            if mode == "edgeToEdge":
                self.add(
                    f"ui_mode_{mode}",
                    f"{title}: edgeToEdge",
                    NOT_AFFECTED,
                    "이미 SystemUiMode.edgeToEdge를 직접 켜고 있어 문서상 마이그레이션이 끝난 앱입니다.",
                    clues,
                    [E["already_migrated"]],
                )
            else:
                self.mode_finding(f"{title}: {mode}", mode, clues)

    def mode_finding(self, title: str, mode: str, clues: list[Clue]) -> None:
        self.add(
            f"ui_mode_{mode}",
            title,
            AFFECTED,
            f"SystemUiMode.{mode} 모드는 targetSdk {EDGE_TO_EDGE_API} 이상에서 opt-out 없이는 동작하지 않습니다.",
            clues,
            [mode_spec(mode)],
            [
                f"{self.device} 에뮬레이터에서 {mode} 모드를 켜는 화면에 들어가 상태바·내비게이션 바가 문서대로 숨는지 확인한다."
            ],
        )

    def layout(self) -> None:
        inp = self.inputs
        title = "시스템 바 영역 레이아웃"
        if not inp.dart_provided:
            self.add(
                "layout",
                title,
                NEEDS_CHECK,
                "Dart 코드를 받지 못했습니다.",
                specs=[E["edge_api"]],
                check="첫 화면의 Scaffold와 SafeArea 사용 부분을 넣어 주세요.",
            )
            return
        if any(m == "edgeToEdge" for m, _ in inp.ui_modes):
            self.add(
                "layout",
                title,
                NOT_AFFECTED,
                "이미 edge-to-edge를 직접 켜고 있어 이번 변경으로 레이아웃이 달라지지 않습니다.",
                [c for m, c in inp.ui_modes if m == "edgeToEdge"],
                [E["already_migrated"]],
            )
            return
        tests = [
            f"{self.device} 에뮬레이터에서 화면 맨 위 텍스트·버튼이 상태바와 겹치지 않는지, "
            "맨 아래 버튼이 내비게이션 바(3버튼·제스처 모두)와 겹치지 않는지 확인한다."
        ]
        if inp.safe_areas:
            self.add(
                "layout",
                title,
                NOT_AFFECTED,
                "제공된 화면은 SafeArea로 시스템 바 영역을 피하고 있습니다. 다른 화면은 확인하지 않았습니다.",
                inp.safe_areas,
                [E["safe_area"]],
                tests,
            )
        elif inp.app_bars:
            self.add(
                "layout",
                title,
                NEEDS_CHECK,
                "AppBar가 상단을 상태바 높이만큼 띄우지만, 하단 내비게이션 바 쪽 처리는 제공된 코드에서 보이지 않습니다.",
                inp.app_bars,
                [E["app_bar_primary"], E["edge_api"]],
                tests,
                check="화면 하단에 버튼이나 목록 끝이 있는지 확인하세요.",
            )
        elif inp.scaffolds:
            self.add(
                "layout",
                title,
                AFFECTED,
                "Scaffold 본문을 SafeArea나 AppBar 없이 그리고 있어, edge-to-edge가 되면 상단 콘텐츠가 상태바 뒤로 들어갑니다.",
                inp.scaffolds,
                [E["edge_api"], E["safe_area"], E["safe_area_scaffold"]],
                tests,
            )
        else:
            self.add(
                "layout",
                title,
                NEEDS_CHECK,
                "제공된 코드에서 화면 구조(Scaffold, SafeArea, AppBar)를 찾지 못했습니다.",
                specs=[E["edge_api"]],
                tests=tests,
                check="첫 화면의 build 메서드를 넣어 주세요.",
            )

    def overlay_colors(self) -> None:
        if not self.inputs.overlay_colors:
            return
        self.add(
            "overlay_colors",
            "상태바·내비게이션 바 색상 지정",
            NEEDS_CHECK,
            f"시스템 바 색상을 직접 지정하고 있습니다. {self.tgt_label} 문서에는 edge-to-edge에서 이 색상이 어떻게 적용되는지 적혀 있지 않습니다.",
            self.inputs.overlay_colors,
            [E["overlay_color_edge"]],
            [
                f"{self.device} 에뮬레이터에서 지정한 색상이 상태바·내비게이션 바에 그대로 보이는지 확인한다."
            ],
            check="문서로 판단할 수 없어 기기에서 직접 확인해야 합니다.",
        )
        f = self.findings[-1]
        # Absence of evidence is the point here; do not list it as a failure.
        f.missing_evidence.clear()

    @property
    def cur_label(self) -> str:
        return self.cur.label

    @property
    def tgt_label(self) -> str:
        return self.tgt.label

    @property
    def api(self) -> int:
        """API level of the device the audit checks: the target's default."""
        return self.tgt.default_target_sdk

    @property
    def android(self) -> str:
        return android_name(self.api)

    @property
    def device(self) -> str:
        return f"{self.android}(API {self.api})"

    def launch_theme(self) -> None:
        """Report a configuration where the launch theme's opt-out differs
        from the app theme's: the launch screen then draws differently from
        the app screen."""
        inp = self.inputs
        if not (inp.normal_theme and inp.launch_theme and inp.styles_provided):
            return
        (normal_name, normal_clue), (launch_name, launch_clue) = (
            inp.normal_theme,
            inp.launch_theme,
        )
        if normal_name == launch_name:
            return
        unchecked = set(unchecked_qualifiers({s.qualifier for s in inp.styles}))
        variants, combos = self.variant_configs(unchecked)
        configs: list[tuple[str | None, str | dict]] = [(None, "values")]
        configs += [(config_name(c), c) for c in variants or []]

        def compare(config):
            """Both resolutions when both are known, else None."""
            normal = resolve_opt_out(inp.styles, normal_name, config, self.api)
            launch = resolve_opt_out(inp.styles, launch_name, config, self.api)
            if normal is None or launch is None:
                return None
            if any(r.unresolved_value or r.missing_parent for r in (normal, launch)):
                return None
            return normal, launch

        found = None
        for label, config in configs:
            pair = compare(config)
            if pair and self.launch_differs(bool(pair[0].value), bool(pair[1].value)):
                found = (label, *pair)
                break
        if found is None:
            # Other configurations were not compared; say so only when the
            # default was compared and showed nothing.
            if variants is None and compare("values") is not None:
                self.launch_unchecked(
                    launch_name, normal_name, combos, [launch_clue, normal_clue]
                )
            return
        label, normal, launch = found
        where = "기본 설정에서" if label is None else f"`{label}` 설정에서"
        reason, specs, check = self.launch_message(
            where, normal_name, launch_name, bool(launch.value)
        )
        if self.conditional:
            n = self.tgt.default_target_sdk
            reason = f"targetSdk가 {josa(n, '이/가')} 된다면: " + reason
        clues = [launch_clue, normal_clue]
        clues += [s.clue for r in (launch, normal) for s in r.styles]
        clues += [r.clue for r in (launch, normal) if r.clue]
        self.add(
            "launch_theme",
            "실행 화면 테마의 opt-out",
            NEEDS_CHECK,
            reason,
            list(dict.fromkeys(clues)),
            specs,
            [
                f"{self.device} 에뮬레이터에서 앱을 처음 실행해 실행 화면과 첫 화면의 상태바 영역을 비교한다."
            ],
            check=check,
        )

    def launch_differs(self, normal: bool, launch: bool) -> bool:
        return normal != launch

    def launch_unchecked(
        self, launch_name: str, normal_name: str, combos: int, clues: list[Clue]
    ) -> None:
        prefix = (
            f"targetSdk가 {josa(self.tgt.default_target_sdk, '이/가')} 된다면: "
            if self.conditional
            else ""
        )
        self.add(
            "launch_theme",
            "실행 화면 테마의 opt-out",
            NEEDS_CHECK,
            f"{prefix}기본 설정에서는 실행 화면의 `{launch_name}` 스타일과 앱 화면의 `{normal_name}` 스타일 사이에 "
            f"알릴 차이가 없습니다. 하지만 리소스 한정자 조합이 {combos}개라서 다른 기기 설정은 비교하지 않았습니다.",
            clues,
            self.launch_specs,
            check=self.launch_unchecked_check,
        )

    @property
    def launch_specs(self) -> list[Spec]:
        return [E["launch_switch"]]

    launch_unchecked_check = (
        "다크 모드 등 다른 설정의 두 스타일에서 opt-out 항목이 같은지 직접 확인하세요."
    )

    def launch_message(
        self, where: str, normal_name: str, launch_name: str, launch_opted: bool
    ) -> tuple[str, list[Spec], str]:
        has, lacks = (
            (launch_name, normal_name) if launch_opted else (normal_name, launch_name)
        )
        return (
            f"{self.device} 기기의 {where} `{has}` 스타일에는 opt-out 항목이 있지만 "
            f"`{lacks}` 스타일에는 없습니다. 실행 화면은 `{launch_name}` 스타일로 그려지고, "
            f"실행 화면이 사라진 뒤 Flutter가 `{normal_name}` 스타일로 바꿉니다. "
            "그래서 실행 화면과 앱 화면이 시스템 바를 다르게 처리할 수 있습니다.",
            self.launch_specs,
            "실행 화면도 앱 화면과 같게 그리려면 두 스타일의 opt-out 항목을 맞추세요.",
        )

    def run(self) -> None:
        if not self.target_sdk():
            return
        opted = self.opt_out()
        self.launch_theme()
        if opted:
            return
        self.ui_mode()
        self.layout()
        self.overlay_colors()


class Android16Auditor(Auditor):
    """Rules for an upgrade that moves the default targetSdk from 35 to 36.

    Only Android 16 devices behave differently: Android 15 and earlier
    devices treat targetSdk 35 and 36 the same. So the opt-out is read on an
    API 36 device. Before the upgrade it still applied there; after it,
    Android 16 ignores it. An app whose API 36 style has no opt-out already
    drew edge-to-edge on Android 16 and does not change. For an app that
    loses the opt-out, the checks that assume edge-to-edge run, and the item
    is reported because the later docs warn that it may crash the app.
    """

    already_state = "Android 16 기기에서 opt-out이 무시되던 상태입니다."

    @property
    def launch_specs(self) -> list[Spec]:
        return [A16["opt_out_ignored"], E["launch_switch"]]

    launch_unchecked_check = (
        "다크 모드 등 다른 설정에서 실행 화면 스타일에만 opt-out 항목이 있는지 직접 확인하세요. "
        "있다면 targetSdk 36에서는 그 opt-out이 무시되어 실행 화면이 edge-to-edge로 바뀝니다."
    )

    def launch_differs(self, normal: bool, launch: bool) -> bool:
        # After the upgrade Android 16 ignores both opt-outs. The launch
        # screen changes only when its own theme opts out; the app theme's
        # loss is the opt_out finding.
        return launch and not normal

    def launch_message(
        self, where: str, normal_name: str, launch_name: str, launch_opted: bool
    ) -> tuple[str, list[Spec], str]:
        return (
            f"{self.device} 기기의 {where} 실행 화면에 쓰이는 `{launch_name}` 스타일에는 "
            f"opt-out 항목이 있지만, 앱 화면의 `{normal_name}` 스타일에는 없습니다. "
            f"targetSdk가 {josa(self.api, '이/가')} 되면 Android 16 기기에서는 이 opt-out이 무시되어, "
            "실행 화면도 앱 화면처럼 edge-to-edge로 그려집니다.",
            self.launch_specs,
            "실행 화면이 상태바·내비게이션 바 뒤까지 그려져도 괜찮은지 확인하세요.",
        )

    @property
    def target_default_spec(self) -> Spec:
        return A16["target_default"]

    @property
    def already_spec(self) -> Spec:
        return A16["opt_out_ignored"]

    def opt_out(self) -> bool | None:
        """Return True if the upgrade leaves the app as it was (stop), False
        if Android 16 changes it, None if unknown."""
        day = self.opt_out_state(self.api)
        theme_name, clues = self.theme()
        if theme_name is None:
            return None
        unchecked = set(unchecked_qualifiers({s.qualifier for s in self.inputs.styles}))
        configs, combos = self.variant_configs(unchecked)
        opted: dict[tuple, tuple[list[dict], OptOutResolution]] = {}
        unknown: dict[tuple, tuple[list[dict], OptOutResolution]] = {}
        for config in configs or []:
            result = resolve_opt_out(self.inputs.styles, theme_name, config)
            if result is None:
                continue
            if result.value:
                groups = opted
            elif result.unresolved_value or result.missing_parent:
                groups = unknown
            else:
                continue
            chain = (
                tuple((s.qualifier, s.name) for s in result.styles),
                result.unresolved_value,
                result.missing_parent,
            )
            seen, _ = groups.setdefault(chain, ([], result))
            if not any(covers(c, config) for c in seen):
                seen.append(
                    config
                )  # a smaller configuration may show this chain already
        if day is None:
            # The default stays "needs check"; a configuration known to opt
            # out is still reported.
            if opted:
                self.lost_opt_out(
                    [([config_name(c) for c in cs], r) for cs, r in opted.values()],
                    theme_name,
                    clues,
                    key="opt_out_variant",
                )
                return False
            return None
        if day.value or opted:
            default_chain = tuple((s.qualifier, s.name) for s in day.styles)
            groups: list[tuple[list[str] | None, OptOutResolution]] = (
                [(None, day)] if day.value else []
            )
            groups += [
                ([config_name(c) for c in cs], r)
                for (chain, _, _), (cs, r) in opted.items()
                if not (day.value and chain == default_chain)
            ]
            self.lost_opt_out(groups, theme_name, clues)
            return False
        own = day.styles[0]
        used = " → ".join(f"{s.qualifier}/{s.name}" for s in day.styles)
        default = (
            f"{self.device} 기기의 기본 설정이 고르는 스타일({used})에서 opt-out 항목이 `false`로 설정되어 있어"
            if day.value is False
            else f"{self.device} 기기의 기본 설정이 고르는 스타일({used})에 opt-out 항목이 없어"
        )
        default_clues = clues + [own.clue] + ([day.clue] if day.value is False else [])
        open_parts: list[str] = []
        open_clues: list[Clue] = []
        if configs is None:
            open_parts.append(
                f"리소스 한정자 조합이 {combos}개라서 다른 기기 설정은 확인하지 않았습니다."
            )
        for cs, r in unknown.values():
            names = ", ".join(f"`{config_name(c)}`" for c in cs)
            if r.unresolved_value:
                open_parts.append(
                    f"{names} 설정의 스타일은 opt-out 항목 값이 `{r.unresolved_value}` 리소스라서 확인할 수 없습니다."
                )
            else:
                open_parts.append(
                    f"{names} 설정의 스타일은 부모인 `{r.missing_parent}` 스타일이 입력에 없어 확인할 수 없습니다."
                )
            open_clues += [s.clue for s in r.styles] + ([r.clue] if r.clue else [])
        caveat, unchecked_clues = self.unchecked_caveat()
        if open_parts or caveat:
            self.add(
                "opt_out",
                OPT_OUT_TITLE,
                NEEDS_CHECK,
                " ".join(
                    part
                    for part in [
                        f"{default} 이 설정은 업그레이드 전부터 edge-to-edge로 그려지고 있었습니다.",
                        *open_parts,
                        caveat.strip(),
                        "확인하지 못한 설정에서 opt-out이 적용된다면, 그 설정의 Android 16 기기에서는 "
                        f"targetSdk가 {josa(self.api, '이/가')} 된 뒤 opt-out이 무시됩니다.",
                    ]
                    if part
                ),
                default_clues + open_clues + unchecked_clues,
                [A16["opt_out_ignored"]],
                [
                    f"해당 설정의 {self.device} 에뮬레이터에서 첫 화면 상단이 상태바 뒤로 들어가는지 확인한다."
                ],
                check="확인하지 못한 설정의 스타일에서 opt-out 항목 값을 직접 확인하세요.",
            )
            return None
        others = (
            " 입력에 있는 다른 기기 설정(다크 모드 등)에도 opt-out 항목이 없습니다."
            if configs
            else ""
        )
        self.add(
            "opt_out",
            OPT_OUT_TITLE,
            NOT_AFFECTED,
            f"{default} 업그레이드 전(targetSdk {EDGE_TO_EDGE_API})부터 Android 16 기기에서도 "
            f"앱이 edge-to-edge로 그려지고 있었습니다.{others} 이번 업그레이드로 바뀌는 것은 없습니다.",
            default_clues,
            [E["edge_default"]],
        )
        self.notes.append(
            "업그레이드 전부터 edge-to-edge였으므로 나머지 항목은 이번 업그레이드의 영향으로 보지 않았습니다."
        )
        return True

    def lost_opt_out(
        self,
        groups: list[tuple[list[str] | None, OptOutResolution]],
        theme_name: str,
        clues: list[Clue],
        key: str = "opt_out",
    ) -> None:
        """Report an opt-out that Android 16 devices apply now and ignore
        after the upgrade. Each group is a style chain that opts out, with the
        device configurations that select it (None for the default)."""
        chain_clues = list(
            dict.fromkeys(
                c for _, r in groups for c in [*(s.clue for s in r.styles), r.clue] if c
            )
        )
        chains = [
            (names, " → ".join(f"{s.qualifier}/{s.name}" for s in r.styles), r)
            for names, r in groups
        ]
        names, used, result = chains[0]
        if names is None:
            own = result.styles[0]
            if result.source is not None and result.source != theme_name:
                where = (
                    f"{self.device} 기기가 고르는 `{own.qualifier}/{theme_name}` 스타일이 부모인 "
                    f"`{result.source}` 스타일에서 opt-out 항목을 상속받아 "
                )
            else:
                where = f"{self.device} 기기가 고르는 `{own.qualifier}/{theme_name}` 스타일에 opt-out 항목이 있어 "
            now = f"{where}지금은 Android 16 기기에서도 시스템 바 바깥에 그려집니다."
            if len(chains) > 1:
                now += (
                    " 다른 설정에서도 opt-out 항목이 있는 스타일 체인을 고릅니다: "
                    + ", ".join(
                        "·".join(f"`{n}`" for n in ns) + f"({u})"
                        for ns, u, _ in chains[1:]
                    )
                    + "."
                )
            test_where = f"{self.device} 에뮬레이터에서"
        else:
            listed = ", ".join(
                "·".join(f"`{n}`" for n in ns) + f"({u})" for ns, u, _ in chains
            )
            default = (
                "기본 설정은 확인하지 못했지만"
                if key != "opt_out"
                else "기본 설정에는 opt-out 항목이 없지만"
            )
            now = (
                f"{self.device} 기기의 {default}, 다음 설정에서 고르는 스타일 체인에는 "
                f"opt-out 항목이 있습니다: {listed}. 지금은 이 설정의 Android 16 기기에서도 시스템 바 바깥에 그려집니다."
            )
            test_where = (
                f"{self.device} 에뮬레이터를 해당 설정(다크 모드 등)으로 바꾸고"
            )
        self.add(
            key,
            OPT_OUT_TITLE if key == "opt_out" else "다른 기기 설정의 opt-out",
            AFFECTED,
            f"{now} targetSdk가 {josa(self.api, '이/가')} 되면 Android 16 기기에서는 "
            "opt-out이 무시되어 앱이 edge-to-edge로 그려집니다.",
            list(dict.fromkeys(clues + chain_clues)),
            [A16["opt_out_ignored"]],
            [
                f"{test_where} Flutter 3.32 빌드와 Flutter 3.35 빌드를 열어, "
                "앱 화면이 상태바·내비게이션 바 뒤까지 그려지는지 비교한다."
            ],
        )
        caveat, unchecked_clues = self.unchecked_caveat()
        listed = ", ".join(f"{u}(`{r.source}`)" for _, u, r in chains)
        self.add(
            "opt_out_android16",
            f"{android_name(self.api)} 기기의 opt-out 항목",
            NEEDS_CHECK,
            f"{self.device} 기기가 고르는 스타일 체인에 opt-out 항목이 남아 있습니다: {listed}. "
            "이후 문서는 Android 16 이상에서 이 방법으로 opt-out하면 앱이 크래시할 수 있고, "
            "버전별 리소스로 이를 피할 수 있다고 안내합니다. Android 16 기기에서만 이 항목을 빼려면 "
            "`values-v36`처럼 API 36 이상에 적용되는 디렉터리를 씁니다." + caveat,
            chain_clues + unchecked_clues,
            [A16["opt_out_crash"]],
            [
                f"{self.device} 에뮬레이터에서 앱을 실행해 첫 화면까지 크래시 없이 열리는지 확인한다."
            ],
            check="API 36 이상 기기에서 쓰이는 스타일에서 opt-out 항목을 빼는지 검토하세요.",
        )

    def unchecked_caveat(self) -> tuple[str, list[Clue]]:
        """A sentence naming the style directories this resolver does not
        judge, and their clues. Directories such as `values-35` (the name the
        later docs use) get the platform version qualifier format."""
        styles = self.inputs.styles
        unchecked = sorted(unchecked_qualifiers({s.qualifier for s in styles}))
        if not unchecked:
            return "", []
        caveat = (
            " 이 판단은 "
            + ", ".join(f"`{q}`" for q in unchecked)
            + " 디렉터리를 고려하지 않았습니다."
        )
        for q in unchecked:
            if m := re.fullmatch(r"values-(\d+)", q):
                caveat += (
                    f" 플랫폼 버전 한정자는 `values-v{m[1]}`처럼 `v`를 붙여 쓰므로, "
                    f"{josa(f'`{q}`', '은/는')} 버전별 리소스로 인식되지 않습니다. "
                    "`values-v35`는 API 35 이상 기기에, `values-v36`은 API 36 이상 기기에 적용됩니다."
                )
        return caveat, [s.clue for s in styles if s.qualifier in unchecked][:5]

    def mode_finding(self, title: str, mode: str, clues: list[Clue]) -> None:
        self.add(
            f"ui_mode_{mode}",
            title,
            AFFECTED,
            f"targetSdk {self.api}부터는 {android_name(self.api)} 기기에서 Android가 SystemUiMode.{mode} 값을 무시하고, "
            "opt-out으로도 되돌릴 수 없습니다.",
            clues,
            [mode_ignored_spec(mode), A16["modes_no_opt_out"]],
            [
                f"{self.device} 에뮬레이터에서 {mode} 모드를 켜는 화면에 들어가 상태바·내비게이션 바가 어떻게 보이는지 확인한다."
            ],
        )

    def overlay_colors(self) -> None:
        if not self.inputs.overlay_colors:
            return
        self.add(
            "overlay_colors",
            "상태바·내비게이션 바 색상 지정",
            AFFECTED,
            f"시스템 바 색상을 직접 지정하고 있습니다. targetSdk {self.api}부터는 opt-out할 수 없어 "
            f"{android_name(self.api)} 기기에서 statusBarColor와 systemNavigationBarColor가 동작하지 않습니다.",
            self.inputs.overlay_colors,
            [A16["overlay_color_api36"]],
            [
                f"{self.device} 에뮬레이터에서 지정한 색상이 상태바·내비게이션 바에 보이는지 확인한다."
            ],
        )


def covers(smaller: dict, larger: dict) -> bool:
    """Whether the configuration `larger` includes everything `smaller`
    selects, so a result for `larger` shows nothing new."""
    for k, v in smaller.items():
        if k not in larger:
            return False
        # Every configuration has a screen size, and the default is
        # `normal`, not the smallest; a smaller screen with the same
        # style chain shows nothing new either.
        if k == "size":
            continue
        if larger[k] != v and not (k in THRESHOLD_KINDS and larger[k] >= v):
            return False
    return True


def auditor_class(release: Release) -> type[Auditor]:
    if release.default_target_sdk > EDGE_TO_EDGE_API:
        return Android16Auditor
    return Auditor


def audit(current: str, target: str, inputs: AppInputs, index: Retriever) -> Report:
    cur, tgt = check_range(current, target)
    auditor = auditor_class(tgt)(cur, tgt, inputs, index)
    auditor.run()
    return Report(current, target, inputs.files, auditor.findings, auditor.notes)
