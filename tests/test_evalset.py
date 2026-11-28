import json
from collections import Counter

from fma.corpus import ROOT
from fma.evalset import (
    QUESTIONS,
    TARGET,
    doc_path,
    gold_sections,
    is_gold,
    load_questions,
    passes_label_filter,
)

RESULTS = ROOT / "results" / "retrieval" / "results.json"


def test_question_set_shape():
    qs = load_questions()
    assert len(qs) == 15
    assert len({q.id for q in qs}) == 15
    assert Counter(q.snapshot for q in qs) == {"target": 14, "later_correction": 1}
    assert QUESTIONS.read_text().count("\n") == 15


def test_every_question_has_gold_only_in_its_snapshot(index):
    for q in load_questions():
        gold = [c for c in index.chunks if is_gold(c, q)]
        assert gold, q.id
        assert {c.snapshot_id for c in gold} == {q.gold_snapshot}, q.id
        assert gold_sections(index.chunks, q), q.id


def test_target_questions_have_lookalike_revisions(index):
    """Most target questions point at a doc that also exists in other
    snapshots, so retrieval can return the wrong revision."""
    lookalike = 0
    for q in load_questions():
        if q.snapshot != "target":
            continue
        other = {c.snapshot_id for c in index.chunks if doc_path(c) == q.path} - {
            TARGET
        }
        lookalike += bool(other)
    assert lookalike == 14


def test_committed_bm25_results_are_reproducible(index):
    data = json.loads(RESULTS.read_text())
    by_id = {r["id"]: r for r in data["questions"]}
    for q in load_questions():
        for name, snaps in (("bm25", None), ("bm25+version", {TARGET})):
            ranked = index.search(q.question, snapshots=snaps, top_k=data["top_k"])
            rank = next(
                (i for i, (_, c) in enumerate(ranked, 1) if is_gold(c, q)), None
            )
            assert by_id[q.id]["methods"][name]["rank"] == rank, (q.id, name)
        ranked = [
            (s, c)
            for s, c in index.search(q.question, top_k=len(index.chunks))
            if passes_label_filter(c)
        ][: data["top_k"]]
        rank = next((i for i, (_, c) in enumerate(ranked, 1) if is_gold(c, q)), None)
        assert by_id[q.id]["methods"]["bm25+label"]["rank"] == rank, q.id
