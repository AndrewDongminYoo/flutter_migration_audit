"""The CLI's default retriever is embedding search. Evidence is accepted only
after the snapshot, heading, and sentence checks, so switching retrievers
must not change any judgement or quote."""

import os
from pathlib import Path

import pytest

from fma import cli
from fma.cli import main
from fma.evidence import resolve
from fma.retrieval import cli_chunks, cli_dense, cli_scope
from fma.rules import all_specs, audit
from fma.signals import discover
from fma.versions import target_releases

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
# Every (target release, spec) pair the rules can request.
CASES = [(t, s) for t in target_releases() for s in all_specs(t)]
# Set in CI, where the embedding tests must run instead of skipping.
REQUIRE_INDEX_ENV = "FMA_REQUIRE_EMBEDDING_INDEX"


@pytest.fixture(scope="session")
def dense(index):
    try:
        # Never build in tests: a cold build takes several minutes.
        return cli_dense(build=False)
    except FileNotFoundError:
        # CI builds or restores the index, so a missing one there is a failure.
        if os.environ.get(REQUIRE_INDEX_ENV):
            pytest.fail(f"embedding index missing although {REQUIRE_INDEX_ENV} is set")
        pytest.skip("embedding index not built (run `uv run fma index`)")


def test_cli_scope_covers_every_spec(index):
    """Every evidence spec resolves to a section inside the CLI index scope,
    and the scope leaves out what no spec can request."""
    scope = cli_scope()
    assert ("flutter-3.24", None) not in scope and all(
        s != "flutter-3.24" for s, _ in scope
    )
    # Only the Android 16 range cites release notes (the targetSdk 36 bump).
    assert {s for s, k in scope if k == "release-notes"} == {"flutter-3.35"}
    kept = {c.chunk_id for c in cli_chunks(index.chunks)}
    for target, spec in CASES:
        ev = resolve(spec, target, index)
        if ev is None:
            continue
        chunk = next(
            c
            for c in index.chunks
            if c.snapshot_id == ev.snapshot_id
            and c.heading == ev.heading
            and c.url == ev.url
        )
        assert chunk.chunk_id in kept, (target.snapshot_id, spec.key)
    assert len(kept) < len(index.chunks) * 0.6


def key(ev):
    return (ev.snapshot_id, ev.heading, ev.quote) if ev else None


@pytest.mark.parametrize(
    "target, spec", CASES, ids=[f"{t.snapshot_id}-{s.key}" for t, s in CASES]
)
def test_same_evidence_with_either_retriever(index, dense, target, spec):
    assert key(resolve(spec, target, index)) == key(resolve(spec, target, dense))


def test_dense_respects_filters(dense):
    hits = dense.search(
        "edge-to-edge opt out", snapshots={"flutter-3.27"}, kinds={"api"}, top_k=20
    )
    assert hits and all(
        c.snapshot_id == "flutter-3.27" and c.kind == "api" for _, c in hits
    )


def test_missing_index_fails_before_loading_model(monkeypatch, tmp_path):
    """Without an index and with build=False, Dense must not construct the
    model: construction may download it, and offline that turns skips into
    errors."""
    import fastembed

    from fma.corpus import Chunk
    from fma.dense import Dense

    def no_model(*args, **kwargs):
        raise AssertionError("model must not load when the index is missing")

    monkeypatch.setattr(fastembed, "TextEmbedding", no_model)
    chunk = Chunk("c#0", "c", "flutter-3.27", "guide", "t", "h", "text", "u", "r")
    with pytest.raises(FileNotFoundError):
        Dense([chunk], cache_dir=tmp_path, build=False)


@pytest.mark.parametrize("sample", ["player_default", "player_opt_out"])
@pytest.mark.parametrize("versions", [("3.24.5", "3.27.1"), ("3.32.5", "3.35.1")])
def test_same_report_with_either_retriever(index, dense, sample, versions):
    inputs = discover(SAMPLES / sample)
    current, target = versions
    a = audit(current, target, inputs, index)
    b = audit(current, target, inputs, dense)
    assert [(f.key, f.verdict, [key(e) for e in f.evidence]) for f in a.findings] == [
        (f.key, f.verdict, [key(e) for e in f.evidence]) for f in b.findings
    ]


def test_cli_bm25_option_and_header(index, capsys):
    assert (
        main(
            [
                "audit",
                "--from",
                "3.24.5",
                "--to",
                "3.27.1",
                "--input",
                str(SAMPLES / "player_opt_out"),
                "--retriever",
                "bm25",
            ]
        )
        == 0
    )
    assert "근거 검색: bm25 + 버전 필터" in capsys.readouterr().out


def test_cli_rejects_version_before_loading_retriever(monkeypatch, capsys):
    def boom(kind):
        raise AssertionError("retriever must not load for an unsupported range")

    monkeypatch.setattr(cli, "get_retriever", boom)
    assert (
        main(
            [
                "audit",
                "--from",
                "3.27.0",
                "--to",
                "3.29.0",
                "--input",
                str(SAMPLES / "player_default"),
            ]
        )
        == 2
    )
    assert "스냅샷이 없습니다" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value, expected", [("6", 6), ("", None), ("0", None), ("abc", None), (" 4 ", 4)]
)
def test_embed_threads_env(monkeypatch, value, expected):
    from fma.dense import THREADS_ENV, embed_threads

    monkeypatch.setenv(THREADS_ENV, value)
    assert embed_threads() == expected


def test_index_parts_are_reused_per_snapshot(monkeypatch, tmp_path):
    """Split by snapshot, adding a snapshot embeds only the new part, and rows
    come back in the order of the chunks."""
    import fastembed
    import numpy as np

    from fma.corpus import Chunk
    from fma.dense import Dense

    embedded: list[str] = []

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def passage_embed(self, texts, batch_size):
            for t in texts:
                embedded.append(t)
                yield np.array([len(t), 1.0], dtype=np.float32)

    monkeypatch.setattr(fastembed, "TextEmbedding", FakeModel)

    def chunk(snapshot, i, text):
        return Chunk(
            f"{snapshot}#{i}", "d", snapshot, "guide", "t", "h", text, "u", "r"
        )

    old = [chunk("flutter-3.27", 0, "a"), chunk("latest", 0, "bbbb")]
    Dense(old, cache_dir=tmp_path, by_snapshot=True)
    assert len(embedded) == 2 and len(list(tmp_path.glob("*.npy"))) == 2

    embedded.clear()
    new = [chunk("flutter-3.27", 0, "a"), chunk("flutter-3.35", 0, "cc"), old[1]]
    d = Dense(new, cache_dir=tmp_path, by_snapshot=True)
    assert [t.splitlines()[-1] for t in embedded] == ["cc"]  # only the new part
    expected = np.array([[len(f"t\nh\n{c.text}"), 1.0] for c in new])
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    assert np.allclose(d.matrix, expected)
