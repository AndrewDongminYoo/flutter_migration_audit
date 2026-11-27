# flutter_migration_audit

Flutter 업그레이드가 내 앱의 Android 시스템 바와 edge-to-edge 동작을 바꾸는지 판단하는 읽기 전용 CLI입니다. 현재·목표 Flutter 버전과 관련 설정·코드 몇 줄을 받아, 항목마다 다음 세 가지를 붙여 판단합니다.

- 앱에서 찾은 단서 (파일과 줄 번호)
- 목표 버전 시점의 공식 문서 근거 (인용문, 문서 판본, URL)
- 직접 해 볼 테스트

판단은 `영향 있음`, `영향 없음`, `추가 확인 필요` 중 하나입니다. 입력이 부족하거나 목표 버전 문서에서 근거를 찾지 못하면 `추가 확인 필요`로 멈추고 무엇을 확인해야 하는지 알려 줍니다. 앱 파일은 읽기만 하고 고치지 않습니다.

## 범위

- 업그레이드 구간: Flutter 3.24.x → 3.27.x
- 주제: Android 시스템 바와 edge-to-edge (`targetSdk`, opt-out 스타일, `SystemUiMode`, `SafeArea`·`AppBar`, 시스템 바 색상)
- 입력: `android/app/build.gradle(.kts)`, `AndroidManifest.xml`, `res/values*/styles.xml`, Dart 파일. 프로젝트 전체가 아니라 일부만 넣어도 됩니다.
- 제외: GitHub 연동, 코드 자동 수정, 다른 업그레이드 구간

## 사용법

```sh
# 코퍼스 만들기 (한 번)
uv run --python 3.12 scripts/fetch_snapshots.py
uv run --python 3.12 scripts/fetch_api_docs.py

# 임베딩 인덱스 만들기 (한 번, 노트북 CPU에서 15분 안팎)
uv run fma index

# 디렉터리로 넣기
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_default

# 파일만 골라 넣기
uv run fma audit --from 3.24.5 --to 3.27.1 path/to/build.gradle path/to/values/styles.xml path/to/main.dart

# JSON 출력
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_opt_out --json

# 근거 후보를 BM25로 찾기 (임베딩 인덱스가 없을 때)
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_default --retriever bm25
```

근거 후보는 기본적으로 목표 버전 스냅샷 안에서 임베딩 검색으로 찾습니다. 검색 방식과 관계없이, 후보가 근거로 채택되려면 정해 둔 판본과 정답 문장을 모두 만족해야 합니다. 그래서 검색 방식을 바꿔도 판단 결과는 같고, 달라지는 것은 근거를 찾기까지 살펴보는 후보의 순서입니다.

## 실행 결과 예시

`samples/player_default`를 분석한 결과에서 다섯 항목 중 두 항목을 옮겼습니다. 나머지 항목도 같은 형식으로 나옵니다.

<!-- fma-example:start -->

```text
Flutter 3.24.5 → 3.27.1 · Android 시스템 바 / edge-to-edge
입력: android/app/build.gradle, android/app/src/main/AndroidManifest.xml, android/app/src/main/res/values/styles.xml, android/app/src/main/res/values-night/styles.xml, lib/player_screen.dart
근거 검색: embedding + 버전 필터

요약: 영향 있음 5 · 추가 확인 필요 0 · 영향 없음 0

[영향 있음] targetSdk 변화
  targetSdk가 flutter.targetSdkVersion을 따르므로 API 34에서 API 35(Android 15)로 바뀝니다.
  앱 단서:
    android/app/build.gradle:14  targetSdk = flutter.targetSdkVersion
  문서 근거:
    “Prior to Flutter 3.27, Flutter apps target Android 14 by default and won't opt into edge-to-
    edge mode automatically, but your app _will_ be impacted when you choose to target Android 15.
    If your app targets `flutter.targetSdkVersion` (as it does by default), then it targets Android
    15 starting with Flutter version 3.27, automatically opting your app in to edge-to-edge.”
      Set default of `SystemUiMode` to edge-to-edge › Context · Flutter 3.27 문서 (flutter/website d69db60f99)
      https://docs.flutter.dev/release/breaking-changes/default-systemuimode-edge-to-edge
  직접 테스트:
    - Android 15(API 35) 에뮬레이터에서 Flutter 3.24 빌드와 Flutter 3.27 빌드의 첫 화면을 열고 상단 상태바·하단 내비게이션 바 주변을
    비교한다.

[영향 있음] SystemUiMode 사용: immersiveSticky
  SystemUiMode.immersiveSticky 모드는 targetSdk 35 이상에서 opt-out 없이는 동작하지 않습니다.
  앱 단서:
    lib/player_screen.dart:16  SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  문서 근거:
    “Available starting at Android SDK 4.4 (API 19). Earlier versions of Android will not be
    affected by this setting. However, if your app targets Android SDK 15 (API 35) or later (Flutter
    does this by default), then you must migrate using the instructions in
    https://docs.flutter.dev/release/breaking-changes/default-systemuimode-edge-to-edge to use this
    mode.”
      SystemUiMode enum › SystemUiMode.immersiveSticky · Flutter 3.27 문서 (flutter/flutter 3.27.0)
      https://api.flutter.dev/flutter/services/SystemUiMode.html
  직접 테스트:
    - Android 15(API 35) 에뮬레이터에서 immersiveSticky 모드를 켜는 화면에 들어가 상태바·내비게이션 바가 문서대로 숨는지 확인한다.
```

<!-- fma-example:end -->

## 샘플: 같은 업그레이드, 다른 결과

`samples/`의 두 앱은 Dart 코드와 Gradle 설정이 같고 `styles.xml`만 다릅니다. 둘 다 동영상 화면에서 `SystemUiMode.immersiveSticky`를 쓰고, `targetSdk`는 `flutter.targetSdkVersion`을 따릅니다.

| 항목                             | `player_default`          | `player_opt_out`                 |
| -------------------------------- | ------------------------- | -------------------------------- |
| targetSdk 변화 (34 → 35)         | 영향 있음                 | 영향 있음                        |
| edge-to-edge opt-out             | 영향 있음 (항목 없음)     | 영향 없음 (항목 있음, 임시 조치) |
| `immersiveSticky`, `manual` 모드 | 영향 있음                 | 해당 없음                        |
| 시스템 바 영역 레이아웃          | 영향 있음 (SafeArea 없음) | 해당 없음                        |

`player_opt_out`은 opt-out이 적용되므로 그 뒤 항목은 확인하지 않습니다. 대신 문서가 이 방법을 임시 조치로 안내한다는 근거를 함께 보여 줍니다.

## 비슷하지만 다른 버전의 문서

edge-to-edge 마이그레이션 문서는 코퍼스에 세 가지 판본이 있습니다. 3.27 출시 전 판본, 3.27 시점 판본, 그리고 Android 16 내용이 추가된 현재 판본입니다. 판본 사이의 차이는 몇 문장에 불과해서, 버전 필터 없이 BM25로 검색하면 세 판본의 점수 차이가 2%도 나지 않고 1위는 3.27 판본이 아닙니다.

| 질의 (opt-out 근거) | 점수  | 판본              |
| ------------------- | ----- | ----------------- |
| 1위                 | 60.54 | 현재 판본         |
| 2위                 | 59.64 | 3.27 판본         |
| 3위                 | 59.55 | 3.27 출시 전 판본 |

현재 판본을 근거로 쓰면 답이 달라집니다. 3.27 판본은 opt-out이 "Android SDK 15+를 대상으로 하는 앱"에 적용된다고 썼지만, 현재 판본은 Android 16부터 opt-out이 불가능하다는 이유로 이를 "SDK 15"로 좁혔습니다. 그래서 근거마다 필요한 판본을 정해 두고, 검색 결과가 다른 판본이면 문장이 같아도 받지 않습니다(`src/fma/evidence.py`, `tests/test_version_guard.py`).

예외는 하나 있습니다. 3.27 판본이 빠뜨린 다크 모드 스타일(`values-night`) 안내는 이후 판본에서 추가됐습니다. 이 경우에만 이후 판본을 인용하고, 출력에 "목표 버전 이후에 고쳐진 내용"이라고 표시합니다.

## 검색 방식 비교

질문 15개로 키워드 검색(BM25), 임베딩 검색, 그리고 각각에 버전 필터를 붙인 방식을 비교했습니다. 필터가 없는 임베딩 검색은 정답을 1위에 올린 질문이 1개뿐이었고, 15개 중 4개에서 1위가 다른 판본이었습니다. 버전 필터를 붙인 임베딩 검색은 1위 적중률 0.60으로 네 방식 중 가장 좋았고, 그래서 CLI의 기본 검색 방식으로 쓰고 있습니다. 버전 필터가 오히려 정답을 막는 경우와, 필터로도 해결되지 않는 실패도 함께 정리했습니다. 자세한 내용은 [docs/retrieval-comparison.md](docs/retrieval-comparison.md)에 있습니다.

```sh
uv run scripts/compare_retrieval.py
```

## 문서

- [docs/corpus.md](docs/corpus.md): 문서 스냅샷 기준, 판본별 차이, 버전 메타데이터의 한계
- [docs/retrieval-comparison.md](docs/retrieval-comparison.md): 검색 방식 비교 결과와 실패 분석

## 테스트

```sh
uv run pytest
```

코퍼스(`data/raw/`)가 없으면 코퍼스가 필요한 테스트는 건너뜁니다. 임베딩 인덱스(`data/index/`)가 없으면 임베딩 검색 테스트도 건너뜁니다. 테스트 중에는 인덱스를 새로 만들지 않습니다.
