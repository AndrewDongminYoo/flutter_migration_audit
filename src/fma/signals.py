"""Read clues from the settings and code snippets the user provides.

Inputs are snippets, not a full project. Every reader records where a clue
came from (file and line) so the report can point back to it, and records
which inputs were missing so a rule can stop instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

OPT_OUT_ATTR = "android:windowOptOutEdgeToEdgeEnforcement"


@dataclass(frozen=True)
class Clue:
    file: str
    line: int
    text: str

    def render(self) -> str:
        return f"{self.file}:{self.line}  {self.text.strip()}"


@dataclass
class TargetSdk:
    raw: str
    clue: Clue

    @property
    def uses_flutter_default(self) -> bool:
        return self.raw == "flutter.targetSdkVersion"

    @property
    def explicit(self) -> int | None:
        return int(self.raw) if self.raw.isdigit() else None


@dataclass
class Style:
    name: str
    qualifier: str  # resource directory, e.g. "values" or "values-night"
    opt_out: Clue | None  # the opt-out item, whatever its value
    clue: Clue
    opt_out_value: bool | None = None  # None if absent or not a literal
    opt_out_raw: str | None = None  # the item's text, e.g. "true" or "@bool/x"
    # Value of the `parent` attribute, if any: "NormalBase" for a local style,
    # "@android:style/..." for a framework style.
    parent: str | None = None


@dataclass
class OptOutResolution:
    value: bool | None  # True/False if some style in the chain sets the item
    clue: Clue | None  # where the deciding item is
    source: str | None  # name of the style that sets it
    chain: list[str]  # styles visited, starting with the requested one
    missing_parent: str | None = None  # a local parent that was not provided
    # The deciding item is not a literal (for example `@bool/x`), so its
    # value is unknown. It still stops inheritance, as in Android.
    unresolved_value: str | None = None
    styles: list[Style] = field(default_factory=list)  # resolved styles, in chain order


def implicit_parent(style: Style) -> str | None:
    """Android rule: an explicit `parent` attribute wins; otherwise a dotted
    name (`NormalTheme.Video`) inherits from its prefix (`NormalTheme`)."""
    if style.parent is not None:
        if style.parent.startswith("@android:") or style.parent.startswith("android:"):
            return None  # framework style: not in the app's resources
        return style.parent.removeprefix("@style/")
    if "." in style.name:
        return style.name.rsplit(".", 1)[0]
    return None


# Android resource qualifiers in precedence order. A resource directory's
# qualifiers must all match the device configuration; among the matching
# directories, Android eliminates candidates one qualifier type at a time in
# this order.
# https://developer.android.com/guide/topics/resources/providing-resources#BestMatch
QUALIFIER_KINDS: list[tuple[str, re.Pattern]] = [
    (kind, re.compile(pattern))
    for kind, pattern in [
        ("mcc", r"mcc\d+"),
        ("mnc", r"mnc\d+"),
        ("layoutdir", r"ldrtl|ldltr"),
        ("sw", r"sw\d+dp"),
        ("w", r"w\d+dp"),
        ("h", r"h\d+dp"),
        ("size", r"small|normal|large|xlarge"),
        ("long", r"long|notlong"),
        ("round", r"round|notround"),
        ("gamut", r"widecg|nowidecg"),
        ("hdr", r"highdr|lowdr"),
        ("orientation", r"port|land"),
        ("uimode", r"car|desk|television|appliance|watch|vrheadset"),
        ("night", r"night|notnight"),
        ("density", r"ldpi|mdpi|hdpi|xhdpi|xxhdpi|xxxhdpi|nodpi|tvdpi|anydpi|\d+dpi"),
        ("touch", r"notouch|finger"),
        ("keys", r"keysexposed|keyshidden|keyssoft"),
        ("input", r"nokeys|qwerty|12key"),
        ("navexp", r"navexposed|navhidden"),
        ("nav", r"nonav|dpad|trackball|wheel"),
        ("version", r"v\d+"),
        ("locale", r"[a-z]{2,3}|r[A-Z]{2}|b\+[\w+]+"),
    ]
]
PRECEDENCE = [
    "mcc",
    "mnc",
    "locale",
    "layoutdir",
    "sw",
    "w",
    "h",
    "size",
    "long",
    "round",
    "gamut",
    "hdr",
    "orientation",
    "uimode",
    "night",
    "density",
    "touch",
    "keys",
    "input",
    "navexp",
    "nav",
    "version",
]
# Default device API for a configuration. The audit passes the API of the
# device it checks; directories for later versions (values-v36 on an API 35
# device) never apply.
DEVICE_API = 35


# Qualifiers that name a minimum value: a directory applies when the device
# value is at least this, and the largest such threshold wins. Screen size
# behaves the same way: a device falls back to resources for smaller sizes.
THRESHOLD_KINDS = {"version", "sw", "w", "h", "size"}
SCREEN_SIZES = {"small": 1, "normal": 2, "large": 3, "xlarge": 4}
SCREEN_SIZE_NAMES = {v: k for k, v in SCREEN_SIZES.items()}
# The default configuration is an ordinary phone. Android treats a resource
# without a size as `normal` on a device that is at least `normal`, so there
# values beats values-small (ResTable_config::isBetterThan in AOSP's
# ResourceTypes.cpp).
NORMAL_SIZE = SCREEN_SIZES["normal"]


def canonical_locale(value: str) -> str:
    """Bring `b+en+US` and `en-rUS` to one form (`en-rUS`); a script is kept
    as its own part (`b+zh+Hant+TW` becomes `zh-Hant-rTW`). A tag with other
    subtags, such as a variant (`b+en+US+POSIX`), is returned unchanged: this
    resolver does not compare them, and the tag must stay distinct."""
    if not value.startswith("b+"):
        return value
    lang, script, region = "", None, None
    for i, sub in enumerate(value[2:].split("+")):
        if i == 0:
            lang = sub.lower()
        elif i == 1 and len(sub) == 4 and sub.isalpha():
            script = sub.title()
        elif region is None and (
            (len(sub) == 2 and sub.isalpha()) or (len(sub) == 3 and sub.isdigit())
        ):
            region = sub.upper()
        else:
            return value
    return "-".join(
        [lang] + ([script] if script else []) + ([f"r{region}"] if region else [])
    )


def locale_parts(value: str) -> tuple[str, str | None, str | None]:
    """Split a canonical locale into (language, script, region)."""
    lang, *rest = value.split("-")
    # Scripts are title case (`Hant`); regions carry a lowercase `r` (`r419`).
    script = next((s for s in rest if len(s) == 4 and s[0].isupper()), None)
    region = next((s[1:] for s in rest if s.startswith("r") and len(s) > 1), None)
    return lang, script, region


def locale_qualifier(value: str) -> str:
    """Render a canonical locale as a directory qualifier. The legacy form
    (`en-rUS`) has no script and only two-letter regions; anything else is
    written in BCP-47 form (`b+es+419`)."""
    lang, script, region = locale_parts(value)
    if script is None and (region is None or region.isalpha()):
        return value
    return "+".join(["b", lang, *(x for x in (script, region) if x)])


def qualifier_parts(qualifier: str) -> dict[str, str | int]:
    """Parse `values-zh-rCN-night-v35` into {"locale": "zh-rCN", "night": "night", "version": 35}."""
    parts: dict[str, str | int] = {}
    for token in qualifier.split("-")[1:]:
        for kind, pattern in QUALIFIER_KINDS:
            if pattern.fullmatch(token):
                if kind == "size":
                    parts[kind] = SCREEN_SIZES[token]
                elif kind in THRESHOLD_KINDS:
                    parts[kind] = int(re.sub(r"\D", "", token))
                elif kind == "locale" and "locale" in parts:
                    parts[kind] = f"{parts[kind]}-{token}"
                else:
                    parts[kind] = token
                break
        else:
            parts[f"unknown:{token}"] = token
    if isinstance(parts.get("locale"), str):
        parts["locale"] = canonical_locale(parts["locale"])
    return parts


# Qualifiers whose Android matching this resolver does not model. Density
# picks the closest bucket, prefers scaling a higher density down, and
# treats nodpi and anydpi specially. Directories using them are reported as
# unchecked instead. See docs/resource-qualifiers.md.
UNMODELED_KINDS = {"density"}


def unmodeled_qualifiers(qualifier: str) -> set[str]:
    out = set()
    for kind, value in qualifier_parts(qualifier).items():
        if kind in UNMODELED_KINDS:
            out.add(kind)
        elif kind == "locale" and str(value).startswith("b+"):
            # Left unchanged by canonical_locale: a variant or other subtag.
            out.add("BCP-47 variant")
        elif kind == "locale" and locale_parts(str(value))[1] is not None:
            # Android infers a script for every device locale (zh-TW is
            # Hant); without that inference the match would be a guess.
            out.add("BCP-47 script")
        elif kind.startswith("unknown:"):
            out.add(f"알 수 없는 한정자 {value}")
    return out


def unchecked_qualifiers(qualifiers: set[str]) -> dict[str, set[str]]:
    """Directories this resolver does not judge, with the reasons.

    Besides the per-directory reasons of `unmodeled_qualifiers`, a regional
    directory is unchecked when its language also appears with another
    region. Android does not require the region to match when the scripts
    agree, so an es-US device can take values-b+es+419; the better region is
    then chosen by CLDR region distance, which this resolver does not model.
    """
    out = {q: unmodeled_qualifiers(q) for q in qualifiers}
    regional: dict[str, dict[str, str]] = {}
    for q in qualifiers:
        locale = qualifier_parts(q).get("locale")
        if not isinstance(locale, str) or out[q]:
            continue
        lang, _, region = locale_parts(locale)
        if region is not None:
            regional.setdefault(lang, {})[q] = region
    for dirs in regional.values():
        if len(set(dirs.values())) > 1:
            for q in dirs:
                out[q].add("region fallback")
    return {q: reasons for q, reasons in out.items() if reasons}


def device_config(qualifier: str, api: int = DEVICE_API) -> dict[str, str | int]:
    """The device configuration that `qualifier` describes, on a device that
    runs `api`. A device is always in day or night mode, so an unspecified
    mode means `notnight`, and always has a screen size, so an unspecified
    size means `normal`."""
    config = qualifier_parts(qualifier)
    config["version"] = api
    config.setdefault("night", "notnight")
    config.setdefault("size", NORMAL_SIZE)
    return config


def normalize_config(config: dict, kinds: set[str]) -> dict:
    """Make a generated configuration physically possible. A device's current
    width and height are never below its smallest width, so where the
    supplied resources use `w`/`h` qualifiers they are raised to `sw`."""
    sw = config.get("sw")
    if not isinstance(sw, int):
        return config
    out = dict(config)
    for k in ("w", "h"):
        if k in kinds:
            out[k] = max(out.get(k, sw), sw)
    return out


def config_name(config: dict) -> str:
    """Render a device configuration as a resource directory name (version omitted)."""
    tokens = []
    for kind in PRECEDENCE:
        if (
            kind == "version"
            or kind not in config
            or (kind == "night" and config[kind] == "notnight")
            or (kind == "size" and config[kind] == NORMAL_SIZE)
        ):
            continue
        value = config[kind]
        if kind in ("sw", "w", "h"):
            tokens.append(f"{kind}{value}dp")
        elif kind == "size":
            tokens.append(SCREEN_SIZE_NAMES[value])
        elif kind == "locale":
            tokens.append(locale_qualifier(value))
        else:
            tokens.append(str(value))
    tokens += [str(v) for k, v in config.items() if k.startswith("unknown:")]
    return "-".join(["values", *tokens])


def _matches(directory: dict, config: dict) -> bool:
    for kind, value in directory.items():
        if kind in THRESHOLD_KINDS:
            have = config.get(kind)
            if not isinstance(have, int) or value > have:
                return False
        elif kind == "locale":
            want = config.get("locale")
            if not isinstance(want, str):
                return False
            lang, script, region = locale_parts(value)
            w_lang, w_script, w_region = locale_parts(want)
            # A part the directory leaves out matches any device value.
            if (
                lang != w_lang
                or script not in (None, w_script)
                or region not in (None, w_region)
            ):
                return False
        elif config.get(kind) != value:
            return False
    return True


def best_match(qualifiers: set[str], config: dict) -> str | None:
    """Android's best-matching resource directory among `qualifiers`."""
    candidates = [(q, qualifier_parts(q)) for q in qualifiers]
    candidates = [(q, d) for q, d in candidates if _matches(d, config)]
    for kind in PRECEDENCE:
        if not any(kind in d for _, d in candidates):
            continue
        with_kind = [(q, d) for q, d in candidates if kind in d]
        if kind == "size":
            # Unlike other qualifiers, an unqualified size is not eliminated:
            # it counts as `normal` on a device that is at least `normal`.
            # On a tie the explicit size wins (values-normal over values).
            device = config.get("size", NORMAL_SIZE)
            unset = NORMAL_SIZE if device >= NORMAL_SIZE else 0
            sizes = [(q, d, d.get("size", unset)) for q, d in candidates]
            top = max(s for _, _, s in sizes)
            at_top = [(q, d) for q, d, s in sizes if s == top]
            with_kind = [(q, d) for q, d in at_top if "size" in d] or at_top
        elif kind in THRESHOLD_KINDS:
            top = max(d[kind] for _, d in with_kind)
            with_kind = [(q, d) for q, d in with_kind if d[kind] == top]
        elif kind == "locale":
            # All remaining locales match; the most specific one wins.
            def specificity(d: dict) -> int:
                return sum(x is not None for x in locale_parts(d["locale"])[1:])

            top = max(specificity(d) for _, d in with_kind)
            with_kind = [(q, d) for q, d in with_kind if specificity(d) == top]
        candidates = with_kind
    return candidates[0][0] if candidates else None


def resolve_opt_out(
    styles: list[Style], name: str, qualifier: str | dict, api: int = DEVICE_API
) -> OptOutResolution | None:
    """Follow the style's parents until one sets the opt-out item.

    `qualifier` names the device configuration to resolve for, such as
    `values` (default), `values-night`, or `values-zh-night`, on a device that
    runs `api`; a dict is a complete configuration. Each style in the chain, parents included, is taken from its own
    best-matching resource directory, as Android does. Returns None if the
    requested style itself is not provided.
    """
    config = device_config(qualifier, api) if isinstance(qualifier, str) else qualifier

    def find(n: str) -> Style | None:
        defined = {s.qualifier for s in styles if s.name == n}
        q = best_match(defined, config)
        return next((s for s in styles if s.name == n and s.qualifier == q), None)

    chain: list[str] = []
    resolved: list[Style] = []
    current = name
    while current and current not in chain:
        style = find(current)
        if style is None:
            if not chain:
                return None
            return OptOutResolution(
                None, None, None, chain, missing_parent=current, styles=resolved
            )
        chain.append(current)
        resolved.append(style)
        if style.opt_out is not None:
            return OptOutResolution(
                style.opt_out_value,
                style.opt_out,
                style.name,
                chain,
                unresolved_value=(
                    None if style.opt_out_value is not None else style.opt_out_raw
                ),
                styles=resolved,
            )
        current = implicit_parent(style)
    return OptOutResolution(None, None, None, chain, styles=resolved)


@dataclass
class AppInputs:
    files: list[str] = field(default_factory=list)
    gradle_provided: bool = False
    manifest_provided: bool = False
    styles_provided: bool = False
    dart_provided: bool = False
    target_sdk: TargetSdk | None = None
    normal_theme: tuple[str, Clue] | None = None
    launch_theme: tuple[str, Clue] | None = None
    framework_theme: tuple[str, Clue] | None = None  # such as @android:style/...
    normal_framework: tuple[str, Clue] | None = None  # meta-data naming a non-app theme
    theme_manifest: str | None = None  # the manifest that decided the themes
    # Themes a later manifest (such as src/debug) names but the audit does not judge.
    other_themes: list[tuple[str, Clue]] = field(default_factory=list)
    # Several activities name a NormalTheme and none is the launcher.
    ambiguous_themes: list[tuple[str, Clue]] = field(default_factory=list)
    # Manifest merger directives (tools:node, tools:replace) in a later manifest.
    merge_directives: list[Clue] = field(default_factory=list)
    # Styles from build-type source sets (src/debug, ...); not judged.
    variant_styles: list[Style] = field(default_factory=list)
    styles: list[Style] = field(default_factory=list)
    ui_modes: list[tuple[str, Clue]] = field(default_factory=list)
    safe_areas: list[Clue] = field(default_factory=list)
    app_bars: list[Clue] = field(default_factory=list)
    scaffolds: list[Clue] = field(default_factory=list)
    overlay_colors: list[Clue] = field(default_factory=list)


def _lines(text: str):
    for no, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith(("//", "#", "*")):
            continue
        yield no, line


# --- Gradle ---------------------------------------------------------------

TARGET_SDK = re.compile(r"^\s*targetSdk(?:Version)?\s*(?:=\s*|\s+)(.+?)\s*$")


def read_gradle(text: str, name: str, inputs: AppInputs) -> None:
    inputs.gradle_provided = True
    for no, line in _lines(text):
        m = TARGET_SDK.match(line)
        if m:
            raw = m.group(1).strip().strip("\"'")
            inputs.target_sdk = TargetSdk(raw, Clue(name, no, line))


# --- AndroidManifest.xml --------------------------------------------------

NORMAL_THEME_META = "io.flutter.embedding.android.NormalTheme"
MANIFEST_TAG = re.compile(
    r"<(application|activity-alias|activity|meta-data)\b([^>]*?)(/?)>", re.DOTALL
)
ACTIVITY_START = re.compile(r"<activity(?:-alias)?\b")
APPLICATION_END = re.compile(r"</application\s*>")
MERGE_DIRECTIVE = re.compile(r"\btools:(?:node|replace|remove)\s*=")
ACTIVITY_END = {
    "activity": re.compile(r"</activity\s*>"),
    "activity-alias": re.compile(r"</activity-alias\s*>"),
}
CDATA = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)
APP_STYLE = re.compile(r"@style/([\w.]+)$")


def _attrs(tag: re.Match) -> dict[str, str]:
    return {m.group(1): m.group(2) or m.group(3) for m in ATTR.finditer(tag.group(2))}


def _theme_attr(
    text: str, name: str, tag: re.Match, attr: str
) -> tuple[str, Clue, bool] | None:
    """An attribute's theme reference, with the line that names it and
    whether it is an app style (@style/...). The name is the style name for
    an app style, else the raw value (such as @android:style/...)."""
    for m in ATTR.finditer(tag.group(2)):
        if m.group(1) != attr:
            continue
        raw = (m.group(2) or m.group(3) or "").strip()
        line = text.count("\n", 0, tag.start(2) + m.start()) + 1
        clue = Clue(name, line, text.splitlines()[line - 1])
        style = APP_STYLE.match(raw)
        return (style.group(1), clue, True) if style else (raw, clue, False)
    return None


def _same_activity(name: str, target: str) -> bool:
    """Whether two android:name values can name the same class. A relative
    name (.Main, or Main without a package) matches the end of a qualified
    one, since the manifest's package may not be in the snippet."""

    def relative(n: str) -> str | None:
        if n.startswith("."):
            return n
        return "." + n if "." not in n else None

    if name == target:
        return True
    for a, b in ((name, target), (target, name)):
        rel = relative(a)
        if rel and (b.endswith(rel) or relative(b) == rel):
            return True
    return False


def read_manifest(text: str, name: str, inputs: AppInputs) -> None:
    """Read the FlutterActivity's themes. The NormalTheme meta-data names the
    theme Flutter switches to after the launch screen; the activity's
    android:theme (or, without one, the application's) is the launch theme.

    The activity is the launcher among those with the meta-data, else the
    only one with it, else the launcher (directly or through an
    activity-alias), else the only activity. Flutter reads the meta-data of
    the activity, so application-level meta-data does not count; a bare
    meta-data snippet does. The first manifest that names a theme (read_paths
    reads src/main first) decides them all; a later one is only recorded,
    with any manifest merger directives it carries."""
    inputs.manifest_provided = True
    body = CDATA.sub(_blank, XML_COMMENT.sub(_blank, text))
    app_theme = None
    app_end = -1
    loose = None  # NormalTheme meta-data outside any activity (a snippet)
    activities: list[dict] = []
    alias_targets: list[str] = []  # targetActivity of launcher aliases
    directives: list[Clue] = []
    current = None
    end = -1
    for tag in MANIFEST_TAG.finditer(body):
        kind = tag.group(1)
        attrs = _attrs(tag)
        if MERGE_DIRECTIVE.search(tag.group(2)):
            line = text.count("\n", 0, tag.start()) + 1
            directives.append(Clue(name, line, text.splitlines()[line - 1]))
        if current is not None and tag.start() >= end:  # end is exclusive
            current = None
        if kind == "application":
            app_theme = _theme_attr(text, name, tag, "android:theme")
            close = APPLICATION_END.search(body, tag.end())
            app_end = (
                tag.end() if tag.group(3) else (close.end() if close else len(body))
            )
        elif kind in ACTIVITY_END:
            if tag.group(3):
                end = tag.end()
            else:  # a snippet may omit the closing tag: stop at the next activity
                sibling = ACTIVITY_START.search(body, tag.end())
                limit = sibling.start() if sibling else len(body)
                close = ACTIVITY_END[kind].search(body, tag.end(), limit)
                end = close.end() if close else limit
            launcher = "android.intent.category.LAUNCHER" in body[tag.end() : end]
            if kind == "activity-alias":
                current = None  # its meta-data does not theme the activity
                if launcher and attrs.get("android:targetActivity"):
                    alias_targets.append(attrs["android:targetActivity"])
                continue
            current = {
                "name": attrs.get("android:name", ""),
                "theme": _theme_attr(text, name, tag, "android:theme"),
                "normal": None,
                "launcher": launcher,
            }
            activities.append(current)
        elif attrs.get("android:name") == NORMAL_THEME_META:
            if attrs.get("tools:node") in ("remove", "removeAll"):
                continue  # removes a declaration; it declares nothing
            theme = _theme_attr(text, name, tag, "android:resource")
            if current is not None:
                current["normal"] = theme
            elif tag.start() > app_end:
                loose = theme  # outside the application: a bare snippet
    for target in alias_targets:
        matches = [a for a in activities if _same_activity(a["name"], target)]
        if len(matches) == 1:  # an ambiguous target chooses nothing
            matches[0]["launcher"] = True
    flutter = [a for a in activities if a["normal"]]
    ambiguous: list[tuple[str, Clue]] = []
    if len(flutter) > 1:
        launchers = [a for a in flutter if a["launcher"]]
        chosen = launchers[0] if len(launchers) == 1 else None
        if chosen is None:
            ambiguous = [a["normal"][:2] for a in flutter]
    else:
        launchers = [a for a in activities if a["launcher"]]
        chosen = (
            (flutter[0] if flutter else None)
            or (launchers[0] if len(launchers) == 1 else None)
            or (activities[0] if len(activities) == 1 else None)
        )
    if chosen:
        normal, launch = chosen["normal"], chosen["theme"] or app_theme
    elif not activities:
        normal, launch = loose, app_theme
    else:
        normal, launch = None, None
    if inputs.theme_manifest is not None:
        # A later manifest (such as src/debug) does not decide the themes.
        inputs.merge_directives += directives
        base_normal = inputs.normal_theme or inputs.normal_framework
        base_launch = inputs.launch_theme or inputs.framework_theme
        for new, base in ((normal, base_normal), (launch, base_launch)):
            if new and (base is None or new[0] != base[0]):
                inputs.other_themes.append(new[:2])
        inputs.other_themes += [t for t in ambiguous if t not in inputs.other_themes]
        return
    if not (normal or launch or ambiguous):
        return  # names no theme (such as src/profile with permissions only)
    inputs.theme_manifest = name
    inputs.ambiguous_themes = ambiguous
    if normal:
        style, clue, is_app = normal
        inputs.normal_theme = (style, clue) if is_app else None
        inputs.normal_framework = None if is_app else (style, clue)
    if launch:
        style, clue, is_app = launch
        inputs.launch_theme = (style, clue) if is_app else None
        inputs.framework_theme = None if is_app else (style, clue)


# --- res/values*/styles.xml -----------------------------------------------

XML_DECL = re.compile(r"<\?xml[^>]*\?>")
XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
STYLE_TAG = re.compile(r"<style\b([^>]*?)(/?)>", re.DOTALL)
STYLE_END = re.compile(r"</style\s*>")
ATTR = re.compile(r"""([\w:]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
ITEM = re.compile(r"<item\b([^>]*)>(.*?)</item\s*>", re.DOTALL)


def _blank(m: re.Match) -> str:
    """Replace matched text with spaces, keeping newlines so line numbers hold."""
    return re.sub(r"[^\n]", " ", m.group(0))


def _parse_styles_xml(text: str) -> list[dict] | None:
    """Parse with expat. Snippets may lack a single root, so wrap them."""
    import xml.parsers.expat

    body = XML_DECL.sub(_blank, text)
    found: list[dict] = []
    stack: list[dict] = []
    item: dict | None = None
    parser = xml.parsers.expat.ParserCreate()

    def start(tag, attrs):
        nonlocal item
        if tag == "style" and "name" in attrs:
            stack.append(
                {
                    "name": attrs["name"],
                    "parent": attrs.get("parent"),
                    "line": parser.CurrentLineNumber,
                    "item": None,
                }
            )
        elif tag == "item" and stack and attrs.get("name") == OPT_OUT_ATTR:
            item = {"line": parser.CurrentLineNumber, "text": ""}

    def data(chunk):
        if item is not None:
            item["text"] += chunk

    def end(tag):
        nonlocal item
        if tag == "item" and item is not None:
            stack[-1]["item"] = item
            item = None
        elif tag == "style" and stack:
            found.append(stack.pop())

    (
        parser.StartElementHandler,
        parser.CharacterDataHandler,
        parser.EndElementHandler,
    ) = (start, data, end)
    try:
        parser.Parse(f"<fma-root>{body}</fma-root>", True)
    except xml.parsers.expat.ExpatError:
        return None
    return found


def _scan_styles_regex(text: str) -> list[dict]:
    """Fallback for snippets that are not well-formed XML."""
    body = XML_COMMENT.sub(_blank, text)
    found = []
    for m in STYLE_TAG.finditer(body):
        attrs = {
            a.group(1): a.group(2) if a.group(2) is not None else a.group(3)
            for a in ATTR.finditer(m.group(1))
        }
        if "name" not in attrs:
            continue
        style = {
            "name": attrs["name"],
            "parent": attrs.get("parent"),
            "line": body.count("\n", 0, m.start()) + 1,
            "item": None,
        }
        if not m.group(2):  # not self-closing
            close = STYLE_END.search(body, m.end())
            inner_end = close.start() if close else len(body)
            for it in ITEM.finditer(body, m.end(), inner_end):
                it_attrs = {
                    a.group(1): a.group(2) if a.group(2) is not None else a.group(3)
                    for a in ATTR.finditer(it.group(1))
                }
                if it_attrs.get("name") == OPT_OUT_ATTR:
                    style["item"] = {
                        "line": body.count("\n", 0, it.start()) + 1,
                        "text": it.group(2),
                    }
                    break
        found.append(style)
    return found


def read_styles(text: str, name: str, qualifier: str, inputs: AppInputs) -> None:
    inputs.styles_provided = True
    lines = text.splitlines()
    parsed = _parse_styles_xml(text)
    if parsed is None:
        parsed = _scan_styles_regex(text)
    for st in sorted(parsed, key=lambda s: s["line"]):
        opt_clue, opt_value, opt_raw = None, None, None
        if st["item"]:
            raw = st["item"]["text"].strip()
            opt_clue = Clue(name, st["item"]["line"], lines[st["item"]["line"] - 1])
            opt_raw, opt_value = raw, {"true": True, "false": False}.get(raw)
        inputs.styles.append(
            Style(
                st["name"],
                qualifier,
                opt_clue,
                Clue(name, st["line"], lines[st["line"] - 1]),
                opt_out_value=opt_value,
                opt_out_raw=opt_raw,
                parent=st["parent"],
            )
        )


# --- Dart -----------------------------------------------------------------

UI_MODE = re.compile(r"setEnabledSystemUIMode\(\s*SystemUiMode\.(\w+)")
OVERLAY_COLOR = re.compile(r"\b(statusBarColor|systemNavigationBarColor)\s*:")


def read_dart(text: str, name: str, inputs: AppInputs) -> None:
    inputs.dart_provided = True
    for no, line in _lines(text):
        clue = Clue(name, no, line)
        if m := UI_MODE.search(line):
            inputs.ui_modes.append((m.group(1), clue))
        if re.search(r"\b(Sliver)?SafeArea\(", line):
            inputs.safe_areas.append(clue)
        if re.search(r"\b(Sliver)?AppBar\(", line):
            inputs.app_bars.append(clue)
        if re.search(r"\bScaffold\(", line):
            inputs.scaffolds.append(clue)
        if OVERLAY_COLOR.search(line):
            inputs.overlay_colors.append(clue)


# --- Discovery ------------------------------------------------------------


def source_set(path: Path) -> str | None:
    """The Gradle source set a file is in (`main`, `debug`, ...): the name in
    the last `src/<name>/res/...` or `src/<name>/AndroidManifest.xml` of its
    path. None if the path has no such shape."""
    parts = path.parts
    for i in range(len(parts) - 3, -1, -1):
        if parts[i] != "src":
            continue
        rest = parts[i + 2 :]
        if rest == ("AndroidManifest.xml",) or (rest[0] == "res" and len(rest) > 1):
            return parts[i + 1]
    return None


def build_type_styles(path: Path, relative: Path) -> bool:
    """Whether a styles.xml is in a source set other than main. The path
    must look like one and have a src/main next to it on disk, as every
    Android module does; an unrelated `src/<name>/res` directory is judged."""
    name = source_set(relative)
    if name in (None, "main"):
        return False
    parts = path.parts
    i = max(
        k for k in range(len(parts) - 2) if parts[k] == "src" and parts[k + 1] == name
    )
    return Path(*parts[: i + 1], "main").is_dir()


def read_paths(paths: list[Path], root: Path | None = None) -> AppInputs:
    """Read known file types. `root` only shortens names in the report."""
    inputs = AppInputs()

    given = {path: i for i, path in enumerate(paths)}

    def rel(path: Path) -> Path:
        # Look for source sets below the input root only.
        return path.relative_to(root) if root else path

    def order(path: Path):
        # src/main's manifest first: build-type manifests (src/debug,
        # src/profile) only add to the base source set; they do not decide
        # the audited theme. Other manifests keep the order they were given.
        if path.name == "AndroidManifest.xml" and source_set(rel(path)) != "main":
            return (1, given[path], path)
        return (0, 0, path)  # Path order compares parts: values before values-night

    for path in sorted(paths, key=order):
        name = str(path.relative_to(root)) if root else str(path)
        text = path.read_text(encoding="utf-8")
        if path.name in ("build.gradle", "build.gradle.kts"):
            read_gradle(text, name, inputs)
        elif path.name == "AndroidManifest.xml":
            read_manifest(text, name, inputs)
        elif path.name == "styles.xml":
            parent = path.parent.name
            qualifier = parent if parent.startswith("values") else "values"
            if not build_type_styles(path, rel(path)):
                read_styles(text, name, qualifier, inputs)
            else:  # a build-type source set: recorded, not judged
                variant = AppInputs()
                read_styles(text, name, qualifier, variant)
                inputs.variant_styles += variant.styles
        elif path.suffix == ".dart":
            read_dart(text, name, inputs)
        else:
            continue
        inputs.files.append(name)
    return inputs


def discover(root: Path) -> AppInputs:
    """Find inputs in a directory laid out like a Flutter project (or a subset)."""
    wanted = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and (
            p.name in ("AndroidManifest.xml", "styles.xml")
            or p.suffix == ".dart"
            # Only the app module sets targetSdk; skip the root build file.
            or (
                p.name in ("build.gradle", "build.gradle.kts")
                and p.parent.name == "app"
            )
        )
    ]
    return read_paths(sorted(wanted), root)
