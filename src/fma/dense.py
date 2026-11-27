"""Dense retrieval over the corpus with a local embedding model.

The comparison in docs/retrieval-comparison.md found that embedding search
with a version filter ranks the right revision first more often than BM25.
Embedding the whole corpus takes minutes on a laptop CPU, so the matrix is
cached under data/index/ and keyed by model, chunk ids, and chunk text.
"""

from __future__ import annotations

import hashlib
import sys
import time
from collections.abc import Set
from pathlib import Path

import numpy as np

from .corpus import ROOT, Chunk

MODEL = "BAAI/bge-small-en-v1.5"
CACHE = ROOT / "data" / "index"
# The model reads at most 512 tokens; cut early to skip tokenizing the rest.
MAX_CHARS = 2500


def passage_text(chunk: Chunk) -> str:
    return f"{chunk.title}\n{chunk.heading}\n{chunk.text}"[:MAX_CHARS]


def cache_path(chunks: list[Chunk], model: str = MODEL, cache_dir: Path = CACHE) -> Path:
    texts = [passage_text(c) for c in chunks]
    key = hashlib.sha256(("\0".join([model] + [c.chunk_id for c in chunks] + texts)).encode()).hexdigest()[:16]
    return cache_dir / f"{model.replace('/', '__')}-{key}.npy"


class Dense:
    def __init__(self, chunks: list[Chunk], model: str = MODEL, cache_dir: Path = CACHE,
                 build: bool = True):
        from fastembed import TextEmbedding

        self.chunks = chunks
        self.model_name = model
        self.path = cache_path(chunks, model, cache_dir)
        self.model = TextEmbedding(model)
        if self.path.exists():
            self.matrix = np.load(self.path)
        elif build:
            self.matrix = self._build()
        else:
            raise FileNotFoundError(self.path)

    def _build(self) -> np.ndarray:
        texts = [passage_text(c) for c in self.chunks]
        print(f"문서 {len(texts)}개 섹션을 임베딩합니다. 처음 한 번만 하며, 몇 분에서 15분 정도 걸립니다.",
              file=sys.stderr)
        started = time.time()
        vecs = np.array(list(self.model.passage_embed(texts, batch_size=64, parallel=0)), dtype=np.float32)
        matrix = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.save(self.path, matrix)
        print(f"임베딩 완료: {time.time() - started:.0f}초, {self.path.name}", file=sys.stderr)
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
