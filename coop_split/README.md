# EscapeBench 2인 협력 방 분할 (v3)

EscapeBench easy 12개 게임의 장면(scene)을 두 역할 A/B에 나눈 데이터입니다. 두 에이전트는 각자 자기 방만 보고 움직이며, 메시지와 물건 건네기로 협력해야 탈출할 수 있습니다.

- 분할 버전: **v3** (2026-11-16 확정, 2026-11-25 재검증)
- 원본: [qiancheng0/EscapeBench](https://github.com/qiancheng0/EscapeBench) 커밋 `2d42347446a8e9ed4f058fa415d40afa194166a5`의 `data/game*-easy.yaml`
- 장면 이름은 위 커밋의 YAML과 글자까지 같아야 합니다. `check_split.py`로 확인할 수 있습니다.

## 폴더 구성

| 파일 | 내용 | 에이전트에게 보여줘도 되나 |
|---|---|---|
| `roles/<game>.json` | 게임별 A/B 장면 목록과 B 시작 위치, 평가용 메타데이터 | `A`, `B`, `starts`만 실행에 사용. 나머지 필드는 **평가자 전용** |
| `clues.json` | 코드 입력 54개 각각의 단서 출처(어느 장면의 어느 물건). 손으로 단 주석 | **평가자 전용** |
| `cohort_policy.json` | 게임 분류(core/extended/control/excluded)와 이유 | 평가자 전용 |
| `verification.json` | 분할 검증 결과(원본 정답 경로 재생) | 평가자 전용 |
| `check_split.py` | 내 EscapeBench 데이터에 분할이 맞는지 확인하는 스크립트 | - |

## `roles/<game>.json` 형식

```jsonc
{
  "version": "v3",
  "game": "game1-1-easy",
  "A": ["living room", ...],          // A가 소유한 장면. 원본 시작 장면(YAML 첫 장면)은 항상 A
  "B": ["bathroom", ...],             // B가 소유한 장면
  "starts": {"B": "dining room and kitchen"},  // B는 처음부터 자기 방 안에서 시작
  "low_interdependence": false,       // true면 협력이 거의 필요 없는 게임 (1-3)
  // ---- 아래는 평가자 전용: 프롬프트에 절대 넣지 말 것 ----
  "metrics": {...},                   // 아래 "지표" 참고
  "cross_clues": [...],               // 방을 넘는 코드 단서 (정답 포함)
  "reference_handoffs": [...]         // 정답 경로에서 필요한 물건 건네기 (정답 포함)
}
```

**지표(`metrics`)**: 원본 정답 경로(reference key steps)를 2인 규칙으로 탐욕적으로 재생해 계산했습니다. 코드는 아는 것으로 치기 때문에 `alone_*`는 상한값입니다.

| 필드 | 뜻 |
|---|---|
| `total` | 정답 경로 단계 수 |
| `alone_A`, `alone_B` | 상대가 아무것도 안 할 때 그 역할 혼자 끝낼 수 있는 단계 수 |
| `together_no_give` | 둘 다 움직이되 `give` 없이 끝낼 수 있는 단계 수. `total`에서 이 값을 빼면 건네기가 필요한 단계 수 |
| `with_give` | `give`까지 허용했을 때 끝낼 수 있는 단계 수 |
| `b_share` | B 장면에서 일어나는 단계 비율 |
| `handoffs` | 정답 경로의 물건 건네기 수 |
| `components` | 각 역할 영역이 장면 그래프에서 몇 조각으로 나뉘는지 (2면 상대 영역을 지나가야 함) |
| `clue_inputs_cross` | 단서가 상대 방에 있는 코드 입력 수 |

## 실행 규칙 (분할 데이터의 의미)

분할 JSON은 아래 규칙과 함께 써야 같은 벤치마크가 됩니다. 원본 엔진은 수정하지 않고 그 위에 얹는 규칙입니다.

1. **장면 소유**: 각 역할은 자기 장면만 보고, 들어가고, 그 안의 물건과 상호작용합니다. 상대의 장면, 가방, 생각은 볼 수 없습니다.
2. **상대 영역 통과**: 내 장면으로 가는 길이 상대 장면을 거쳐야 하면, 그 경로의 상대 장면이 원본 엔진에서 "보이는"(잠기지 않은) 상태일 때만 이동 선택지 `Go to <내 장면> via partner area`를 줍니다. 상대 장면에 멈추거나 그 안을 보지는 못합니다. 영역이 두 조각인 게임(`components`가 2인 1-1, 1-2, 1-4, 2-1, 2-4)에서는 이 규칙이 없으면 일부 장면에 갈 수 없습니다.
3. **시작 위치**: A는 원본 시작 장면, B는 `starts.B`에서 시작합니다. B의 시작 장면이 원본에서 잠긴 문 너머(보이지 않음)여도 B는 안에 있으므로 그 장면으로 돌아갈 수 있습니다. 문이 열리기 전까지 A는 그 장면을 지나갈 수 없습니다.
4. **가방**: 역할마다 가방이 따로 있습니다. 원본의 가방은 A의 것이고, B는 빈 가방으로 시작합니다.
5. **협력 행동 두 가지** (원본의 click/craft/apply/input/move에 추가):
   - `send(message)`: 상대에게 짧은 메시지를 보냅니다(300자 이하, 빈 메시지는 실패). 상대의 다음 차례 프롬프트에 전달됩니다.
   - `give(tool)`: 내 가방의 도구를 상대 가방으로 옮깁니다. 상대에게 "건네받았다"는 알림이 갑니다.
6. **세계 상태 공유**: 게임 상태(문 열림, 퍼즐 해결, 진행률 카운터)는 하나입니다. 상대가 문을 열면 내 쪽에도 반영됩니다.
7. **탈출 판정**: 둘 중 누구든 최종 탈출을 완료하면 팀이 탈출한 것입니다.
8. **(help 모드를 쓸 때) 역할을 고려한 힌트**: 다음 정답 단계는 그 장면을 소유한 역할에게 줍니다. 그 단계에 필요한 도구가 상대 가방에 있으면, 가진 쪽에게 먼저 `give(<도구>)`를 힌트로 줍니다.

**분할에 포함되지 않는 것 (실험 프로토콜에서 정할 것)**: 차례 순서(번갈아 할지, 한 번에 몇 번 판단할지), 행동 예산, 메모리와 히스토리 길이, 프롬프트 문구. 참고로 원래 실험에서 쓴 협력 안내 문단은 아래와 같습니다. 원본 system prompt의 `Here are some reminders` 앞에 넣었습니다.

> You are playing together with a partner. The scenes are divided between the two of you: you can only see and enter your own scenes, and your partner can only see and enter theirs. You cannot see your partner's scenes, bag, or thoughts. Some clues and tools you need may be on your partner's side, and some of yours may be needed by your partner. Two more actions let you cooperate:
> - send(message): Send a short text message to your partner. For example, send(The note in my room says the code is 4305).
> - give(\<applicable tool\>): Hand a tool in your bag over to your partner. It leaves your bag and appears in your partner's bag. For example, give(screwdriver).
>
> Messages and tools from your partner will be shown to you. Changes your partner makes (such as opening a door) can also affect your scenes. The team escapes when either of you completes the final escape.

## 분할을 고른 기준

장면을 "방" 단위로 묶은 뒤(클로즈업 장면은 그것이 열리는 방에 붙임) 가능한 A/B 배정을 모두 탐색했습니다. 그래서 상대 방 안의 클로즈업을 갖는 일은 없습니다.

**필수 조건**
- `give`를 허용하면 원본(분할 없음)과 같은 수의 정답 단계를 끝낼 수 있다
- 각 역할이 혼자 정답 단계의 10% 이상을 할 수 있다 (할 일이 없는 역할 방지)
- 정답 단계의 15% 이상이 물건 건네기를 필요로 한다 (만족하는 분할이 없으면 이 조건을 빼고 `low_interdependence: true`)

**우선순위**: 방을 넘는 코드 단서가 있는 분할을 먼저 고르고, 그 안에서 두 역할의 할 일, 작업량 균형, 영역 연결성, 건네기 수, 교차 단서 수를 점수로 매겨 1위를 골랐습니다.

## 게임별 요약

| 게임 | 장면 A/B | 정답 단계 | 혼자 가능 A/B | 건네기 필요 단계 | 물건 건네기 | 교차 코드 단서 | 분류 |
|---|---|---|---|---|---|---|---|
| 1-1 | 10/10 | 40 | 13/6 | 15 | 6 | 3 | core |
| 1-2 | 15/8 | 45 | 7/12 | 26 | 8 | 1 | extended |
| 1-3 | 3/3 | 38 | 11/26 | 1 | 1 | 0 | negative control |
| 1-4 | 3/2 | 64 | 29/13 | 22 | 6 | 1 | excluded |
| 1-5 | 12/3 | 62 | 16/17 | 29 | 11 | 2 | extended |
| 2-1 | 7/5 | 45 | 11/16 | 18 | 4 | 3 | core |
| 2-2 | 4/4 | 66 | 20/14 | 32 | 7 | 3 | core |
| 2-3 | 15/20 | 95 | 19/34 | 42 | 13 | 4 | extended |
| 2-4 | 4/5 | 57 | 20/16 | 21 | 4 | 3 | core |
| 2-5 | 11/5 | 58 | 21/15 | 22 | 10 | 4 | core |
| 3-1 | 9/12 | 72 | 16/11 | 45 | 10 | 3 | extended |
| 3-2 | 5/4 | 48 | 18/8 | 22 | 5 | 4 | core |

- **core (6개)**: 주 분석 대상.
- **extended (4개)**: 협력 구조는 있지만 장면 수나 정답 경로가 길어 탐색 부담이 큽니다.
- **1-3 (negative control)**: 방 단위 분할로는 협력 의존도 15%를 만족할 수 없습니다. 협력이 거의 필요 없는 대조군입니다.
- **1-4 (excluded)**: 원본 게임 자체에 단서 순환 의존이 있습니다. 금고에 넣을 코드 7049의 단서는 그 금고를 연 뒤 이어지는 사슬(buttons → cabinet → chisel → ice → swipe card → front door)의 끝에서야 보입니다. 분할과 무관한 원본 결함이라 제외를 권합니다.

각 분류의 상세 이유는 `cohort_policy.json`에 있습니다.

## 검증

`verification.json`은 원본 엔진으로 정답 경로를 2인 규칙 아래 재생해 위 필수 조건을 다시 확인한 결과입니다(2026-11-25).

- 12개 모두 완주 가능하고, 할 일이 없는 역할이 없습니다.
- 협력 의존도 조건은 1-3만 불만족입니다(위 설명대로 예상된 결과).
- 2-3은 정답 단계 95개 중 94개까지만 재생됩니다. 분할 없는 원본도 같은 검사에서 94개입니다. 점수가 없는 click 하나가 탐욕적 재생에서 빠지는 것으로, 분할 문제가 아닙니다.
- `roles/`의 메타데이터는 재계산 값과 모두 일치합니다.

내 EscapeBench 데이터에 분할이 맞는지는 이렇게 확인합니다.

```bash
pip install PyYAML
python check_split.py /path/to/EscapeBench/data
```

YAML이 고정 커밋과 같은지, 모든 장면이 정확히 한 역할에 배정됐는지, 시작 위치가 맞는지, 각 역할이 자기 장면에 갈 수 있는지를 확인합니다. 12개 모두 `ok`가 나와야 합니다.
