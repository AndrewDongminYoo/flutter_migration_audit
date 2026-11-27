"""Evaluation questions and the gold rule used to score retrieval.

A hit is a chunk from the gold doc, in the gold snapshot, that contains the
gold sentence (and has the gold heading, if given). A "wrong version" result
is a chunk from the same doc and section in a different snapshot: the text
looks right, but it is the wrong revision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .corpus import ROOT, Chunk, normalize
from .evidence import LATEST

QUESTIONS = ROOT / "eval" / "questions.jsonl"
TARGET = "flutter-3.27"


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


def matches_text(chunk: Chunk, q: Question) -> bool:
    if doc_path(chunk) != q.path:
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
        and doc_path(chunk) == q.path
        and (chunk.heading in sections or matches_text(chunk, q))
    )
