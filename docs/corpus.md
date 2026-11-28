# 코퍼스 구성

## 스냅샷 기준

flutter/website 저장소에는 릴리스 태그가 없습니다. 그래서 각 릴리스 스냅샷은 다음 정식 릴리스가 나오기 직전의 마지막 커밋으로 정합니다. 그 버전이 현재 stable이던 기간에 사용자가 보던 문서를 재현하기 위해서입니다. 릴리스 날짜는 Flutter 공식 `releases_macos.json`에서 가져옵니다.

| 스냅샷         | 대표 버전 | 커밋                      | 기준               |
| -------------- | --------- | ------------------------- | ------------------ |
| `flutter-3.24` | 3.24.0    | `4e5c7d2f72` (2024-12-11) | 3.27.0 릴리스 직전 |
| `flutter-3.27` | 3.27.0    | `d69db60f99` (2025-02-11) | 3.29.0 릴리스 직전 |
| `flutter-3.32` | 3.32.0    | `04e40bb7b4` (2025-08-14) | 3.35.0 릴리스 직전 |
| `flutter-3.35` | 3.35.0    | `ae1d177e32` (2025-11-12) | 3.38.0 릴리스 직전 |
| `latest`       | 현재 문서 | `a0b75bedb9` (2026-11-25) | 고정 커밋          |

docs.flutter.dev에서 수집하는 대상은 다음과 같습니다. 전체 목록과 메타데이터는 `data/manifest/docs.jsonl`에 있고, 원문은 `scripts/fetch_snapshots.py`로 `data/raw/snapshots/`에 다시 만들 수 있습니다.

- `release/breaking-changes/*.md`
- 3.22 이후 릴리스 노트
- Android 및 화면 레이아웃 가이드: `deployment/android.md`, `ui/adaptive-responsive/*`, `platform-adaptations`, `platform-integration/android/*`, `add-to-app/android/*`

Android 가이드 중 상당수(예: predictive back, splash screen, platform views)는 시스템 바와 관계가 없습니다. 일부러 넣은 문서입니다. Android 관련이라는 점만 같고 정답은 아닌 문서가 있어야 검색 방식 사이의 차이가 드러납니다.

`platform-adaptations.md`는 3.27 스냅샷부터 `platform-integration/`에서 `ui/adaptive-responsive/`로 경로가 바뀌었습니다. 그래서 매니페스트의 각 문서에 `doc_key`를 둡니다. `doc_key`는 문서의 URL 경로에서 시작해, 고정한 최신 커밋의 flutter/website 리다이렉트 설정(`firebase.json`의 301 리다이렉트)을 끝까지 따라간 경로입니다. 곧 그 문서가 지금 사이트에서 있는 곳입니다. 이전 커밋에만 있던 리다이렉트는 따르지 않습니다. 나중에 지워진 규칙을 따르면, 다시 생긴 페이지가 관계없는 키를 받을 수 있기 때문입니다. 도착 경로의 쿼리와 fragment는 버립니다. 이동한 문서의 두 경로는 같은 `doc_key`(`/ui/adaptive-responsive/platform-adaptations`)를 받으므로, 판본을 비교할 때 같은 문서로 묶입니다(`src/fma/evalset.py`). `platform-integration/android/c-interop.md`는 최신 사이트에서 수집 범위 밖의 `/platform-integration/legacy-ffi-plugin`으로 리다이렉트되므로 그 경로를 키로 받습니다. 수집한 판본끼리는 모두 같은 키라서 같은 문서로 묶입니다. API 문서는 스냅샷 사이에 경로가 바뀌지 않으므로 경로를 그대로 키로 씁니다.

## API 문서

api.flutter.dev는 최신 릴리스만 제공합니다. 그래서 이전 버전의 API 문서는 flutter/flutter 저장소의 릴리스 태그에서 dartdoc 주석(`///`)을 추출해 다시 만듭니다(`scripts/fetch_api_docs.py`, 목록은 `data/manifest/api_docs.jsonl`). 공개된 최상위 선언 하나가 문서 하나가 되고, 문서화된 멤버는 섹션으로 들어갑니다.

| 스냅샷         | 태그          | 문서 수 |
| -------------- | ------------- | ------- |
| `flutter-3.24` | 3.24.0        | 15      |
| `flutter-3.27` | 3.27.0        | 15      |
| `flutter-3.32` | 3.32.0        | 15      |
| `flutter-3.35` | 3.35.0        | 16      |
| `latest`       | 3.50.1 (고정) | 16      |

대상 소스는 `system_chrome.dart`(`SystemUiMode`, `SystemChrome`, `SystemUiOverlayStyle`), `safe_area.dart`, `media_query.dart`, `annotated_region.dart`, `app_bar.dart`입니다. API 스냅샷은 릴리스 태그 자체를 쓰고, 웹사이트 스냅샷은 다음 릴리스 직전 커밋을 씁니다. API 문서는 릴리스와 함께 배포되지만 웹사이트 문서는 릴리스 이후에도 계속 고쳐지기 때문입니다.

`SystemUiMode` 문서도 판본마다 다릅니다. 3.24에는 API 35 언급이 없습니다. 3.27에는 "Android 15(API 35)를 대상으로 하면 edge-to-edge가 기본"이라는 설명이 추가됐고, 3.35.0부터는 "API 36 이상이면 시스템이 이 값을 무시한다"는 설명이 더해졌습니다. 3.35는 `flutter.targetSdkVersion` 기본값이 36으로 바뀐 릴리스입니다.

`{@macro}`로 다른 곳의 `{@template}`을 불러오는 부분은 dartdoc처럼 펼쳐 넣습니다. 템플릿은 같은 태그의 `packages/flutter/lib` 아래 모든 Dart 파일에서 모읍니다. 예를 들어 `SliverAppBar.primary`에는 `AppBar.primary`의 설명("상태바 높이만큼 위쪽을 띄운다")이 들어갑니다. `dart:ui`처럼 그 밖에 정의된 템플릿은 펼치지 못하고, 매니페스트의 `unresolved_macros`에 남깁니다. 지금은 다섯 스냅샷 모두 `dart.ui.ViewConfiguration.displayFeatures` 하나뿐입니다.

## 같은 문서, 다섯 가지 판본

`default-systemuimode-edge-to-edge.md`는 스냅샷마다 내용이 다릅니다.

| 스냅샷         | 색인 상태                  | 버전 표기             | Android 16 언급 | `values-night` 안내 | `values-35` 안내 |
| -------------- | -------------------------- | --------------------- | --------------- | ------------------- | ---------------- |
| `flutter-3.24` | Not yet released to stable | 없음                  | 없음            | 없음                | 없음             |
| `flutter-3.27` | Released in Flutter 3.27   | 3.26.0-0.0.pre / 3.27 | 없음            | 없음                | 없음             |
| `flutter-3.32` | Released in Flutter 3.27   | 3.26.0-0.0.pre / 3.27 | 4회             | 있음                | 없음             |
| `flutter-3.35` | Released in Flutter 3.27   | 3.26.0-0.0.pre / 3.27 | 4회             | 있음                | 없음             |
| `latest`       | Released in Flutter 3.27   | 3.26.0-0.0.pre / 3.27 | 8회             | 있음                | 있음             |

나중에 추가된 내용이 모두 오염인 것은 아닙니다. Android 16 크래시 회피(`values-35`)는 3.27 시점에는 없던 내용이고, 2026년 2월에 추가되어 3.35 판본에도 없습니다. 반면 `values-night` 스타일에도 같은 속성을 넣으라는 안내는 3.27 판본이 빠뜨린 부분을 2025년 8월에 바로잡은 것이라 3.32 판본부터 들어 있습니다. 3.32와 3.35 판본에는 "Android 16 이상을 대상으로 하면 opt-out할 수 없다"는 안내도 있습니다. 그래서 정답 표에는 질문마다 어느 판본을 근거로 삼는지와 그 이유를 함께 적습니다.

## 버전 메타데이터의 한계

버전 필터는 문서마다 붙은 버전 정보에 의존하는데, 이 정보가 항상 일치하지는 않습니다.

- 문서 하단 표기(`Landed in version`, `Stable release`)와 색인 페이지의 릴리스 구분이 다른 문서가 있습니다. 예를 들어 `buttons.md`는 하단에 2.0.0, 색인에는 1.20으로 나옵니다.
- 하단 표기가 없는 breaking change 문서가 스냅샷마다 30개 넘게 있고, 색인에 없는 문서도 11개 있습니다.
- 출시 전 판본에는 버전 표기가 없습니다(`flutter-3.24`의 edge-to-edge 문서).

그래서 근거를 고를 때는 문서별 버전 표기 대신 스냅샷을 기준으로 거릅니다. 목표 버전의 스냅샷에 들어 있는 판본만 받고, 이후 판본은 누락을 바로잡은 내용일 때만 표시를 붙여 인용합니다(`src/fma/evidence.py`). 버전 표기는 검색 비교 단계에서 다른 필터 방식과 견줄 때 다시 다룹니다.
