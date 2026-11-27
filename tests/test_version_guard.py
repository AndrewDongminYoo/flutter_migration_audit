"""Version guard: evidence must come from the docs of the target version.

The edge-to-edge breaking change doc exists in three revisions that differ by
a few sentences. Plain BM25 over all snapshots ranks the wrong revision first
for these queries; the snapshot filter plus `accept` keeps it out.
"""

import pytest

from fma.evidence import LATEST, VersionMismatch, accept, resolve
from fma.rules import E
from fma.versions import release_for

TARGET = release_for("3.27.0")
EDGE_DOC = "release/breaking-changes/default-systemuimode-edge-to-edge.md"


def chunk(index, snapshot, heading):
    return next(c for c in index.chunks
                if c.doc_id == f"{snapshot}:{EDGE_DOC}" and c.heading == heading)


@pytest.mark.parametrize("key", ["opt_out_works", "target_default", "already_migrated"])
def test_unfiltered_search_ranks_a_wrong_version_first(index, key):
    spec = E[key]
    top = index.search(spec.query, kinds=spec.kinds, top_k=3)
    snapshots = [c.snapshot_id for _, c in top]
    # The trap this project is about: all three revisions score within a few
    # percent, and the top hit is not the 3.27 revision.
    assert snapshots[0] != TARGET.snapshot_id
    assert set(snapshots) == {"flutter-3.24", "flutter-3.27", LATEST}
    assert top[2][0] / top[0][0] > 0.9


def test_wrong_revision_of_opt_out_text_is_rejected(index):
    latest = chunk(index, LATEST, "Migration guide")
    assert "This modified style opts your app out" in latest.normalized  # same sentence...
    with pytest.raises(VersionMismatch):
        accept(latest, E["opt_out_works"], TARGET)  # ...wrong version


def test_prerelease_revision_is_rejected(index):
    early = chunk(index, "flutter-3.24", "Context")
    with pytest.raises(VersionMismatch):
        accept(early, E["already_migrated"], TARGET)


def test_filtered_evidence_keeps_target_wording(index):
    ev = resolve(E["opt_out_works"], TARGET, index)
    assert ev.snapshot_id == "flutter-3.27"
    assert "Android SDK 15+." in ev.quote
    # The later revision narrows this to "SDK 15" because Android 16 removed
    # the opt-out. Citing it here would change the answer.
    latest = chunk(index, LATEST, "Migration guide")
    assert "Android SDK 15+." not in latest.normalized
    assert "Android SDK 15." in latest.normalized


def test_android16_text_never_reaches_target_evidence(index):
    for key, spec in E.items():
        if spec.snapshot != "target":
            continue
        ev = resolve(spec, TARGET, index)
        if ev:
            assert ev.snapshot_id == TARGET.snapshot_id, key
            assert "Android 16" not in ev.quote and "API 36" not in ev.quote, key


def test_later_correction_is_explicit_and_labelled(index):
    ev = resolve(E["opt_out_night"], TARGET, index)
    assert ev.snapshot_id == LATEST and ev.later_correction
    assert "목표 버전 이후" in ev.source_label()
    # The 3.27 revision has no such instruction, which is why it is a correction.
    target_text = " ".join(c.normalized for c in index.chunks if c.doc_id == f"flutter-3.27:{EDGE_DOC}")
    assert "night mode" not in target_text


def test_api_doc_revision_differs_by_version(index):
    def section(snapshot):
        return next(c for c in index.chunks
                    if c.doc_id == f"{snapshot}:api/services/SystemUiMode.md"
                    and c.heading == "SystemUiMode.immersiveSticky").normalized
    assert "API 35" not in section("flutter-3.24")
    assert "API 35" in section("flutter-3.27") and "API 36" not in section("flutter-3.27")
    assert "API 36" in section(LATEST)
