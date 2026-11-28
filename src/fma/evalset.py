"""Evaluation questions and the gold rule used to score retrieval.

A hit is a chunk from the gold doc, in the gold snapshot, that contains the
gold sentence (and has the gold heading, if given). A "wrong version" result
is a chunk from the same doc and section in a different snapshot: the text
looks right, but it is the wrong revision. "The same doc" is the manifest's
doc_key, so a doc that moved between snapshots still counts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .corpus import MANIFESTS, ROOT, Chunk, normalize
from .evidence import LATEST

QUESTIONS = ROOT / "eval" / "questions.jsonl"
TARGET = "flutter-3.27"
TARGET_VERSION = (3, 27)


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    snapshot: str  # "target" or "later_correction"
    path: str
    must_contain: str
    heading: str | None

    @property
    def gold_snapshot(self) -> str:
        return TARGET if self.snapshot == "target" else LATEST


def load_questions(path: Path = QUESTIONS) -> list[Question]:
    out = []
    for line in path.open(encoding="utf-8"):
        q = json.loads(line)
        g = q["gold"]
        out.append(
            Question(
                q["id"],
                q["question"],
                g["snapshot"],
                g["path"],
                g["must_contain"],
                g.get("heading"),
            )
        )
    return out


def doc_path(chunk: Chunk) -> str:
    return chunk.doc_id.split(":", 1)[1]


@cache
def _docs() -> dict[str, dict]:
    docs = {}
    for manifest in MANIFESTS:
        path = ROOT / "data" / "manifest" / manifest
        for line in path.open(encoding="utf-8"):
            doc = json.loads(line)
            docs[doc["doc_id"]] = doc
    return docs


@cache
def _doc_keys() -> dict[str, str]:
    return {i: d.get("doc_key") or d["path"] for i, d in _docs().items()}


# A doc's own version label, in the order the evaluation trusts them: the
# footer's stable release, the breaking-change index section, then the
# footer's "Landed in version" (often a pre-release). Guides, release notes,
# and API docs carry none.
LABEL_FIELDS = ("stable_release_footer", "stable_release_index", "landed_in")
MAJOR_MINOR = re.compile(r"v?(\d+)\.(\d+)")


def version_label(doc_id: str) -> tuple[int, int] | None:
    doc = _docs().get(doc_id, {})
    for field in LABEL_FIELDS:
        m = MAJOR_MINOR.match(doc.get(field) or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def passes_label_filter(chunk: Chunk, target: tuple[int, int] = TARGET_VERSION) -> bool:
    """The label filter: keep a doc whose label is at most the target
    version, in any snapshot. A doc without a label is kept: nothing says
    it is later. Unlike the snapshot filter, this cannot tell revisions of
    one doc apart, since they share a label."""
    label = version_label(chunk.doc_id)
    return label is None or label <= target


def question_key(q: Question) -> str:
    """The doc_key of the question's gold doc."""
    return _doc_keys().get(f"{q.gold_snapshot}:{q.path}", q.path)


def matches_text(chunk: Chunk, q: Question) -> bool:
    if chunk.doc_key != question_key(q):
        return False
    if q.heading and chunk.heading != q.heading:
        return False
    return normalize(q.must_contain).lower() in chunk.normalized.lower()


def is_gold(chunk: Chunk, q: Question) -> bool:
    return chunk.snapshot_id == q.gold_snapshot and matches_text(chunk, q)


def gold_sections(chunks: list[Chunk], q: Question) -> set[str]:
    return {c.heading for c in chunks if is_gold(c, q)}


def is_wrong_version(chunk: Chunk, q: Question, sections: set[str]) -> bool:
    return (
        chunk.snapshot_id != q.gold_snapshot
        and chunk.doc_key == question_key(q)
        and (chunk.heading in sections or matches_text(chunk, q))
    )
