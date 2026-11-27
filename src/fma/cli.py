"""Command-line entry point. Read-only: it never writes to the app."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .corpus import CorpusMissing, default_index
from .report import to_json, to_text
from .rules import audit
from .signals import discover, read_paths
from .versions import UnsupportedVersion


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fma",
        description="Flutter 업그레이드가 Android 시스템 바·edge-to-edge에 주는 영향을 앱 설정과 공식 문서로 판단합니다.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit", help="업그레이드 영향 분석")
    a.add_argument("--from", dest="current", required=True, help="현재 Flutter 버전 (예: 3.24.5)")
    a.add_argument("--to", dest="target", required=True, help="목표 Flutter 버전 (예: 3.27.1)")
    a.add_argument("--input", type=Path, help="설정·코드 조각이 들어 있는 디렉터리")
    a.add_argument("files", nargs="*", type=Path,
                   help="build.gradle(.kts), AndroidManifest.xml, res/values*/styles.xml, *.dart")
    a.add_argument("--json", action="store_true", help="JSON으로 출력")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if bool(args.input) == bool(args.files):
        print("--input 디렉터리와 파일 목록 중 하나만 넣어 주세요.", file=sys.stderr)
        return 2
    inputs = discover(args.input) if args.input else read_paths(args.files)
    try:
        report = audit(args.current, args.target, inputs, default_index())
    except (UnsupportedVersion, CorpusMissing) as e:
        print(str(e), file=sys.stderr)
        return 2
    sys.stdout.write(to_json(report) if args.json else to_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
