"""Compare retrieval methods on the 15 evaluation questions.

Methods (2 x 2):
  bm25                 keyword search over all snapshots
  embedding            dense search over all snapshots
  bm25+version         keyword search restricted to the target snapshot
  embedding+version    dense search restricted to the target snapshot

Scoring rules (gold chunk, wrong version) live in fma.evalset.

Outputs:
  results/retrieval/results.json   per question, per method
  results/retrieval/report.md      summary tables

Run: uv run --group eval scripts/compare_retrieval.py
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from fma.corpus import Chunk, Index, load_chunks
from fma.evalset import TARGET, doc_path, gold_sections, is_gold, is_wrong_version, load_questions

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "index"
OUT = ROOT / "results" / "retrieval"

MODEL = "BAAI/bge-small-en-v1.5"
TOP_K = 10


# --- dense retrieval ---------------------------------------------------------

class Dense:
    def __init__(self, chunks: list[Chunk]):
        from fastembed import TextEmbedding

        self.chunks = chunks
        self.model = TextEmbedding(MODEL)
        # The model reads at most 512 tokens; cut early to skip tokenizing the rest.
        texts = [f"{c.title}\n{c.heading}\n{c.text}"[:2500] for c in chunks]
        key = hashlib.sha256(("\0".join([MODEL] + [c.chunk_id for c in chunks] + texts)).encode()).hexdigest()[:16]
        path = CACHE / f"{MODEL.replace('/', '__')}-{key}.npy"
        if path.exists():
            self.matrix = np.load(path)
        else:
            started = time.time()
            vecs = np.array(list(self.model.passage_embed(texts, batch_size=64)), dtype=np.float32)
            self.matrix = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            CACHE.mkdir(parents=True, exist_ok=True)
            np.save(path, self.matrix)
            print(f"embedded {len(texts)} chunks in {time.time() - started:.0f}s -> {path.name}")

    def search(self, query: str, snapshots: set[str] | None = None, top_k: int = TOP_K):
        q = np.array(next(iter(self.model.query_embed([query]))), dtype=np.float32)
        q /= np.linalg.norm(q)
        scores = self.matrix @ q
        order = np.argsort(-scores)
        out = []
        for i in order:
            c = self.chunks[i]
            if snapshots is not None and c.snapshot_id not in snapshots:
                continue
            out.append((float(scores[i]), c))
            if len(out) == top_k:
                break
        return out


# --- evaluation ----------------------------------------------------------------

def same_text_as_gold_revision(chunks: list[Chunk], chunk: Chunk, q) -> bool:
    twin = next((c for c in chunks if c.snapshot_id == q.gold_snapshot
                 and doc_path(c) == doc_path(chunk) and c.heading == chunk.heading), None)
    return twin is not None and twin.normalized == chunk.normalized


def evaluate(questions, chunks, methods):
    rows = []
    for q in questions:
        sections = gold_sections(chunks, q)
        assert sections, f"{q.id}: no gold chunk in corpus"
        row = {"id": q.id, "question": q.question, "gold_snapshot": q.gold_snapshot,
               "gold_path": q.path, "gold_sections": sorted(sections), "methods": {}}
        for name, search in methods.items():
            ranked = search(q.question)
            rank = next((i for i, (_, c) in enumerate(ranked, 1) if is_gold(c, q)), None)
            top = ranked[0][1] if ranked else None
            wrong = bool(top and is_wrong_version(top, q, sections))
            row["methods"][name] = {
                "rank": rank,
                "top1": {"doc_id": top.doc_id, "heading": top.heading, "snapshot": top.snapshot_id} if top else None,
                "top1_wrong_version": wrong,
                # Same section, same text, different snapshot: only metadata
                # can tell these apart.
                "top1_identical_text": bool(wrong and same_text_as_gold_revision(chunks, top, q)),
                "top3": [f"{c.snapshot_id} {doc_path(c)} › {c.heading}" for _, c in ranked[:3]],
            }
        rows.append(row)
    return rows


def summarize(rows, names):
    summary = {}
    for name in names:
        ranks = [r["methods"][name]["rank"] for r in rows]
        n = len(ranks)
        summary[name] = {
            "hit@1": sum(1 for x in ranks if x == 1) / n,
            "hit@3": sum(1 for x in ranks if x and x <= 3) / n,
            "mrr@10": sum(1 / x for x in ranks if x) / n,
            "wrong_version@1": sum(r["methods"][name]["top1_wrong_version"] for r in rows) / n,
        }
    return summary


def render(rows, summary, names) -> str:
    out = ["# 검색 방식 비교", "",
           f"질문 {len(rows)}개, 목표 버전 스냅샷 `{TARGET}`, 임베딩 모델 `{MODEL}`, BM25는 `fma.corpus.Index`.",
           "정답은 정해진 판본의 정해진 문서에서 정답 문장이 들어 있는 섹션입니다. "
           "잘못된 판본@1은 1위 결과가 같은 문서의 같은 섹션이지만 판본이 다른 경우의 비율입니다.", "",
           "| 방식 | hit@1 | hit@3 | MRR@10 | 잘못된 판본@1 |", "| --- | --- | --- | --- | --- |"]
    for name in names:
        s = summary[name]
        out.append(f"| {name} | {s['hit@1']:.2f} | {s['hit@3']:.2f} | {s['mrr@10']:.2f} | {s['wrong_version@1']:.2f} |")
    out += ["", "## 질문별 정답 순위", "", "`-`는 10위 안에 정답이 없음을 뜻합니다. `*`는 1위가 내용이 다른 잘못된 판본, "
            "`=`는 1위가 내용은 같지만 판본이 다른 문서임을 뜻합니다.", "",
            "| 질문 | 정답 판본 | " + " | ".join(names) + " |",
            "| --- | --- | " + " | ".join("---" for _ in names) + " |"]
    for r in rows:
        cells = []
        for name in names:
            m = r["methods"][name]
            mark = ("=" if m["top1_identical_text"] else "*") if m["top1_wrong_version"] else ""
            cells.append((str(m["rank"]) if m["rank"] else "-") + mark)
        out.append(f"| {r['id']} | {r['gold_snapshot']} | " + " | ".join(cells) + " |")
    out += ["", "## 질문", ""]
    out += [f"- {r['id']}: {r['question']}" for r in rows]
    return "\n".join(out) + "\n"


def main() -> None:
    chunks = load_chunks(ROOT)
    questions = load_questions()
    bm25 = Index(chunks)
    dense = Dense(chunks)
    target = {TARGET}
    methods = {
        "bm25": lambda q: bm25.search(q, top_k=TOP_K),
        "embedding": lambda q: dense.search(q),
        "bm25+version": lambda q: bm25.search(q, snapshots=target, top_k=TOP_K),
        "embedding+version": lambda q: dense.search(q, snapshots=target),
    }
    rows = evaluate(questions, chunks, methods)
    summary = summarize(rows, list(methods))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(
        {"target": TARGET, "model": MODEL, "top_k": TOP_K, "summary": summary, "questions": rows},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(render(rows, summary, list(methods)), encoding="utf-8")
    for name, s in summary.items():
        print(f"{name:18} " + "  ".join(f"{k}={v:.2f}" for k, v in s.items()))


if __name__ == "__main__":
    main()
