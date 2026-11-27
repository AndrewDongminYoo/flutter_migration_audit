"""Choose the retriever that proposes evidence candidates.

Both retrievers take the same filters. Evidence is still accepted only after
`fma.evidence.accept` checks the snapshot, heading, and required sentence, so
the retriever affects which candidates are seen, not what counts as evidence.
"""

from __future__ import annotations

from collections.abc import Set
from typing import Protocol

from .corpus import Chunk, Index, load_chunks

RETRIEVERS = ("embedding", "bm25")
DEFAULT = "embedding"


class Retriever(Protocol):
    def search(
        self,
        query: str,
        snapshots: Set[str] | None = None,
        kinds: Set[str] | None = None,
        top_k: int = 10,
    ) -> list[tuple[float, Chunk]]: ...


_CACHE: dict[str, Retriever] = {}


def get_retriever(kind: str = DEFAULT) -> Retriever:
    if kind not in RETRIEVERS:
        raise ValueError(f"unknown retriever: {kind}")
    if kind not in _CACHE:
        chunks = load_chunks()
        if kind == "bm25":
            _CACHE[kind] = Index(chunks)
        else:
            from .dense import Dense

            _CACHE[kind] = Dense(chunks)
    return _CACHE[kind]
