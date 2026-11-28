"""Dense retrieval over the corpus with a local embedding model.

The comparison in docs/retrieval-comparison.md found that embedding search
with a version filter ranks the right revision first more often than BM25.
Embedding the whole corpus takes minutes on a laptop CPU, so the matrix is
cached under data/index/ and keyed by model, chunk ids, and chunk text. The
CLI index is cached in one part per snapshot, so a new snapshot only adds a
part.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from collections.abc import Set
from pathlib import Path

import numpy as np

from .corpus import ROOT, Chunk
from .korean import josa

MODEL = "BAAI/bge-small-en-v1.5"
CACHE = ROOT / "data" / "index"
# The model reads at most 512 tokens; cut early to skip tokenizing the rest.
MAX_CHARS = 2500
# ONNX Runtime uses every core by default. Set FMA_EMBED_THREADS to leave
# room for other work on a busy machine; it changes speed, not results.
THREADS_ENV = "FMA_EMBED_THREADS"


def embed_threads() -> int | None:
    value = os.environ.get(THREADS_ENV, "").strip()
    return int(value) if value.isdigit() and int(value) > 0 else None


def passage_text(chunk: Chunk) -> str:
    return f"{chunk.title}\n{chunk.heading}\n{chunk.text}"[:MAX_CHARS]


def cache_path(
    chunks: list[Chunk], model: str = MODEL, cache_dir: Path = CACHE
) -> Path:
    texts = [passage_text(c) for c in chunks]
    key = hashlib.sha256(
        ("\0".join([model] + [c.chunk_id for c in chunks] + texts)).encode()
    ).hexdigest()[:16]
    return cache_dir / f"{model.replace('/', '__')}-{key}.npy"


def index_parts(chunks: list[Chunk], by_snapshot: bool) -> list[list[int]]:
    """Row numbers of each cached part. Split by snapshot, a new snapshot only
    adds a part, and the parts for the other snapshots are reused."""
    if not by_snapshot:
        return [list(range(len(chunks)))]
    parts: dict[str, list[int]] = {}
    for i, c in enumerate(chunks):
        parts.setdefault(c.snapshot_id, []).append(i)
    return list(parts.values())


class Dense:
    def __init__(
        self,
        chunks: list[Chunk],
        model: str = MODEL,
        cache_dir: Path = CACHE,
        build: bool = True,
        by_snapshot: bool = False,
    ):
        self.chunks = chunks
        self.model_name = model
        self.parts = index_parts(chunks, by_snapshot)
        self.paths = [
            cache_path([chunks[i] for i in rows], model, cache_dir)
            for rows in self.parts
        ]
        missing = [p for p in self.paths if not p.exists()]
        # Check the index before loading the model: loading may download it,
        # and a caller that only wants an existing index must not pay for that.
        if missing and not build:
            raise FileNotFoundError(missing[0])

        from fastembed import TextEmbedding

        self.model = TextEmbedding(model, threads=embed_threads())
        matrices = [
            np.load(path) if path.exists() else self._build(rows, path)
            for rows, path in zip(self.parts, self.paths, strict=False)
        ]
        self.matrix = np.empty((len(chunks), matrices[0].shape[1]), dtype=np.float32)
        for rows, matrix in zip(self.parts, matrices, strict=False):
            self.matrix[rows] = matrix

    def _build(self, rows: list[int], path: Path) -> np.ndarray:
        texts = [passage_text(self.chunks[i]) for i in rows]
        snapshots = sorted({self.chunks[i].snapshot_id for i in rows})
        label = snapshots[0] if len(snapshots) == 1 else "전체"
        threads = embed_threads()
        print(
            f"문서 {josa(f'{len(texts)}개 섹션({label})', '을/를')} 임베딩합니다. 처음 한 번만 하며 몇 분 걸립니다"
            + (f" (스레드 {threads}개)." if threads else "."),
            file=sys.stderr,
        )
        started = time.time()
        vecs = np.array(
            list(self.model.passage_embed(texts, batch_size=64)), dtype=np.float32
        )
        matrix = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, matrix)
        print(
            f"임베딩 완료: {time.time() - started:.0f}초, {path.name}",
            file=sys.stderr,
        )
        return matrix

    def search(
        self,
        query: str,
        snapshots: Set[str] | None = None,
        kinds: Set[str] | None = None,
        top_k: int = 10,
    ) -> list[tuple[float, Chunk]]:
        q = np.array(next(iter(self.model.query_embed([query]))), dtype=np.float32)
        q /= np.linalg.norm(q)
        scores = self.matrix @ q
        out = []
        for i in np.argsort(-scores, kind="stable"):
            c = self.chunks[i]
            if snapshots is not None and c.snapshot_id not in snapshots:
                continue
            if kinds is not None and c.kind not in kinds:
                continue
            out.append((float(scores[i]), c))
            if len(out) == top_k:
                break
        return out
