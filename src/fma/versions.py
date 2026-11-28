"""Flutter versions the audit supports, and what each one implies."""

from __future__ import annotations

import re
from dataclasses import dataclass

VERSION = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?$")

# Android enforces edge-to-edge for apps that target this API level or later.
EDGE_TO_EDGE_API = 35
ANDROID_VERSIONS = {34: "Android 14", 35: "Android 15", 36: "Android 16"}


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

    @property
    def label(self) -> str:
        return f"Flutter {self.minor[0]}.{self.minor[1]}"


RELEASES = {
    (3, 24): Release((3, 24), "flutter-3.24", 34),
    (3, 27): Release((3, 27), "flutter-3.27", 35),
}
# Upgrades the audit supports, as (current minor, target minor). Each range
# changes the default targetSdk; its evidence comes from the docs snapshot of
# the target release.
SUPPORTED_RANGES = (((3, 24), (3, 27)),)


def android_name(api: int) -> str:
    return ANDROID_VERSIONS.get(api, f"API {api}")


def target_releases() -> list[Release]:
    """The releases that some supported upgrade targets."""
    return [RELEASES[target] for _, target in SUPPORTED_RANGES]


def range_text(minors: tuple[tuple[int, int], tuple[int, int]]) -> str:
    (a, b), (c, d) = minors
    return f"{a}.{b}.x → {c}.{d}.x"


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
    if (cur.minor, tgt.minor) not in SUPPORTED_RANGES:
        raise UnsupportedVersion(
            "첫 버전은 Flutter "
            + ", ".join(range_text(r) for r in SUPPORTED_RANGES)
            + f" 구간만 분석합니다. 입력: {current} → {target}"
        )
    return cur, tgt
