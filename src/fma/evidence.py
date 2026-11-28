"""Turn an evidence spec into a cited quote from the right version of the docs.

A spec says which snapshot the evidence must come from and which sentence
must be in it. Retrieval proposes candidates; `resolve` accepts only a chunk
from the required snapshot that contains the sentence. A chunk from another
version is rejected even when its text is almost the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .corpus import Chunk, normalize
from .versions import Release

if TYPE_CHECKING:
    from .retrieval import Retriever

LATEST = "latest"


class VersionMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    key: str
    query: str
    must_contain: str
    # "target": docs of the version being upgraded to.
    # "later_correction": a fix published after the target release. Used only
    # when a later revision corrects an omission, and labelled as such.
    snapshot: str = "target"
    kinds: frozenset[str] | None = None
    heading: str | None = None


@dataclass(frozen=True)
class Evidence:
    spec_key: str
    quote: str
    title: str
    heading: str
    url: str
    snapshot_id: str
    revision: str
    later_correction: bool
    rank: int  # 1-based rank of the accepted chunk among the candidates

    def source_label(self) -> str:
        m = re.fullmatch(r"flutter-(\d+\.\d+)", self.snapshot_id)
        version = f"Flutter {m.group(1)} 문서" if m else "현재 문서"
        repo = (
            "flutter/flutter"
            if not re.fullmatch(r"[0-9a-f]{40}", self.revision)
            else "flutter/website"
        )
        rev = self.revision[:10]
        label = f"{version} ({repo} {rev})"
        if self.later_correction:
            label += " · 목표 버전 이후에 고쳐진 내용"
        return label


def required_snapshot(spec: Spec, target: Release) -> str:
    if spec.snapshot == "target":
        return target.snapshot_id
    if spec.snapshot == "later_correction":
        return LATEST
    raise ValueError(f"unknown snapshot policy: {spec.snapshot}")


def accept(chunk: Chunk, spec: Spec, target: Release) -> bool:
    """Raise VersionMismatch if the chunk is from the wrong snapshot."""
    want = required_snapshot(spec, target)
    if chunk.snapshot_id != want:
        raise VersionMismatch(
            f"{spec.key}: {chunk.doc_id} 는 {chunk.snapshot_id} 문서입니다. "
            f"필요한 문서: {want}"
        )
    if spec.heading and chunk.heading != spec.heading:
        return False
    return normalize(spec.must_contain).lower() in chunk.normalized.lower()


MD_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
MD_INLINE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# A bullet list item marker at the start of a line. Numbered lists stay
# whole: their items read as one argument (the 3.27 opt-out note is
# "1. ... temporary. 2. ... migrate before the OS removes the opt-out").
LIST_ITEM = re.compile(r"^\s*[*-]\s+", re.M)


def quote_for(chunk: Chunk, must_contain: str) -> str:
    """Return the paragraph that contains the required sentence, with
    Markdown link syntax reduced to its label. In a list (release notes are
    one long list), return only the item that contains it."""
    needle = normalize(must_contain).lower()
    for para in re.split(r"\n\s*\n", chunk.text):
        parts = LIST_ITEM.split(para) if LIST_ITEM.match(para) else [para]
        for part in parts:
            flat = normalize(part)
            if needle in flat.lower():
                return MD_INLINE_LINK.sub(r"\1", MD_REF_LINK.sub(r"\1", flat))
    return normalize(must_contain)


def resolve(
    spec: Spec, target: Release, index: Retriever, top_k: int = 20
) -> Evidence | None:
    snapshot = required_snapshot(spec, target)
    candidates = index.search(
        spec.query, snapshots={snapshot}, kinds=spec.kinds, top_k=top_k
    )
    for rank, (_, chunk) in enumerate(candidates, start=1):
        if accept(chunk, spec, target):
            return Evidence(
                spec_key=spec.key,
                quote=quote_for(chunk, spec.must_contain),
                title=chunk.title,
                heading=chunk.heading,
                url=chunk.url,
                snapshot_id=chunk.snapshot_id,
                revision=chunk.revision,
                later_correction=spec.snapshot == "later_correction",
                rank=rank,
            )
    return None
