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

UI_MODES = ("leanBack", "immersive", "immersiveSticky", "edgeToEdge", "manual")


def cli_scope() -> set[tuple[str, str | None]]:
    """(snapshot, kind) pairs that some evidence spec can request.

    Evidence is always filtered by snapshot and usually by kind, so the CLI's
    embedding index only needs these sections. A kind of None means every
    kind in that snapshot. Derived from the specs, so a new spec widens the
    scope automatically.
    """
    from .evidence import required_snapshot
    from .rules import E, mode_spec
    from .versions import target_releases

    scope: set[tuple[str, str | None]] = set()
    for target in target_releases():
        for spec in [*E.values(), *(mode_spec(m) for m in UI_MODES)]:
            snapshot = required_snapshot(spec, target)
            for kind in spec.kinds or [None]:
                scope.add((snapshot, kind))
    return scope


def cli_chunks(chunks: list[Chunk]) -> list[Chunk]:
    scope = cli_scope()
    return [
        c
        for c in chunks
        if (c.snapshot_id, c.kind) in scope or (c.snapshot_id, None) in scope
    ]


def get_retriever(kind: str = DEFAULT) -> Retriever:
    if kind not in RETRIEVERS:
        raise ValueError(f"unknown retriever: {kind}")
    if kind not in _CACHE:
        chunks = load_chunks()
        if kind == "bm25":
            _CACHE[kind] = Index(chunks)
        else:
            from .dense import Dense

            # Only the sections evidence can come from. The retrieval
            # comparison (scripts/compare_retrieval.py) embeds the whole corpus.
            _CACHE[kind] = Dense(cli_chunks(chunks))
    return _CACHE[kind]
