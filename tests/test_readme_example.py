"""The README output example must stay identical to real CLI output (issue #8)."""

import re
from pathlib import Path

from fma.report import to_text
from fma.rules import audit
from fma.signals import discover

ROOT = Path(__file__).resolve().parents[1]
# Markdown formatters may put a blank line between the markers and the fence.
BLOCK = re.compile(
    r"<!-- fma-example:start -->\n+```text\n(.*?)\n```\n+<!-- fma-example:end -->",
    re.DOTALL,
)


def readme_example() -> str:
    m = BLOCK.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert m, "README.md has no fma-example block"
    return m.group(1)


def test_readme_example_matches_cli_output(index):
    report = audit(
        "3.24.5", "3.27.1", discover(ROOT / "samples" / "player_default"), index
    )
    # The README shows the default retriever. Evidence is the same with either
    # retriever (tests/test_retrievers.py), so only the header label differs.
    report.retriever = "embedding"
    actual_blocks = to_text(report).strip("\n").split("\n\n")
    example_blocks = readme_example().split("\n\n")
    assert len(example_blocks) >= 3
    for block in example_blocks:
        assert (
            block in actual_blocks
        ), f"README block is not in the CLI output:\n{block}"


def test_readme_example_keeps_output_order(index):
    report = audit(
        "3.24.5", "3.27.1", discover(ROOT / "samples" / "player_default"), index
    )
    report.retriever = "embedding"
    actual_blocks = to_text(report).strip("\n").split("\n\n")
    positions = [actual_blocks.index(b) for b in readme_example().split("\n\n")]
    assert positions == sorted(positions)
