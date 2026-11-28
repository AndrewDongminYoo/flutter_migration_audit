"""Extract versioned API docs from Flutter framework source.

api.flutter.dev only serves the current release, so the API pages for older
versions are rebuilt from the dartdoc comments (`///`) in flutter/flutter at
each release tag. Each public top-level declaration (class, enum, mixin,
extension) becomes one Markdown doc, with its documented members as sections.

`{@macro name}` is replaced with the matching `{@template name}` block, as
dartdoc does. Templates are collected from every Dart file under
packages/flutter/lib at the same tag. Macros whose template is defined
elsewhere (for example in dart:ui) are left in place and listed in the
manifest as `unresolved_macros`.

Outputs:
  data/raw/flutter.git                              shallow partial clone (ignored by git)
  data/raw/snapshots/<id>/api/<library>/<Name>.md   (ignored by git)
  data/manifest/api_docs.jsonl                      (committed)

Run: uv run --python 3.12 scripts/fetch_api_docs.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "raw" / "snapshots"
CLONE = ROOT / "data" / "raw" / "flutter.git"
FLUTTER_REPO = "https://github.com/flutter/flutter.git"
TEMPLATE_ROOT = "packages/flutter/lib"
MANIFEST = ROOT / "data" / "manifest"

# Same snapshot ids as fetch_snapshots.py. API docs ship with the release, so
# each id maps to the release tag itself. `latest` is pinned to the stable
# release that was current when the corpus was built.
TAGS = {
    "flutter-3.24": "3.24.0",
    "flutter-3.27": "3.27.0",
    "flutter-3.32": "3.32.0",
    "flutter-3.35": "3.35.0",
    "latest": "3.50.1",
}

SOURCES = (
    "packages/flutter/lib/src/services/system_chrome.dart",
    "packages/flutter/lib/src/widgets/safe_area.dart",
    "packages/flutter/lib/src/widgets/media_query.dart",
    "packages/flutter/lib/src/widgets/annotated_region.dart",
    "packages/flutter/lib/src/material/app_bar.dart",
)


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
DIRECTIVE = re.compile(
    r"\{@(?:tool|end-tool|youtube|animation|dartpad|template|endtemplate)[^}]*\}"
)
TEMPLATE = re.compile(
    r"\{@template\s+([\w.\-]+)\}[ \t]*\n?(.*?)\{@endtemplate\}", re.DOTALL
)
MACRO = re.compile(r"\{@macro\s+([\w.\-]+)\}")
MAX_MACRO_DEPTH = 5
# Headings inside a doc comment are pushed below the member headings.
DOC_HEADING = re.compile(r"^(#{1,4}) ", re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], check=True, capture_output=True, text=True
    ).stdout


def ensure_tags(tags: list[str]) -> None:
    """Shallow, blob-less fetch of each release tag: only the tagged commit
    and its trees, so the clone stays small."""
    if not CLONE.exists():
        CLONE.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(CLONE)], check=True)
        git("remote", "add", "origin", FLUTTER_REPO)
        git("config", "remote.origin.promisor", "true")
        git("config", "remote.origin.partialclonefilter", "blob:none")
        git("config", "core.commitGraph", "false")
    for tag in tags:
        if (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(CLONE),
                    "rev-parse",
                    "-q",
                    "--verify",
                    f"refs/tags/{tag}",
                ],
                capture_output=True,
            ).returncode
            != 0
        ):
            git(
                "fetch",
                "-q",
                "--depth",
                "1",
                "--filter=blob:none",
                "origin",
                f"refs/tags/{tag}:refs/tags/{tag}",
            )


def read_tree(tag: str, root: str) -> dict[str, str]:
    """Return {path: text} for Dart files under `root`, fetching blobs in batches."""
    entries = [
        line.split("\t", 1)
        for line in git("ls-tree", "-r", tag, "--", root).splitlines()
    ]
    entries = [
        (meta.split()[2], path) for meta, path in entries if path.endswith(".dart")
    ]
    oids = [oid for oid, _ in entries]
    for i in range(0, len(oids), 300):
        subprocess.run(
            [
                "git",
                "-C",
                str(CLONE),
                "-c",
                "fetch.negotiationAlgorithm=noop",
                "fetch",
                "-q",
                "origin",
                "--no-tags",
                "--no-write-fetch-head",
                *oids[i : i + 300],
            ],
            check=True,
        )
    return {path: git("cat-file", "blob", oid) for oid, path in entries}


def doc_blocks(source: str):
    """Yield the text of each run of consecutive `///` lines."""
    block: list[str] = []
    for raw in source.splitlines() + [""]:
        stripped = raw.strip()
        if stripped.startswith("///"):
            block.append(stripped[3:].removeprefix(" "))
        elif block:
            yield "\n".join(block)
            block = []


def collect_templates(files: dict[str, str]) -> dict[str, str]:
    templates: dict[str, str] = {}
    for source in files.values():
        for block in doc_blocks(source):
            for m in TEMPLATE.finditer(block):
                templates.setdefault(m.group(1), m.group(2).strip())
    return templates


def expand_macros(
    text: str, templates: dict[str, str], unresolved: set[str], depth: int = 0
) -> str:
    def replace(m: re.Match) -> str:
        name = m.group(1)
        if name not in templates or depth >= MAX_MACRO_DEPTH:
            unresolved.add(name)
            return m.group(0)
        return expand_macros(templates[name], templates, unresolved, depth + 1)

    return MACRO.sub(replace, text)


GENERIC_ARGS = re.compile(r"<[^<>]*>")


def member_name(decl: str) -> str | None:
    # Drop type arguments first so `Map<String, dynamic> _toMap()` does not
    # match `String,` as a field name.
    prev = None
    while prev != decl:
        prev, decl = decl, GENERIC_ARGS.sub("", decl)
    m = MEMBER_ACCESSOR.search(decl) or MEMBER_NAME.search(decl)
    return m.group(1) if m else None


def clean(
    lines: list[str],
    templates: dict[str, str] | None = None,
    unresolved: set[str] | None = None,
) -> str:
    text = "\n".join(line[3:].removeprefix(" ") for line in lines)
    if templates is not None:
        text = expand_macros(
            text, templates, unresolved if unresolved is not None else set()
        )
    text = DOC_HEADING.sub(r"##\1 ", text)
    return DIRECTIVE.sub("", text).strip()


def parse(source: str, templates: dict[str, str] | None = None) -> list[dict]:
    """Return [{name, kind, doc, members: [(name, doc)], unresolved}] for public declarations."""
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
                current = {
                    "name": m.group(2),
                    "kind": m.group(1).split()[0],
                    "members": [],
                    "unresolved": set(),
                }
                current["doc"] = clean(pending, templates, current["unresolved"])
                decls.append(current)
            elif (
                m
                or stripped.startswith(("typedef", "const", "final"))
                or "(" in stripped
            ):
                current = None
            pending = []
            continue
        if current is not None and pending and indent == 2:
            name = member_name(stripped)
            if name and not name.startswith("_"):
                current["members"].append(
                    (name, clean(pending, templates, current["unresolved"]))
                )
        pending = []
    return [d for d in decls if d["doc"] or d["members"]]


def render(decl: dict, library: str, tag: str, path: str) -> str:
    out = [
        f"# {decl['name']} ({decl['kind']}, {library} library)",
        "",
        f"Source: flutter/flutter@{tag} {path}",
        "",
        decl["doc"],
        "",
    ]
    for name, doc in decl["members"]:
        out += [f"## {decl['name']}.{name}", "", doc, ""]
    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    records = []
    ensure_tags(list(TAGS.values()))
    for snap_id, tag in TAGS.items():
        count = 0
        files = read_tree(tag, TEMPLATE_ROOT)
        templates = collect_templates(files)
        unresolved_total: set[str] = set()
        for path in SOURCES:
            library = path.split("/")[-2]
            for decl in parse(files[path], templates):
                unresolved_total |= decl["unresolved"]
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
                        "unresolved_macros": sorted(decl["unresolved"]),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "chars": len(text),
                    }
                )
                count += 1
        print(
            f"{snap_id:14} {tag:8} {count} API docs, {len(templates)} templates, "
            f"{len(unresolved_total)} unresolved macros"
        )

    MANIFEST.mkdir(parents=True, exist_ok=True)
    with (MANIFEST / "api_docs.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"total {len(records)} API docs -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
