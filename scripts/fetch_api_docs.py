"""Extract versioned API docs from Flutter framework source.

api.flutter.dev only serves the current release, so the API pages for older
versions are rebuilt from the dartdoc comments (`///`) in flutter/flutter at
each release tag. Each public top-level declaration (class, enum, mixin,
extension) becomes one Markdown doc, with its documented members as sections.

Outputs:
  data/raw/snapshots/<id>/api/<library>/<Name>.md   (ignored by git)
  data/manifest/api_docs.jsonl                      (committed)

Run: uv run --python 3.12 scripts/fetch_api_docs.py
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "raw" / "snapshots"
MANIFEST = ROOT / "data" / "manifest"

# Same snapshot ids as fetch_snapshots.py. API docs ship with the release, so
# each id maps to the release tag itself. `latest` is pinned to the stable
# release that was current when the corpus was built.
TAGS = {
    "flutter-3.24": "3.24.0",
    "flutter-3.27": "3.27.0",
    "latest": "3.50.1",
}

SOURCES = (
    "packages/flutter/lib/src/services/system_chrome.dart",
    "packages/flutter/lib/src/widgets/safe_area.dart",
    "packages/flutter/lib/src/widgets/media_query.dart",
    "packages/flutter/lib/src/widgets/annotated_region.dart",
    "packages/flutter/lib/src/material/app_bar.dart",
)

RAW_URL = "https://raw.githubusercontent.com/flutter/flutter/{tag}/{path}"

TOP_DECL = re.compile(
    r"^(?:(?:abstract|base|final|sealed|interface|mixin)\s+)*"
    r"(class|enum|mixin|extension(?:\s+type)?)\s+(\w+)"
)
MEMBER_ACCESSOR = re.compile(r"\b[gs]et\s+(\w+)")
# The declared name is the earliest identifier followed by `(` (method,
# constructor) or by `;`, `=`, `,` (field, enum value). Taking the earliest
# match handles `static const X light = X(...)`.
MEMBER_NAME = re.compile(r"(\w+)\s*(?:\(|[;=,]|$)")
# Dartdoc directives that carry no prose of their own.
DIRECTIVE = re.compile(r"\{@(?:tool|end-tool|youtube|animation|dartpad|end-template)[^}]*\}")
# Headings inside a doc comment are pushed below the member headings.
DOC_HEADING = re.compile(r"^(#{1,4}) ", re.MULTILINE)


def fetch(tag: str, path: str) -> str:
    with urllib.request.urlopen(RAW_URL.format(tag=tag, path=path), timeout=30) as resp:
        return resp.read().decode("utf-8")


GENERIC_ARGS = re.compile(r"<[^<>]*>")


def member_name(decl: str) -> str | None:
    # Drop type arguments first so `Map<String, dynamic> _toMap()` does not
    # match `String,` as a field name.
    prev = None
    while prev != decl:
        prev, decl = decl, GENERIC_ARGS.sub("", decl)
    m = MEMBER_ACCESSOR.search(decl) or MEMBER_NAME.search(decl)
    return m.group(1) if m else None


def clean(lines: list[str]) -> str:
    text = "\n".join(l[3:].removeprefix(" ") for l in lines)
    text = DOC_HEADING.sub(r"##\1 ", text)
    return DIRECTIVE.sub("", text).strip()


def parse(source: str) -> list[dict]:
    """Return [{name, kind, doc, members: [(name, doc)]}] for public declarations."""
    decls: list[dict] = []
    current: dict | None = None
    pending: list[str] = []
    for raw in source.splitlines():
        stripped = raw.strip()
        if stripped.startswith("///"):
            pending.append(stripped)
            continue
        if not stripped:
            pending = []  # a doc block must sit directly above its declaration
            continue
        if stripped.startswith(("@", "//")):
            continue  # annotations and plain comments between doc and declaration
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            m = TOP_DECL.match(stripped)
            if m and not m.group(2).startswith("_"):
                current = {"name": m.group(2), "kind": m.group(1).split()[0],
                           "doc": clean(pending), "members": []}
                decls.append(current)
            elif m or stripped.startswith(("typedef", "const", "final")) or "(" in stripped:
                current = None
            pending = []
            continue
        if current is not None and pending and indent == 2:
            name = member_name(stripped)
            if name and not name.startswith("_"):
                current["members"].append((name, clean(pending)))
        pending = []
    return [d for d in decls if d["doc"] or d["members"]]


def render(decl: dict, library: str, tag: str, path: str) -> str:
    out = [f"# {decl['name']} ({decl['kind']}, {library} library)", "",
           f"Source: flutter/flutter@{tag} {path}", "", decl["doc"], ""]
    for name, doc in decl["members"]:
        out += [f"## {decl['name']}.{name}", "", doc, ""]
    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    records = []
    for snap_id, tag in TAGS.items():
        count = 0
        for path in SOURCES:
            library = path.split("/")[-2]
            for decl in parse(fetch(tag, path)):
                rel = f"api/{library}/{decl['name']}.md"
                text = render(decl, library, tag, path)
                dest = SNAP_DIR / snap_id / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                records.append(
                    {
                        "doc_id": f"{snap_id}:{rel}",
                        "snapshot_id": snap_id,
                        "source": "flutter/flutter",
                        "tag": tag,
                        "source_path": path,
                        "path": rel,
                        "url": f"https://api.flutter.dev/flutter/{library}/{decl['name']}.html",
                        "kind": "api",
                        "title": f"{decl['name']} {decl['kind']}",
                        "members": len(decl["members"]),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "chars": len(text),
                    }
                )
                count += 1
        print(f"{snap_id:14} {tag:8} {count} API docs")

    MANIFEST.mkdir(parents=True, exist_ok=True)
    with (MANIFEST / "api_docs.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"total {len(records)} API docs -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
