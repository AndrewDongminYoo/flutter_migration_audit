"""Filtering by each doc's own version label (#13)."""

from fma.evalset import TARGET_VERSION, passes_label_filter, version_label

EDGE = "release/breaking-changes/default-systemuimode-edge-to-edge.md"


def test_label_precedence_footer_then_index_then_landed():
    # buttons.md: footer 2.0.0, index 1.20, landed 1.20.0-0.0.pre
    assert version_label("flutter-3.27:release/breaking-changes/buttons.md") == (2, 0)
    # the edge-to-edge doc: footer 3.27
    assert version_label(f"flutter-3.27:{EDGE}") == (3, 27)


def test_unlabeled_docs_have_no_label():
    assert version_label(f"flutter-3.24:{EDGE}") is None
    assert version_label("flutter-3.27:deployment/android.md") is None
    assert version_label("flutter-3.27:api/services/SystemUiMode.md") is None


def test_filter_keeps_labels_up_to_the_target_and_unlabeled_docs(index):
    assert TARGET_VERSION == (3, 27)
    by_doc = {}
    for c in index.chunks:
        by_doc.setdefault(c.doc_id, c)
    # every revision of the edge-to-edge doc passes: the label cannot tell them apart
    for snap in (
        "flutter-3.24",
        "flutter-3.27",
        "flutter-3.32",
        "flutter-3.35",
        "latest",
    ):
        assert passes_label_filter(by_doc[f"{snap}:{EDGE}"])
    later = [c for d, c in by_doc.items() if (version_label(d) or (0, 0)) > (3, 27)]
    assert later and not any(passes_label_filter(c) for c in later)
