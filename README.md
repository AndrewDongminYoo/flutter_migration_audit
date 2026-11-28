# flutter_migration_audit

Flutter 업그레이드가 내 앱의 Android 시스템 바와 edge-to-edge 동작을 바꾸는지 판단하는 읽기 전용 CLI입니다. 현재·목표 Flutter 버전과 관련 설정·코드 몇 줄을 받아, 항목마다 다음 세 가지를 붙여 판단합니다.

- 앱에서 찾은 단서 (파일과 줄 번호)
- 목표 버전 시점의 공식 문서 근거 (인용문, 문서 판본, URL)
- 직접 해 볼 테스트

판단은 `영향 있음`, `영향 없음`, `추가 확인 필요` 중 하나입니다. 입력이 부족하거나 목표 버전 문서에서 근거를 찾지 못하면 `추가 확인 필요`로 멈추고 무엇을 확인해야 하는지 알려 줍니다. 앱 파일은 읽기만 하고 고치지 않습니다.

## 범위

- 업그레이드 구간: Flutter 3.24.x → 3.27.x(`targetSdk` 기본값 34 → 35, Android 15), 3.32.x → 3.35.x(35 → 36, Android 16). 구간을 건너뛰는 업그레이드(예: 3.27 → 3.35)는 받지 않습니다.
- 주제: Android 시스템 바와 edge-to-edge (`targetSdk`, opt-out 스타일, `SystemUiMode`, `SafeArea`·`AppBar`, 시스템 바 색상)
- 입력: `android/app/build.gradle(.kts)`, `AndroidManifest.xml`, `res/values*/styles.xml`, Dart 파일. 프로젝트 전체가 아니라 일부만 넣어도 됩니다.
- 판단하는 테마: `AndroidManifest.xml`에서 FlutterActivity의 `NormalTheme` meta-data가 가리키는 스타일을 판단합니다. meta-data가 없으면 activity의 `android:theme`(없으면 application의 테마)를 판단합니다. 실행 화면 테마(`LaunchTheme`)의 opt-out 여부가 이 스타일과 다르면(다크 모드 같은 다른 기기 설정에서만 다른 경우 포함) `추가 확인 필요`로 따로 알립니다. 3.32 → 3.35 구간에서는 업그레이드 후 두 스타일의 opt-out이 모두 무시되므로, 실행 화면 테마에만 opt-out이 있어 실행 화면이 바뀌는 경우만 알립니다. manifest를 넣었는데 테마를 찾지 못하면 opt-out 항목을 `추가 확인 필요`로 판단하고, manifest를 넣지 않으면 템플릿 기본값인 `NormalTheme`을 판단합니다. manifest가 여러 개이면 기본 소스 세트인 `src/main`의 manifest로 판단합니다(`src/main`이 없으면 먼저 넣은 manifest). 빌드 유형별 manifest(예: `src/debug`)가 다른 테마나 병합 지시(`tools:node` 등)를 담고 있으면 리포트에 메모로 알립니다. `styles.xml`도 같습니다. opt-out은 `src/main`(소스 세트가 없는 경로 포함)의 스타일로 판단하고, 빌드 유형별 소스 세트의 스타일이 같은 이름의 main 스타일과 opt-out 항목이나 부모 스타일이 다르면 메모로 알립니다. NormalTheme meta-data가 있는 activity가 여럿이면 실행(LAUNCHER) activity를 판단하고, 실행 activity를 정할 수 없으면 opt-out 항목을 `추가 확인 필요`로 판단합니다.
- 제외: GitHub 연동, 코드 자동 수정, 위 두 구간 밖의 업그레이드

## 사용법

```sh
# 코퍼스 만들기 (한 번)
uv run --python 3.12 scripts/fetch_snapshots.py
uv run --python 3.12 scripts/fetch_api_docs.py

# 임베딩 인덱스 만들기 (한 번, 노트북 CPU에서 5분 안팎)
uv run fma index

# 다른 작업과 함께 돌릴 때는 스레드 수를 줄입니다 (결과는 같고 속도만 달라집니다)
FMA_EMBED_THREADS=4 uv run fma index

# 디렉터리로 넣기
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_default

# 파일만 골라 넣기
uv run fma audit --from 3.24.5 --to 3.27.1 path/to/build.gradle path/to/values/styles.xml path/to/main.dart

# JSON 출력
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_opt_out --json

# 근거 후보를 BM25로 찾기 (임베딩 인덱스가 없을 때)
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_default --retriever bm25

# Android 16 구간
uv run fma audit --from 3.32.5 --to 3.35.1 --input samples/player_opt_out
```

근거 후보는 기본적으로 목표 버전 스냅샷 안에서 임베딩 검색으로 찾습니다. CLI용 임베딩 인덱스에는 근거로 쓰일 수 있는 섹션만 넣습니다. 목표 버전의 breaking change·API·가이드 문서, 3.35의 릴리스 노트(`targetSdk` 기본값 변경), 그리고 이후에 고쳐진 내용을 위한 현재 판본의 breaking change 문서입니다. 전체 코퍼스의 56%이고, 검색 비교 실험만 전체 코퍼스를 임베딩합니다. 검색 방식과 관계없이, 후보가 근거로 채택되려면 정해 둔 판본과 정답 문장을 모두 만족해야 합니다. 그래서 검색 방식을 바꿔도 판단 결과는 같고, 달라지는 것은 근거를 찾기까지 살펴보는 후보의 순서입니다.

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

같은 두 앱을 3.32.5 → 3.35.1로 분석하면 결과가 뒤집힙니다. `targetSdk`가 36이 되면 Android 16 기기에서는 opt-out이 무시되기 때문입니다.

| 항목                             | `player_default`              | `player_opt_out`                       |
| -------------------------------- | ----------------------------- | -------------------------------------- |
| targetSdk 변화 (35 → 36)         | 영향 있음                     | 영향 있음                              |
| edge-to-edge opt-out             | 영향 없음 (이미 edge-to-edge) | 영향 있음 (Android 16 기기에서 무시됨) |
| Android 16 기기의 opt-out 항목   | 해당 없음                     | 추가 확인 필요 (크래시 위험 안내)      |
| `immersiveSticky`, `manual` 모드 | 해당 없음                     | 영향 있음                              |
| 시스템 바 영역 레이아웃          | 해당 없음                     | 영향 있음                              |

`player_default`는 업그레이드 전(`targetSdk` 35)부터 edge-to-edge로 그려지고 있었으므로, 이번 업그레이드로 바뀌는 것이 없습니다. `player_opt_out`은 Android 15 기기에서는 지금처럼 opt-out이 적용되지만, Android 16 기기에서는 3.24 → 3.27 구간의 `player_default`와 같은 영향을 받습니다.

## 비슷하지만 다른 버전의 문서

edge-to-edge 마이그레이션 문서는 코퍼스에 다섯 가지 판본이 있습니다. 3.27 출시 전 판본, 3.27·3.32·3.35 시점 판본, 그리고 Android 16 크래시 회피 안내까지 추가된 현재 판본입니다. 판본 사이의 차이는 몇 문장에 불과해서, 버전 필터 없이 BM25로 검색하면 다섯 판본의 점수 차이가 2%도 나지 않고 1위는 3.27 판본이 아닙니다.

| 질의 (opt-out 근거) | 점수  | 판본              |
| ------------------- | ----- | ----------------- |
| 1위                 | 60.91 | 현재 판본         |
| 2위                 | 60.73 | 3.32 판본         |
| 3위                 | 60.73 | 3.35 판본         |
| 4위                 | 59.93 | 3.27 판본         |
| 5위                 | 59.84 | 3.27 출시 전 판본 |

3.27 판본이 아닌 판본을 근거로 쓰면 답이 달라집니다. 3.27 판본은 opt-out이 "Android SDK 15+를 실행하는 기기"에 적용된다고 썼지만, 3.32 판본부터는 이를 "SDK 15"로 좁혔습니다. Android 16(API 36)을 대상으로 하는 앱은 Android 16 기기에서 opt-out할 수 없기 때문입니다. 그래서 근거마다 필요한 판본을 정해 두고, 검색 결과가 다른 판본이면 문장이 같아도 받지 않습니다(`src/fma/evidence.py`, `tests/test_version_guard.py`).

예외는 두 가지입니다. 3.27 판본이 빠뜨린 다크 모드 스타일(`values-night`) 안내와, 3.35 판본 이후인 2026년 2월에 추가된 Android 16 크래시 위험 안내입니다. 이 두 경우에만 이후 판본을 인용하고, 출력에 "목표 버전 이후에 고쳐진 내용"이라고 표시합니다.

## 검색 방식 비교

질문 15개로 키워드 검색(BM25), 임베딩 검색, 그리고 각각에 버전 필터를 붙인 방식을 비교했습니다. 코퍼스에는 다섯 스냅샷이 들어 있습니다. 필터가 없는 임베딩 검색은 정답을 1위에 올린 질문이 1개뿐이었고, 15개 중 4개에서 1위가 다른 판본이었습니다. 버전 필터를 붙인 임베딩 검색은 1위 적중률 0.60으로 네 방식 중 가장 좋았고, 그래서 CLI의 기본 검색 방식으로 쓰고 있습니다. 버전 필터가 오히려 정답을 막는 경우와, 필터로도 해결되지 않는 실패도 함께 정리했습니다. 자세한 내용은 [docs/retrieval-comparison.md](docs/retrieval-comparison.md)에 있습니다.

```sh
uv run scripts/compare_retrieval.py
```

## 문서

- [docs/corpus.md](docs/corpus.md): 문서 스냅샷 기준, 판본별 차이, 버전 메타데이터의 한계
- [docs/retrieval-comparison.md](docs/retrieval-comparison.md): 검색 방식 비교 결과와 실패 분석
- [docs/resource-qualifiers.md](docs/resource-qualifiers.md): opt-out을 판단할 때 리소스 한정자를 다루는 방식과 추가 확인이 필요한 경우

## 테스트

```sh
uv run pytest
```

코퍼스(`data/raw/`)가 없으면 코퍼스가 필요한 테스트는 건너뜁니다. 임베딩 인덱스(`data/index/`)가 없으면 임베딩 검색 테스트도 건너뜁니다. 테스트 중에는 인덱스를 새로 만들지 않습니다.
