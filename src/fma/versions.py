"""Flutter versions the audit supports, and what each one implies."""

from __future__ import annotations

import re
from dataclasses import dataclass

VERSION = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?$")


class UnsupportedVersion(ValueError):
    pass


@dataclass(frozen=True)
class Release:
    minor: tuple[int, int]
    snapshot_id: str
    # Value of `flutter.targetSdkVersion` in this release. Source: the
    # "Context" section of the 3.27 edge-to-edge breaking change doc
    # ("Prior to Flutter 3.27, Flutter apps target Android 14 by default").
    default_target_sdk: int


RELEASES = {
    (3, 24): Release((3, 24), "flutter-3.24", 34),
    (3, 27): Release((3, 27), "flutter-3.27", 35),
}
SUPPORTED_RANGE = ((3, 24), (3, 27))


def parse(version: str) -> tuple[int, int, int]:
    m = VERSION.match(version.strip())
    if not m:
        raise UnsupportedVersion(f"Flutter 버전 형식을 읽을 수 없습니다: {version!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def release_for(version: str) -> Release:
    major, minor, _ = parse(version)
    try:
        return RELEASES[(major, minor)]
    except KeyError:
        raise UnsupportedVersion(
            f"Flutter {version}의 문서 스냅샷이 없습니다. 지원 버전: "
            + ", ".join(f"{a}.{b}.x" for a, b in RELEASES)
        ) from None


def check_range(current: str, target: str) -> tuple[Release, Release]:
    cur, tgt = release_for(current), release_for(target)
    if (cur.minor, tgt.minor) != SUPPORTED_RANGE:
        raise UnsupportedVersion(
            "첫 버전은 Flutter 3.24.x → 3.27.x 구간만 분석합니다. "
            f"입력: {current} → {target}"
        )
    return cur, tgt
