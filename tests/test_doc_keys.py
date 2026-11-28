"""Docs whose path changed between snapshots are one document (#17)."""

import json

from fma.corpus import ROOT
from fma.evalset import Question, is_wrong_version

DOCS = ROOT / "data" / "manifest" / "docs.jsonl"
OLD = "platform-integration/platform-adaptations.md"
NEW = "ui/adaptive-responsive/platform-adaptations.md"


def docs():
    return [json.loads(line) for line in DOCS.open(encoding="utf-8")]


def test_every_website_doc_has_a_key():
    assert all(d.get("doc_key", "").startswith("/") for d in docs())


def test_a_moved_doc_keeps_its_key():
    keys = {(d["snapshot_id"], d["path"]): d["doc_key"] for d in docs()}
    assert keys[("flutter-3.24", OLD)] == keys[("flutter-3.27", NEW)]
    assert keys[("flutter-3.27", NEW)] == "/ui/adaptive-responsive/platform-adaptations"


def test_an_unmoved_doc_is_keyed_by_its_url():
    for d in docs():
        if d["path"] == "deployment/android.md":
            assert d["doc_key"] == "/deployment/android"


def test_the_moved_doc_counts_as_a_wrong_version(index):
    q = Question("x", "?", "target", NEW, "", None)
    old = [c for c in index.chunks if c.doc_id == f"flutter-3.24:{OLD}"]
    new = {c.heading for c in index.chunks if c.doc_id == f"flutter-3.27:{NEW}"}
    shared = [c for c in old if c.heading in new]
    assert shared, "the two revisions share section headings"
    assert all(is_wrong_version(c, q, new) for c in shared)
