"""Build versioned snapshots of the Flutter docs for the retrieval corpus.

Each snapshot is the flutter/website tree at a pinned commit. A release
snapshot uses the last commit before the *next* stable release, so it shows
the docs as they were while that version was the current stable.

Outputs:
  data/raw/website.git            partial bare clone (ignored by git)
  data/raw/snapshots/<id>/...     extracted Markdown files (ignored by git)
  data/manifest/snapshots.json    snapshot metadata (committed)
  data/manifest/docs.jsonl        one record per extracted doc (committed)

Run: uv run --python 3.12 scripts/fetch_snapshots.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLONE = RAW / "website.git"
SNAP_DIR = RAW / "snapshots"
MANIFEST = ROOT / "data" / "manifest"

WEBSITE_REPO = "https://github.com/flutter/website.git"
RELEASES_JSON = (
    "https://storage.googleapis.com/flutter_infra_release/releases/releases_macos.json"
)

# id -> (version the snapshot represents, next stable release that closes the window)
RELEASE_SNAPSHOTS = {
    "flutter-3.24": ("3.24.0", "3.27.0"),
    "flutter-3.27": ("3.27.0", "3.29.0"),
}
# Pinned so the corpus is reproducible. Update deliberately.
LATEST_SNAPSHOT = ("latest", "a0b75bedb9557c5b71c81d8482a3073c05a0b7f3")

# Content roots moved in 2026 (sites/docs/...). Try both.
CONTENT_ROOTS = ("sites/docs/src/content/", "src/content/")
INCLUDE = (
    re.compile(r"^release/breaking-changes/[^/]+\.md$"),
    re.compile(r"^release/release-notes/release-notes-3\.(2[2-9]|[3-9]\d)\.\d+\.md$"),
    # Android and screen-layout guides: the evidence for system bar questions,
    # plus Android pages that look similar but are not about system bars.
    re.compile(r"^deployment/android\.md$"),
    re.compile(r"^ui/adaptive-responsive/[^/]+\.md$"),
    re.compile(r"^platform-integration/platform-adaptations\.md$"),
    re.compile(r"^platform-integration/android/[^/]+\.md$"),
    re.compile(r"^add-to-app/android/[^/]+\.md$"),
)

FOOTER_LANDED = re.compile(r"Landed in version:\s*([^\s<]+)")
FOOTER_STABLE = re.compile(r"(?:In )?[Ss]table release:\s*([^\s<]+)")
TITLE = re.compile(r"^title:\s*(.+)$", re.MULTILINE)
INDEX_SECTION = re.compile(r"^###\s+(.+)$")
INDEX_BULLET_REF = re.compile(r"^\s*[*-]\s+\[(.+?)\]\[([^\]]*)\]")
INDEX_BULLET_URL = re.compile(r"^\s*[*-]\s+\[(.+?)\]\((/release/breaking-changes/[^)#\s]+)")
REF_DEF = re.compile(r"^\[(.+?)\]:\s*(\S+)")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], check=True, capture_output=True, text=True
    ).stdout


def ensure_clone() -> None:
    if CLONE.exists():
        subprocess.run(["git", "-C", str(CLONE), "fetch", "-q", "origin", "main:main"], check=True)
    else:
        RAW.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "-q", "--bare", "--filter=blob:none", WEBSITE_REPO, str(CLONE)],
            check=True,
        )
    # Fetching blobs by id into a partial clone can leave the commit-graph
    # pointing at objects that are not local, which then fails later reads.
    for key in ("core.commitGraph", "fetch.writeCommitGraph", "gc.writeCommitGraph"):
        subprocess.run(["git", "-C", str(CLONE), "config", key, "false"], check=True)


def stable_release_dates() -> dict[str, str]:
    with urllib.request.urlopen(RELEASES_JSON, timeout=30) as resp:
        data = json.load(resp)
    return {
        r["version"]: r["release_date"]
        for r in data["releases"]
        if r["channel"] == "stable"
    }


def split_root(path: str) -> tuple[str, str] | None:
    for root in CONTENT_ROOTS:
        if path.startswith(root):
            return root, path[len(root):]
    return None


def parse_index(text: str) -> dict[str, str]:
    """Map breaking-change slug -> index section (e.g. 'Released in Flutter 3.27')."""
    refs = {}
    for line in text.splitlines():
        m = REF_DEF.match(line)
        if m:
            refs[m.group(1).lower()] = m.group(2)
    section, result = None, {}
    for line in text.splitlines():
        m = INDEX_SECTION.match(line)
        if m:
            section = m.group(1).strip()
            continue
        if section is None:
            continue
        url = None
        m = INDEX_BULLET_URL.match(line)
        if m:
            url = m.group(2)
        else:
            m = INDEX_BULLET_REF.match(line)
            if m:
                key = (m.group(2) or m.group(1)).lower()
                url = refs.get(key)
        if url and url.startswith("/release/breaking-changes/"):
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            result.setdefault(slug, section)
    return result


def section_version(section: str | None) -> str | None:
    if not section:
        return None
    m = re.search(r"Flutter\s+(\d+\.\d+)", section)
    return m.group(1) if m else None


def prefetch_blobs(oids: list[str]) -> None:
    """Fetch missing blobs in batches. Lazy per-file fetches in a partial
    clone are slow and fail intermittently."""
    for i in range(0, len(oids), 200):
        subprocess.run(
            ["git", "-C", str(CLONE), "-c", "fetch.negotiationAlgorithm=noop",
             "fetch", "-q", "origin", "--no-tags", "--no-write-fetch-head",
             *oids[i:i + 200]],
            check=True,
        )


def extract(snapshot_id: str, commit: str) -> list[dict]:
    selected, oids = [], []
    for line in git("ls-tree", "-r", commit).splitlines():
        meta, path = line.split("\t", 1)
        split = split_root(path)
        if split and any(p.match(split[1]) for p in INCLUDE):
            selected.append((path, split[1]))
            oids.append(meta.split()[2])
    prefetch_blobs(oids)

    index_rel = "release/breaking-changes/index.md"
    index_path = next(p for p, rel in selected if rel == index_rel)
    index_map = parse_index(git("show", f"{commit}:{index_path}"))

    commit_date = git("log", "-1", "--format=%cI", commit).strip()
    out_dir = SNAP_DIR / snapshot_id
    records = []
    for path, rel in selected:
        text = git("show", f"{commit}:{path}")
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

        slug = Path(rel).stem
        if rel == index_rel:
            kind = "breaking-change-index"
        elif rel.startswith("release/breaking-changes/"):
            kind = "breaking-change"
        elif rel.startswith("release/release-notes/"):
            kind = "release-notes"
        else:
            kind = "guide"
        title = TITLE.search(text)
        landed = FOOTER_LANDED.search(text)
        stable = FOOTER_STABLE.search(text)
        section = index_map.get(slug) if kind == "breaking-change" else None
        records.append(
            {
                "doc_id": f"{snapshot_id}:{rel}",
                "snapshot_id": snapshot_id,
                "source": "flutter/website",
                "commit": commit,
                "commit_date": commit_date,
                "path": rel,
                "url": "https://docs.flutter.dev/" + rel.removesuffix(".md").removesuffix("/index"),
                "kind": kind,
                "title": title.group(1).strip().strip("'\"") if title else None,
                "landed_in": landed.group(1) if landed else None,
                "stable_release_footer": stable.group(1) if stable else None,
                "index_section": section,
                "stable_release_index": section_version(section),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "chars": len(text),
            }
        )
    return records


def main() -> None:
    ensure_clone()
    dates = stable_release_dates()

    snapshots = []
    for snap_id, (version, next_version) in RELEASE_SNAPSHOTS.items():
        cutoff = dates[next_version]
        commit = git("rev-list", "-1", f"--before={cutoff}", "main").strip()
        snapshots.append(
            {
                "snapshot_id": snap_id,
                "represents": version,
                "released": dates[version],
                "window_closes": f"{next_version} released {cutoff}",
                "commit": commit,
            }
        )
    snapshots.append(
        {
            "snapshot_id": LATEST_SNAPSHOT[0],
            "represents": "current docs (pinned)",
            "released": None,
            "window_closes": None,
            "commit": LATEST_SNAPSHOT[1],
        }
    )

    all_records = []
    for snap in snapshots:
        snap["commit_date"] = git("log", "-1", "--format=%cI", snap["commit"]).strip()
        records = extract(snap["snapshot_id"], snap["commit"])
        snap["doc_count"] = len(records)
        all_records.extend(records)
        print(f"{snap['snapshot_id']:14} {snap['commit'][:10]} {snap['commit_date']}  {len(records)} docs")

    MANIFEST.mkdir(parents=True, exist_ok=True)
    (MANIFEST / "snapshots.json").write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (MANIFEST / "docs.jsonl").open("w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"total {len(all_records)} docs -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
