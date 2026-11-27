"""Dartdoc macro expansion in the API doc extractor (issue #5)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fetch_api_docs", ROOT / "scripts" / "fetch_api_docs.py"
)
fad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fad)

SOURCE = """\
/// Some class.
///
/// {@template demo.primary}
/// Whether this bar is at the top of the screen.
///
/// If true, it is padded by the status bar height.
/// {@endtemplate}
class Bar {
  /// {@macro demo.primary}
  final bool primary;

  /// {@macro demo.outer}
  final int nested;

  /// {@macro dart.ui.Missing}
  final int missing;
}

/// {@template demo.outer}
/// Outer text, then {@macro demo.primary}
/// {@endtemplate}
class Other {}
"""


def test_collect_templates():
    t = fad.collect_templates({"a.dart": SOURCE})
    assert set(t) == {"demo.primary", "demo.outer"}
    assert t["demo.primary"].startswith("Whether this bar")
    assert "{@endtemplate}" not in t["demo.primary"]


def test_parse_expands_macros_and_records_unresolved():
    templates = fad.collect_templates({"a.dart": SOURCE})
    bar = next(d for d in fad.parse(SOURCE, templates) if d["name"] == "Bar")
    members = dict(bar["members"])
    assert "padded by the status bar height" in members["primary"]
    assert (
        "Outer text" in members["nested"]
        and "padded by the status bar height" in members["nested"]
    )
    assert members["missing"] == "{@macro dart.ui.Missing}"
    assert bar["unresolved"] == {"dart.ui.Missing"}
    # Template markers do not leak into the class doc that defines them.
    assert "{@template" not in bar["doc"] and "{@endtemplate}" not in bar["doc"]
    assert "Whether this bar is at the top" in bar["doc"]


def test_recursive_macro_stops():
    templates = {"a": "A {@macro b}", "b": "B {@macro a}"}
    unresolved = set()
    out = fad.expand_macros("{@macro a}", templates, unresolved)
    assert out.count("A") <= fad.MAX_MACRO_DEPTH + 1
    assert unresolved  # the loop is reported, not expanded forever


def test_parse_without_templates_keeps_old_behavior():
    bar = next(d for d in fad.parse(SOURCE) if d["name"] == "Bar")
    assert dict(bar["members"])["primary"] == "{@macro demo.primary}"


def test_committed_manifest_lists_only_known_unresolved_macro():
    import json

    unresolved = set()
    for line in (ROOT / "data" / "manifest" / "api_docs.jsonl").open():
        unresolved.update(json.loads(line)["unresolved_macros"])
    # Defined in dart:ui, outside packages/flutter/lib.
    assert unresolved == {"dart.ui.ViewConfiguration.displayFeatures"}
