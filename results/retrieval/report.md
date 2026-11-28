# 검색 방식 비교

질문 15개, 목표 버전 스냅샷 `flutter-3.27`, 임베딩 모델 `BAAI/bge-small-en-v1.5`, BM25는 `fma.corpus.Index`.
정답은 정해진 판본의 정해진 문서에서 정답 문장이 들어 있는 섹션입니다. 잘못된 판본@1은 1위 결과가 같은 문서의 같은 섹션이지만 판본이 다른 경우의 비율입니다.

| 방식              | hit@1 | hit@3 | MRR@10 | 잘못된 판본@1 |
| ----------------- | ----- | ----- | ------ | ------------- |
| bm25              | 0.27  | 0.40  | 0.35   | 0.13          |
| embedding         | 0.07  | 0.53  | 0.30   | 0.27          |
| bm25+version      | 0.33  | 0.53  | 0.48   | 0.07          |
| embedding+version | 0.60  | 0.67  | 0.63   | 0.07          |

## 질문별 정답 순위

`-`는 10위 안에 정답이 없음을 뜻합니다. `*`는 1위가 내용이 다른 잘못된 판본, `=`는 1위가 내용은 같지만 판본이 다른 문서임을 뜻합니다.

| 질문 | 정답 판본    | bm25 | embedding | bm25+version | embedding+version |
| ---- | ------------ | ---- | --------- | ------------ | ----------------- |
| q01  | flutter-3.27 | -    | -         | -            | -                 |
| q02  | flutter-3.27 | 2    | 7         | 2            | 1                 |
| q03  | flutter-3.27 | 1    | 3         | 1            | 1                 |
| q04  | flutter-3.27 | -    | 2         | 5            | 1                 |
| q05  | flutter-3.27 | -    | -         | 5            | -                 |
| q06  | flutter-3.27 | 1    | 5         | 1            | 3                 |
| q07  | flutter-3.27 | 5*   | 2*        | 1            | 1                 |
| q08  | flutter-3.27 | 1    | 3*        | 1            | 1                 |
| q09  | flutter-3.27 | 1    | 1         | 1            | 1                 |
| q10  | flutter-3.27 | 7    | -         | 2            | -                 |
| q11  | flutter-3.27 | 7    | 3         | 2            | 1                 |
| q12  | flutter-3.27 | -    | 2=        | 7            | 1                 |
| q13  | latest       | 3*   | 6*        | -*           | -*                |
| q14  | flutter-3.27 | -    | 2         | -            | 1                 |
| q15  | flutter-3.27 | -    | -         | 5            | 8                 |

## 질문

- q01: After upgrading Flutter from 3.24 to 3.27, my Android app now draws behind the status bar. Why did this start happening?
- q02: Which Android SDK does a Flutter 3.27 app target by default?
- q03: I pinned targetSdk to 34 in build.gradle. Will upgrading to Flutter 3.27 still make my app edge-to-edge?
- q04: How do I keep the old non edge-to-edge layout on Android 15 after moving to Flutter 3.27?
- q05: Is the windowOptOutEdgeToEdgeEnforcement opt-out a permanent solution?
- q06: My app already calls SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge). Do I need to migrate anything for Flutter 3.27?
- q07: My video player hides the system bars with SystemUiMode.immersiveSticky. Will that still work when the app targets Android 15?
- q08: Does SystemUiMode.leanBack still work on Android 15 with Flutter 3.27?
- q09: What does SystemUiMode.edgeToEdge do on Android?
- q10: How do I stop my app content from being covered by the Android status bar?
- q11: Where should I put SafeArea in a Scaffold?
- q12: Does AppBar add padding for the status bar automatically?
- q13: I added the edge-to-edge opt-out attribute but the app is still edge-to-edge in dark mode. Which styles file do I need to change?
- q14: My app never calls setEnabledSystemUIMode. Is it affected by the new edge-to-edge default in Flutter 3.27?
- q15: Which SystemUiMode values stop working on Android 15 unless I opt out of edge-to-edge?
