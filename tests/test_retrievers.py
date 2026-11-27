"""The CLI's default retriever is embedding search. Evidence is accepted only
after the snapshot, heading, and sentence checks, so switching retrievers
must not change any judgement or quote."""

from pathlib import Path

import pytest

from fma import cli
from fma.cli import main
from fma.corpus import load_chunks
from fma.evidence import resolve
from fma.rules import E, audit, mode_spec
from fma.signals import discover
from fma.versions import release_for

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
TARGET = release_for("3.27.0")
SPECS = list(E.values()) + [mode_spec(m) for m in ("leanBack", "immersive", "immersiveSticky", "manual")]


@pytest.fixture(scope="session")
def dense(index):
    from fma.dense import Dense

    try:
        # Never build in tests: a cold build takes about 15 minutes.
        return Dense(load_chunks(), build=False)
    except FileNotFoundError:
        pytest.skip("embedding index not built (run `uv run fma index`)")


def key(ev):
    return (ev.snapshot_id, ev.heading, ev.quote) if ev else None


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.key)
def test_same_evidence_with_either_retriever(index, dense, spec):
    assert key(resolve(spec, TARGET, index)) == key(resolve(spec, TARGET, dense))


def test_dense_respects_filters(dense):
    hits = dense.search("edge-to-edge opt out", snapshots={"flutter-3.27"}, kinds={"api"}, top_k=20)
    assert hits and all(c.snapshot_id == "flutter-3.27" and c.kind == "api" for _, c in hits)


@pytest.mark.parametrize("sample", ["player_default", "player_opt_out"])
def test_same_report_with_either_retriever(index, dense, sample):
    inputs = discover(SAMPLES / sample)
    a, b = audit("3.24.5", "3.27.1", inputs, index), audit("3.24.5", "3.27.1", inputs, dense)
    assert [(f.key, f.verdict, [key(e) for e in f.evidence]) for f in a.findings] == \
           [(f.key, f.verdict, [key(e) for e in f.evidence]) for f in b.findings]


def test_cli_bm25_option_and_header(index, capsys):
    assert main(["audit", "--from", "3.24.5", "--to", "3.27.1", "--input",
                 str(SAMPLES / "player_opt_out"), "--retriever", "bm25"]) == 0
    assert "근거 검색: bm25 + 버전 필터" in capsys.readouterr().out


def test_cli_rejects_version_before_loading_retriever(monkeypatch, capsys):
    def boom(kind):
        raise AssertionError("retriever must not load for an unsupported range")

    monkeypatch.setattr(cli, "get_retriever", boom)
    assert main(["audit", "--from", "3.27.0", "--to", "3.29.0", "--input", str(SAMPLES / "player_default")]) == 2
    assert "스냅샷이 없습니다" in capsys.readouterr().err
