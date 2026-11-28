"""The CLI's default retriever is embedding search. Evidence is accepted only
after the snapshot, heading, and sentence checks, so switching retrievers
must not change any judgement or quote."""

import os
from pathlib import Path

import pytest

from fma import cli
from fma.cli import main
from fma.corpus import load_chunks
from fma.evidence import resolve
from fma.retrieval import cli_chunks, cli_scope
from fma.rules import E, audit, mode_spec
from fma.signals import discover
from fma.versions import release_for

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
TARGET = release_for("3.27.0")
SPECS = list(E.values()) + [
    mode_spec(m) for m in ("leanBack", "immersive", "immersiveSticky", "manual")
]
# Set in CI, where the embedding tests must run instead of skipping.
REQUIRE_INDEX_ENV = "FMA_REQUIRE_EMBEDDING_INDEX"


@pytest.fixture(scope="session")
def dense(index):
    from fma.dense import Dense

    try:
        # Never build in tests: a cold build takes several minutes.
        return Dense(cli_chunks(load_chunks()), build=False)
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
    assert all(k != "release-notes" for _, k in scope)
    kept = {c.chunk_id for c in cli_chunks(index.chunks)}
    for spec in SPECS:
        ev = resolve(spec, TARGET, index)
        if ev is None:
            continue
        chunk = next(
            c
            for c in index.chunks
            if c.snapshot_id == ev.snapshot_id
            and c.heading == ev.heading
            and c.url == ev.url
        )
        assert chunk.chunk_id in kept, spec.key
    assert len(kept) < len(index.chunks) * 0.6


def key(ev):
    return (ev.snapshot_id, ev.heading, ev.quote) if ev else None


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.key)
def test_same_evidence_with_either_retriever(index, dense, spec):
    assert key(resolve(spec, TARGET, index)) == key(resolve(spec, TARGET, dense))


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
def test_same_report_with_either_retriever(index, dense, sample):
    inputs = discover(SAMPLES / sample)
    a, b = audit("3.24.5", "3.27.1", inputs, index), audit(
        "3.24.5", "3.27.1", inputs, dense
    )
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
