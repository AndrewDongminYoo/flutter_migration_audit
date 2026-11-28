"""Command-line entry point. Read-only: it never writes to the app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .corpus import CorpusMissing
from .report import to_json, to_text
from .retrieval import DEFAULT, RETRIEVERS, get_retriever
from .rules import audit
from .signals import discover, read_paths
from .versions import UnsupportedVersion, check_range


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fma",
        description="Flutter 업그레이드가 Android 시스템 바·edge-to-edge에 주는 영향을 앱 설정과 공식 문서로 판단합니다.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit", help="업그레이드 영향 분석")
    a.add_argument(
        "--from", dest="current", required=True, help="현재 Flutter 버전 (예: 3.24.5)"
    )
    a.add_argument(
        "--to", dest="target", required=True, help="목표 Flutter 버전 (예: 3.27.1)"
    )
    a.add_argument("--input", type=Path, help="설정·코드 조각이 들어 있는 디렉터리")
    a.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="build.gradle(.kts), AndroidManifest.xml, res/values*/styles.xml, *.dart",
    )
    a.add_argument(
        "--retriever",
        choices=RETRIEVERS,
        default=DEFAULT,
        help=f"근거 후보를 찾는 검색 방식 (기본값: {DEFAULT})",
    )
    a.add_argument("--json", action="store_true", help="JSON으로 출력")
    sub.add_parser("index", help="임베딩 인덱스를 미리 만듭니다")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "index":
            retriever = get_retriever("embedding")
            for path in retriever.paths:  # type: ignore[attr-defined]
                print(f"임베딩 인덱스 준비 완료: {path}")
            return 0
        if bool(args.input) == bool(args.files):
            print(
                "--input 디렉터리와 파일 목록 중 하나만 넣어 주세요.", file=sys.stderr
            )
            return 2
        # Reject unsupported versions before loading (or building) an index.
        check_range(args.current, args.target)
        inputs = discover(args.input) if args.input else read_paths(args.files)
        report = audit(args.current, args.target, inputs, get_retriever(args.retriever))
        report.retriever = args.retriever
    except (UnsupportedVersion, CorpusMissing) as e:
        print(str(e), file=sys.stderr)
        return 2
    sys.stdout.write(to_json(report) if args.json else to_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
