# flutter_migration_audit

Flutter 업그레이드 구간을 입력하면 공식 마이그레이션 문서에서 근거를 찾아 영향 조건, 테스트할 항목, 출처를 보여주는 도구입니다. 문서만으로 판단할 수 없으면 확인해야 할 설정을 알려 주고 멈춥니다.

## 첫 버전 범위

- 업그레이드 구간: Flutter 3.24 → 3.27
- 주제: Android 화면 및 시스템 바 변경 (edge-to-edge, `SystemUiMode`, 상태바·내비게이션 바)
- 검증 질문: 15개
- 비교 대상: 키워드 검색, 임베딩 검색, 버전 필터를 붙인 검색
- 제외: GitHub 연동, 코드 자동 수정

## 왜 버전이 중요한가

docs.flutter.dev의 breaking change 문서는 발행 이후에도 계속 수정됩니다. 예를 들어 [Set default of `SystemUiMode` to edge-to-edge](https://docs.flutter.dev/release/breaking-changes/default-systemuimode-edge-to-edge)는 3.27과 함께 나왔지만, 2025년 6월 이후 Android 16 관련 내용이 추가되었습니다. 3.27 시점의 질문에 현재 문서를 그대로 쓰면 그 시점에는 없던 내용이 답에 섞일 수 있습니다. 그래서 이 프로젝트는 [flutter/website](https://github.com/flutter/website) 저장소에서 릴리스 날짜 기준으로 문서 스냅샷을 만들어 검색 코퍼스로 사용합니다.
