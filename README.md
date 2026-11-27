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

# 디렉터리로 넣기
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_default

# 파일만 골라 넣기
uv run fma audit --from 3.24.5 --to 3.27.1 path/to/build.gradle path/to/values/styles.xml path/to/main.dart

# JSON 출력
uv run fma audit --from 3.24.5 --to 3.27.1 --input samples/player_opt_out --json
```

## 샘플: 같은 업그레이드, 다른 결과

`samples/`의 두 앱은 Dart 코드와 Gradle 설정이 같고 `styles.xml`만 다릅니다. 둘 다 동영상 화면에서 `SystemUiMode.immersiveSticky`를 쓰고, `targetSdk`는 `flutter.targetSdkVersion`을 따릅니다.

| 항목 | `player_default` | `player_opt_out` |
| --- | --- | --- |
| targetSdk 변화 (34 → 35) | 영향 있음 | 영향 있음 |
| edge-to-edge opt-out | 영향 있음 (항목 없음) | 영향 없음 (항목 있음, 임시 조치) |
| `immersiveSticky`, `manual` 모드 | 영향 있음 | 해당 없음 |
| 시스템 바 영역 레이아웃 | 영향 있음 (SafeArea 없음) | 해당 없음 |

`player_opt_out`은 opt-out이 적용되므로 그 뒤 항목은 확인하지 않습니다. 대신 문서가 이 방법을 임시 조치로 안내한다는 근거를 함께 보여 줍니다.

## 비슷하지만 다른 버전의 문서

edge-to-edge 마이그레이션 문서는 코퍼스에 세 가지 판본이 있습니다. 3.27 출시 전 판본, 3.27 시점 판본, 그리고 Android 16 내용이 추가된 현재 판본입니다. 판본 사이의 차이는 몇 문장에 불과해서, 버전 필터 없이 BM25로 검색하면 세 판본의 점수 차이가 2%도 나지 않고 1위는 3.27 판본이 아닙니다.

| 질의 (opt-out 근거) | 점수 | 판본 |
| --- | --- | --- |
| 1위 | 60.54 | 현재 판본 |
| 2위 | 59.64 | 3.27 판본 |
| 3위 | 59.55 | 3.27 출시 전 판본 |

현재 판본을 근거로 쓰면 답이 달라집니다. 3.27 판본은 opt-out이 "Android SDK 15+를 대상으로 하는 앱"에 적용된다고 썼지만, 현재 판본은 Android 16부터 opt-out이 불가능하다는 이유로 이를 "SDK 15"로 좁혔습니다. 그래서 근거마다 필요한 판본을 정해 두고, 검색 결과가 다른 판본이면 문장이 같아도 받지 않습니다(`src/fma/evidence.py`, `tests/test_version_guard.py`).

예외는 하나 있습니다. 3.27 판본이 빠뜨린 다크 모드 스타일(`values-night`) 안내는 이후 판본에서 추가됐습니다. 이 경우에만 이후 판본을 인용하고, 출력에 "목표 버전 이후에 고쳐진 내용"이라고 표시합니다.

## 검색 방식 비교

질문 15개로 키워드 검색(BM25), 임베딩 검색, 그리고 각각에 버전 필터를 붙인 방식을 비교했습니다. 필터가 없는 임베딩 검색은 정답을 1위에 올린 질문이 하나도 없었고, 15개 중 5개에서 1위가 다른 판본이었습니다. 버전 필터를 붙인 임베딩 검색은 1위 적중률 0.60으로 네 방식 중 가장 좋았습니다. 버전 필터가 오히려 정답을 막는 경우와, 필터로도 해결되지 않는 실패도 함께 정리했습니다. 자세한 내용은 [docs/retrieval-comparison.md](docs/retrieval-comparison.md)에 있습니다.

```sh
uv run --group eval scripts/compare_retrieval.py
```

## 문서

- [docs/corpus.md](docs/corpus.md): 문서 스냅샷 기준, 판본별 차이, 버전 메타데이터의 한계
- [docs/retrieval-comparison.md](docs/retrieval-comparison.md): 검색 방식 비교 결과와 실패 분석

## 테스트

```sh
uv run pytest
```

코퍼스(`data/raw/`)가 없으면 코퍼스가 필요한 테스트는 건너뜁니다.
