# AGENTS.md

Guidance for coding agents in this repository.
For what the tool does and its scope, read [README.md](README.md).

## Commands

```sh
uv sync                                   # install, including the dev group
uv run pytest                             # all tests
uv run pytest tests/test_rules.py         # one file
uv run pytest tests/test_signals.py::test_styles_opt_out_and_qualifier   # one test
uv run pytest -k opt_out                  # tests whose name matches
uv run pytest -rs                         # show why tests were skipped

uv run --python 3.12 scripts/fetch_snapshots.py   # build the docs corpus into data/raw/
uv run --python 3.12 scripts/fetch_api_docs.py    # build the API docs corpus into data/raw/
uv run fma index                                  # build the embedding index into data/index/
FMA_EMBED_THREADS=4 uv run fma index              # same result, fewer CPU threads

uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_default
uv run scripts/compare_retrieval.py               # rewrite results/retrieval/

trunk fmt                                 # black, isort, prettier, taplo
trunk check                               # ruff, markdownlint, yamllint, cspell, and others
```

`trunk fmt` and `trunk check` are the gate before a commit.
CI (`.github/workflows/ci.yml`) does not run trunk.
CI runs only the corpus build, the index build, and `pytest` with `FMA_REQUIRE_EMBEDDING_INDEX=1`.

## Test preconditions

- `data/raw/` and `data/index/` are gitignored, so a fresh checkout has neither.
- Without the corpus, tests that use the `index` fixture (`tests/conftest.py`) skip.
- Without the embedding index, the embedding tests skip. With `FMA_REQUIRE_EMBEDDING_INDEX=1` they fail instead (`tests/test_retrievers.py`).
- Tests never build the index. A green run with skips does not cover the rules. Read the `-rs` output before you report a pass.
- `fma index` embeds about a third of the corpus and takes about 5 minutes on a laptop CPU.

## Architecture

The pipeline for `fma audit` (`src/fma/cli.py`):

1. `signals.py` reads clues from the user's snippets (`build.gradle(.kts)`, `AndroidManifest.xml`, `res/values*/styles.xml`, Dart). Each clue keeps its file and line. The reader also records which inputs are missing, and it resolves Android resource qualifiers for the opt-out style (see [docs/resource-qualifiers.md](docs/resource-qualifiers.md)).
2. `versions.py` maps a Flutter version to a docs snapshot and to the default `targetSdk`. Two ranges are supported: 3.24.x → 3.27.x (`targetSdk` 34 → 35) and 3.32.x → 3.35.x (35 → 36).
3. `rules.py` gives each rule a verdict: `영향 있음`, `영향 없음`, or `추가 확인 필요`. Each rule names its evidence with a `Spec` from the `E` table or from `mode_spec`. A target whose default `targetSdk` is 36 uses `Android16Auditor` and the `A16` table instead: there the apps that change are the ones whose style on an Android 16 device, in any modeled configuration such as `values-night`, opts out. `all_specs(release)` lists every spec a target can request.
4. `retrieval.py` selects the retriever that proposes candidates: `dense.py` (embedding, default) or the BM25 index in `corpus.py`.
5. `evidence.py` accepts a candidate only when it comes from the required snapshot and contains `must_contain` (and `heading`, if set). If no candidate passes, the rule drops to `추가 확인 필요`.
6. `report.py` renders text or JSON.

Invariants:

- The retriever changes only the order of candidates, not the verdicts. The version guard in `evidence.accept` decides what counts as evidence. `tests/test_retrievers.py` and `tests/test_version_guard.py` hold this.
- A spec uses `snapshot="later_correction"` only when a later docs revision fixes an omission in the target revision. The report labels that evidence.
- The CLI embedding index holds only the sections that some spec can request (`retrieval.cli_scope`). A new or changed spec changes that scope. The index is one file per snapshot (`retrieval.cli_index_files`), and each file name is a hash of the model and that snapshot's sections. After such a change, run `fma index` again; it rebuilds only the files whose sections changed.
- The tool is read-only. It never writes to the app it audits.

## Generated and committed files

- `data/manifest/*.jsonl` and `data/manifest/snapshots.json` come from the two fetch scripts. They pin commits and release tags. CI rebuilds them and fails on any diff, so change the scripts, not the manifests.
- `results/retrieval/` comes from `scripts/compare_retrieval.py`. [docs/retrieval-comparison.md](docs/retrieval-comparison.md) quotes its numbers.
- The README block between `<!-- fma-example:start -->` and `<!-- fma-example:end -->` must match the real CLI output for `samples/player_default` (`tests/test_readme_example.py`). When you change the output of a rule or of `report.py`, update that block.

## Conventions

- Report text, CLI help, and docs under `docs/` and `README.md` are in Korean on purpose. Do not translate them. Code, comments, and commit messages are in English.
- The two apps in `samples/` differ only in `styles.xml`. Keep it that way, because the README compares their results.
- The cspell dictionary is `.cspell/project_terms.txt`. Keep it a flat list, sorted case-insensitively. `cspell@10.5` needs the trunk `node@22.18.0` runtime or later. On an older runtime, trunk reports no issues without checking any file.
