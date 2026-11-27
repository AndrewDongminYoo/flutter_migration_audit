"""Load the versioned corpus, split it into sections, and search it.

Search is plain BM25. A snapshot filter restricts which versions of the
docs can be returned; that filter is the "version filter" this project
compares against unfiltered retrieval.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Set
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ("docs.jsonl", "api_docs.jsonl")
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
HEADING = re.compile(r"^(#{1,3}) (.+)$", re.MULTILINE)
TOKEN = re.compile(r"[a-z0-9]+")


class CorpusMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    snapshot_id: str
    kind: str
    title: str
    heading: str
    text: str
    url: str
    revision: str  # website commit or framework tag

    @cached_property
    def normalized(self) -> str:
        return normalize(self.text)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def split_sections(text: str) -> list[tuple[str, str]]:
    text = FRONTMATTER.sub("", text)
    marks = list(HEADING.finditer(text))
    sections = []
    if not marks or marks[0].start() > 0:
        sections.append(("", text[: marks[0].start()] if marks else text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections.append((m.group(2).strip(), text[m.start() : end]))
    return [(h, t) for h, t in sections if t.strip()]


def load_chunks(root: Path = ROOT) -> list[Chunk]:
    chunks = []
    for manifest in MANIFESTS:
        path = root / "data" / "manifest" / manifest
        if not path.exists():
            raise CorpusMissing(f"{path} 가 없습니다.")
        for line in path.open(encoding="utf-8"):
            doc = json.loads(line)
            source = (
                root / "data" / "raw" / "snapshots" / doc["snapshot_id"] / doc["path"]
            )
            if not source.exists():
                raise CorpusMissing(
                    f"{source} 가 없습니다. scripts/fetch_snapshots.py와 "
                    "scripts/fetch_api_docs.py로 코퍼스를 먼저 만드세요."
                )
            for i, (heading, text) in enumerate(
                split_sections(source.read_text(encoding="utf-8"))
            ):
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc['doc_id']}#{i}",
                        doc_id=doc["doc_id"],
                        snapshot_id=doc["snapshot_id"],
                        kind=doc["kind"],
                        title=doc.get("title") or doc["path"],
                        heading=heading,
                        text=text,
                        url=doc["url"],
                        revision=doc.get("commit") or doc.get("tag"),
                    )
                )
    return chunks


class Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.2, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(c.title + " " + c.text)) for c in chunks]
        self.lengths = [sum(tf.values()) for tf in self.tf]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter()
        for tf in self.tf:
            df.update(tf.keys())
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(
        self,
        query: str,
        snapshots: Set[str] | None = None,
        kinds: Set[str] | None = None,
        top_k: int = 10,
    ) -> list[tuple[float, Chunk]]:
        terms = tokenize(query)
        scored = []
        for i, chunk in enumerate(self.chunks):
            if snapshots is not None and chunk.snapshot_id not in snapshots:
                continue
            if kinds is not None and chunk.kind not in kinds:
                continue
            tf, length = self.tf[i], self.lengths[i]
            score = 0.0
            for t in terms:
                f = tf.get(t)
                if f:
                    norm = f + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                    score += self.idf[t] * f * (self.k1 + 1) / norm
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: (-x[0], x[1].chunk_id))
        return scored[:top_k]


_INDEX: Index | None = None


def default_index() -> Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = Index(load_chunks())
    return _INDEX
