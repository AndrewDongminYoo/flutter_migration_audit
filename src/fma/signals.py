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


def resolve_opt_out(styles: list[Style], name: str, qualifier: str) -> OptOutResolution | None:
    """Follow the style's parents until one sets the opt-out item.

    Parents are looked up in the same resource directory first, then in the
    default `values` directory, as Android does. Returns None if the
    requested style itself is not provided.
    """
    def find(n: str) -> Style | None:
        for q in (qualifier, "values"):
            for s in styles:
                if s.name == n and s.qualifier == q:
                    return s
        return None

    chain: list[str] = []
    current = name
    while current and current not in chain:
        style = find(current)
        if style is None:
            if not chain:
                return None
            return OptOutResolution(None, None, None, chain, missing_parent=current)
        chain.append(current)
        if style.opt_out is not None:
            return OptOutResolution(style.opt_out_value, style.opt_out, style.name, chain,
                                    unresolved_value=None if style.opt_out_value is not None else style.opt_out_raw)
        current = implicit_parent(style)
    return OptOutResolution(None, None, None, chain)


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

STYLE = re.compile(r'<style\s+name="([\w.]+)"([^>]*)>(.*?)</style>', re.DOTALL)
STYLE_PARENT = re.compile(r'\bparent="([^"]*)"')
OPT_OUT_ITEM = re.compile(
    r'<item\s+name="' + re.escape(OPT_OUT_ATTR) + r'"\s*>\s*([^<]*?)\s*</item>'
)


def read_styles(text: str, name: str, qualifier: str, inputs: AppInputs) -> None:
    inputs.styles_provided = True
    for m in STYLE.finditer(text):
        start_line = text.count("\n", 0, m.start()) + 1
        body_offset = m.start(3)
        opt = OPT_OUT_ITEM.search(m.group(3))
        opt_clue, opt_value, opt_raw = None, None, None
        if opt:
            line = text.count("\n", 0, body_offset + opt.start()) + 1
            opt_clue = Clue(name, line, text.splitlines()[line - 1])
            opt_raw = opt.group(1)
            opt_value = {"true": True, "false": False}.get(opt_raw)
        parent = STYLE_PARENT.search(m.group(2))
        inputs.styles.append(
            Style(m.group(1), qualifier, opt_clue,
                  Clue(name, start_line, text.splitlines()[start_line - 1]),
                  opt_out_value=opt_value, opt_out_raw=opt_raw,
                  parent=parent.group(1) if parent else None)
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
