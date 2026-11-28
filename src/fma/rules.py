"""Audit rules for Android system bars and edge-to-edge across a Flutter upgrade.

Each rule reads app clues, picks a verdict, and names the doc evidence that
backs it. If the evidence cannot be found in the right version of the docs,
the verdict drops to "needs check": the audit does not state what the docs
do not say.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .evidence import Evidence, Spec, resolve
from .retrieval import Retriever
from .signals import (
    THRESHOLD_KINDS,
    AppInputs,
    Clue,
    config_name,
    device_config,
    normalize_config,
    qualifier_parts,
    resolve_opt_out,
    unchecked_qualifiers,
)
from .versions import EDGE_TO_EDGE_API, Release, android_name, check_range

AFFECTED, NOT_AFFECTED, NEEDS_CHECK = "affected", "not_affected", "needs_check"
LABELS = {
    AFFECTED: "영향 있음",
    NOT_AFFECTED: "영향 없음",
    NEEDS_CHECK: "추가 확인 필요",
}

BC = frozenset({"breaking-change"})
API = frozenset({"api"})
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
            finding.reason = (
                f"targetSdk가 {self.tgt.default_target_sdk}가 된다면: " + finding.reason
            )
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
                f"{where}. 기본값(flutter.targetSdkVersion)을 쓰면 {cur}에서 {tgt}로 바뀝니다.",
                specs=[E["target_default"]],
                check="android/app/build.gradle(.kts)의 targetSdk 값을 확인하세요.",
            )
            self.conditional = True
            return True
        if ts.uses_flutter_default:
            self.add(
                "target_sdk",
                title,
                AFFECTED,
                f"targetSdk가 flutter.targetSdkVersion을 따르므로 API {cur}에서 API {tgt}({android_name(tgt)})로 바뀝니다.",
                [ts.clue],
                [E["target_default"]],
                [compare],
            )
            return True
        if ts.explicit is not None and ts.explicit < EDGE_TO_EDGE_API:
            self.add(
                "target_sdk",
                title,
                NOT_AFFECTED,
                f"targetSdk를 {ts.explicit}로 직접 지정해서 이번 업그레이드로는 바뀌지 않습니다. "
                f"{EDGE_TO_EDGE_API}로 올리는 시점에 같은 영향이 생깁니다.",
                [ts.clue],
                [E["target_explicit"]],
            )
            self.notes.append(
                f"targetSdk가 {EDGE_TO_EDGE_API} 미만으로 고정되어 있어 시스템 바 관련 나머지 항목은 확인하지 않았습니다."
            )
            return False
        if ts.explicit is not None and ts.explicit == tgt:
            self.add(
                "target_sdk",
                title,
                NOT_AFFECTED,
                f"이미 targetSdk {tgt}를 직접 지정하고 있어 Flutter 버전과 관계없이 edge-to-edge가 적용되던 상태입니다. "
                "이번 업그레이드로 바뀌는 것은 없습니다.",
                [ts.clue],
                [E["edge_default"]],
            )
            self.notes.append(
                f"업그레이드 전부터 targetSdk {tgt}였으므로 나머지 항목은 이번 업그레이드의 영향으로 보지 않았습니다."
            )
            return False
        if ts.explicit is not None:
            self.add(
                "target_sdk",
                title,
                NEEDS_CHECK,
                f"targetSdk {ts.explicit}는 이번 구간 문서({self.tgt_label} 기준 {android_name(tgt)})가 다루지 않는 값입니다.",
                [ts.clue],
                check=f"{android_name(tgt + 1)} 이상을 대상으로 할 때의 동작은 이 구간 문서로 판단할 수 없습니다. "
                f"{android_name(tgt + 1)} 동작 변경 문서를 직접 확인하세요.",
            )
            return False
        self.add(
            "target_sdk",
            title,
            NEEDS_CHECK,
            f"targetSdk가 `{ts.raw}`로 설정되어 있어 실제 값을 알 수 없습니다.",
            [ts.clue],
            [E["target_default"]],
            check=f"`{ts.raw}`가 가리키는 값을 확인하세요. flutter.targetSdkVersion이면 {cur}→{tgt}로 바뀝니다.",
        )
        self.conditional = True
        return True

    def opt_out(self) -> bool | None:
        """Return True if opted out, False if not, None if unknown."""
        inp = self.inputs
        title = "edge-to-edge opt-out 설정"
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
        theme_name, theme_clue = inp.normal_theme or ("NormalTheme", None)
        clues = [theme_clue] if theme_clue else []
        day = resolve_opt_out(inp.styles, theme_name, "values", self.api)
        if day is None:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                f"앱이 쓰는 스타일 `{theme_name}`이 제공된 res/values/styles.xml에 없습니다.",
                clues,
                check=f"`{theme_name}` 스타일 정의를 찾아 opt-out 항목을 확인하세요.",
            )
            return None
        own = day.styles[0]  # the theme as Android selects it (may be values-v21 etc.)
        inherited = day.source is not None and day.source != theme_name
        if day.value:
            caveat = (
                ""
                if inp.manifest_provided
                else " (AndroidManifest.xml을 받지 못해 이 스타일이 실제로 쓰이는지는 확인하지 않았습니다.)"
            )
            where = (
                f"`{theme_name}`이 부모 스타일 `{day.source}`에서 opt-out 항목을 상속받아"
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
        if day.unresolved_value:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                f"`{day.source}`의 opt-out 항목 값이 `{day.unresolved_value}`라서 참인지 거짓인지 알 수 없습니다. "
                "이 항목이 있으면 부모 스타일의 값은 쓰이지 않습니다.",
                clues + [day.clue],
                [E["opt_out_works"]],
                check=f"`{day.unresolved_value}`가 가리키는 값(예: res/values/bools.xml)을 확인하세요.",
            )
            return None
        if day.missing_parent:
            self.add(
                "opt_out",
                title,
                NEEDS_CHECK,
                f"`{theme_name}`의 부모 스타일 `{day.missing_parent}`이 제공된 styles.xml에 없어, "
                "opt-out 항목을 상속받는지 확인할 수 없습니다.",
                clues + [own.clue],
                [E["opt_out_parent"]],
                check=f"`{day.missing_parent}` 스타일 정의가 들어 있는 styles.xml을 함께 넣어 주세요.",
            )
            return None
        if day.value is False:
            reason = (
                "opt-out 항목이 `false`로 설정되어 있어"
                + (f"(`{day.source}`에서 상속)" if inherited else "")
                + f" {android_name(EDGE_TO_EDGE_API)} 이상 기기에서 앱이 edge-to-edge로 그려집니다."
            )
            extra = [day.clue]
        else:
            reason = (
                f"`{theme_name}`과 그 부모 스타일에 opt-out 항목이 없어 "
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
                f"제공된 리소스에 이 도구가 Android 선택 규칙을 정확히 따라가지 않는 한정자({kinds_text})가 있습니다: "
                + ", ".join(f"`{q}`" for q in unmodeled)
                + ". 이 디렉터리의 스타일이 opt-out 판단에 영향을 주는지는 확인하지 않았습니다.",
                [s.clue for s in inp.styles if s.qualifier in unmodeled][:5],
                tests=[
                    f"해당 한정자에 맞는 {self.android} 기기나 에뮬레이터 설정(화면 밀도, 언어)에서 첫 화면 상단을 확인한다."
                ],
                check="이 디렉터리들의 스타일에서도 opt-out이 유지되는지 직접 확인하세요.",
            )
        values: dict[str, set] = {}
        for q in {s.qualifier for s in inp.styles} - set(unmodeled):
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
            self.add(
                "opt_out_variant",
                "다른 기기 설정의 opt-out",
                NEEDS_CHECK,
                f"제공된 리소스 한정자 조합이 {combos}개라서 모두 확인하지 않았습니다. "
                "기본 설정에서는 opt-out이 적용됩니다.",
                check="언어·다크 모드·화면 크기 등 한정자별로 opt-out이 유지되는지 직접 확인하세요.",
            )
            return True
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
        configs = sorted(normalized, key=len)
        reported: list[tuple[dict, tuple]] = []

        def covers(smaller: dict, larger: dict) -> bool:
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
                detail = f"`{result.source}`가 opt-out 항목을 `false`로 덮어씁니다"
            elif result.missing_parent:
                detail = f"부모 스타일 `{result.missing_parent}`이 입력에 없어 확인할 수 없습니다"
            else:
                detail = "적용되는 스타일 체인에 opt-out 항목이 없습니다"
            used = " → ".join(f"{s.qualifier}/{s.name}" for s in result.styles)
            clues = [s.clue for s in result.styles] + (
                [result.clue] if result.clue else []
            )
            if config.get("night") == "night":
                self.add(
                    "opt_out_night",
                    "다크 모드 스타일의 opt-out",
                    NEEDS_CHECK,
                    f"`{name}` 설정에서 Android가 고르는 스타일 체인({used})에서 {detail}. "
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
                    f"기본 설정에서는 opt-out이 적용되지만, `{name}` 설정에서 Android가 고르는 스타일 체인({used})에서 {detail}. "
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
                self.add(
                    f"ui_mode_{mode}",
                    f"{title}: {mode}",
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

    def run(self) -> None:
        if not self.target_sdk():
            return
        opted = self.opt_out()
        if opted:
            return
        self.ui_mode()
        self.layout()
        self.overlay_colors()


def audit(current: str, target: str, inputs: AppInputs, index: Retriever) -> Report:
    cur, tgt = check_range(current, target)
    auditor = Auditor(cur, tgt, inputs, index)
    auditor.run()
    return Report(current, target, inputs.files, auditor.findings, auditor.notes)
