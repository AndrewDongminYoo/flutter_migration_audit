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
    (kind, re.compile(pattern)) for kind, pattern in [
        ("mcc", r"mcc\d+"), ("mnc", r"mnc\d+"),
        ("layoutdir", r"ldrtl|ldltr"),
        ("sw", r"sw\d+dp"), ("w", r"w\d+dp"), ("h", r"h\d+dp"),
        ("size", r"small|normal|large|xlarge"), ("long", r"long|notlong"),
        ("round", r"round|notround"), ("gamut", r"widecg|nowidecg"), ("hdr", r"highdr|lowdr"),
        ("orientation", r"port|land"),
        ("uimode", r"car|desk|television|appliance|watch|vrheadset"),
        ("night", r"night|notnight"),
        ("density", r"ldpi|mdpi|hdpi|xhdpi|xxhdpi|xxxhdpi|nodpi|tvdpi|anydpi|\d+dpi"),
        ("touch", r"notouch|finger"), ("keys", r"keysexposed|keyshidden|keyssoft"),
        ("input", r"nokeys|qwerty|12key"), ("navexp", r"navexposed|navhidden"),
        ("nav", r"nonav|dpad|trackball|wheel"),
        ("version", r"v\d+"),
        ("locale", r"[a-z]{2,3}|r[A-Z]{2}|b\+[\w+]+"),
    ]
]
PRECEDENCE = ["mcc", "mnc", "locale", "layoutdir", "sw", "w", "h", "size", "long", "round",
              "gamut", "hdr", "orientation", "uimode", "night", "density", "touch", "keys",
              "input", "navexp", "nav", "version"]
# The audit looks at Android 15 devices, so every configuration it resolves
# runs API 35. Directories for later versions (values-v36) never apply.
DEVICE_API = 35


# Qualifiers that name a minimum value: a directory applies when the device
# value is at least this, and the largest such threshold wins.
THRESHOLD_KINDS = {"version", "sw", "w", "h"}


def qualifier_parts(qualifier: str) -> dict[str, str | int]:
    """Parse `values-zh-rCN-night-v35` into {"locale": "zh-rCN", "night": "night", "version": 35}."""
    parts: dict[str, str | int] = {}
    for token in qualifier.split("-")[1:]:
        for kind, pattern in QUALIFIER_KINDS:
            if pattern.fullmatch(token):
                if kind in THRESHOLD_KINDS:
                    parts[kind] = int(re.sub(r"\D", "", token))
                elif kind == "locale" and "locale" in parts:
                    parts[kind] = f"{parts[kind]}-{token}"
                else:
                    parts[kind] = token
                break
        else:
            parts[f"unknown:{token}"] = token
    return parts


def device_config(qualifier: str) -> dict[str, str | int]:
    """The API 35 device configuration that `qualifier` describes. A device is
    always in day or night mode, so an unspecified mode means `notnight`."""
    config = qualifier_parts(qualifier)
    config["version"] = DEVICE_API
    config.setdefault("night", "notnight")
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
        if kind == "version" or kind not in config or (kind == "night" and config[kind] == "notnight"):
            continue
        value = config[kind]
        tokens.append(f"{kind}{value}dp" if kind in ("sw", "w", "h") else str(value))
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
            if not isinstance(want, str) or not (want == value or want.split("-")[0] == value):
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
        if kind in THRESHOLD_KINDS:
            top = max(d[kind] for _, d in with_kind)
            with_kind = [(q, d) for q, d in with_kind if d[kind] == top]
        elif kind == "locale":
            exact = [(q, d) for q, d in with_kind if d["locale"] == config.get("locale")]
            with_kind = exact or with_kind
        candidates = with_kind
    return candidates[0][0] if candidates else None


def resolve_opt_out(styles: list[Style], name: str, qualifier: str | dict) -> OptOutResolution | None:
    """Follow the style's parents until one sets the opt-out item.

    `qualifier` names the device configuration to resolve for, such as
    `values` (default), `values-night`, or `values-zh-night`, on an API 35
    device. Each style in the chain, parents included, is taken from its own
    best-matching resource directory, as Android does. Returns None if the
    requested style itself is not provided.
    """
    config = device_config(qualifier) if isinstance(qualifier, str) else qualifier

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
            return OptOutResolution(None, None, None, chain, missing_parent=current, styles=resolved)
        chain.append(current)
        resolved.append(style)
        if style.opt_out is not None:
            return OptOutResolution(style.opt_out_value, style.opt_out, style.name, chain,
                                    unresolved_value=None if style.opt_out_value is not None else style.opt_out_raw,
                                    styles=resolved)
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

NORMAL_THEME = re.compile(
    r'android:name="io\.flutter\.embedding\.android\.NormalTheme"[^>]*?'
    r'android:resource="@style/([\w.]+)"',
    re.DOTALL,
)


def read_manifest(text: str, name: str, inputs: AppInputs) -> None:
    inputs.manifest_provided = True
    m = NORMAL_THEME.search(text)
    if m:
        line = text.count("\n", 0, m.start(1)) + 1
        inputs.normal_theme = (m.group(1), Clue(name, line, text.splitlines()[line - 1]))


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
            stack.append({"name": attrs["name"], "parent": attrs.get("parent"),
                          "line": parser.CurrentLineNumber, "item": None})
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

    parser.StartElementHandler, parser.CharacterDataHandler, parser.EndElementHandler = start, data, end
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
        attrs = {a.group(1): a.group(2) if a.group(2) is not None else a.group(3)
                 for a in ATTR.finditer(m.group(1))}
        if "name" not in attrs:
            continue
        style = {"name": attrs["name"], "parent": attrs.get("parent"),
                 "line": body.count("\n", 0, m.start()) + 1, "item": None}
        if not m.group(2):  # not self-closing
            close = STYLE_END.search(body, m.end())
            inner_end = close.start() if close else len(body)
            for it in ITEM.finditer(body, m.end(), inner_end):
                it_attrs = {a.group(1): a.group(2) if a.group(2) is not None else a.group(3)
                            for a in ATTR.finditer(it.group(1))}
                if it_attrs.get("name") == OPT_OUT_ATTR:
                    style["item"] = {"line": body.count("\n", 0, it.start()) + 1, "text": it.group(2)}
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
            Style(st["name"], qualifier, opt_clue, Clue(name, st["line"], lines[st["line"] - 1]),
                  opt_out_value=opt_value, opt_out_raw=opt_raw, parent=st["parent"])
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

def read_paths(paths: list[Path], root: Path | None = None) -> AppInputs:
    """Read known file types. `root` only shortens names in the report."""
    inputs = AppInputs()
    for path in sorted(paths):
        name = str(path.relative_to(root)) if root else str(path)
        text = path.read_text(encoding="utf-8")
        if path.name in ("build.gradle", "build.gradle.kts"):
            read_gradle(text, name, inputs)
        elif path.name == "AndroidManifest.xml":
            read_manifest(text, name, inputs)
        elif path.name == "styles.xml":
            parent = path.parent.name
            read_styles(text, name, parent if parent.startswith("values") else "values", inputs)
        elif path.suffix == ".dart":
            read_dart(text, name, inputs)
        else:
            continue
        inputs.files.append(name)
    return inputs


def discover(root: Path) -> AppInputs:
    """Find inputs in a directory laid out like a Flutter project (or a subset)."""
    wanted = [
        p for p in root.rglob("*")
        if p.is_file() and (
            p.name in ("AndroidManifest.xml", "styles.xml")
            or p.suffix == ".dart"
            # Only the app module sets targetSdk; skip the root build file.
            or (p.name in ("build.gradle", "build.gradle.kts") and p.parent.name == "app")
        )
    ]
    return read_paths(wanted, root)
