# 거울과 작업실

원본: `game1-1-easy.yaml`. 전체 원본 분할이며 축약본을 대체합니다.
객체 38/38, 장면 20/20, 원본 핵심 행동 40/40 보존.
협업 정답 경로: 74행동. 물건 전달 7회, 교차 정보 관계 4개.

## 방 배치

| 방 | 원본 장면 | 물건 |
|---|---|---|
| A | living room | telephone cabinet, left door to the study, right door to the exit |
| A | telephone cabinet close-up | drawer, telephone, hairpin, carving knife |
| A | bedroom | bathroom door, hammer handle |
| B | toolbox close-up | toolbox, screwdriver, fuse |
| A | cardboard box close-up | cardboard box, door handle |
| A | bathroom | plunger |
| A | mirror close-up | mirror |
| A | ventilation fan close-up | ventilation fan, locker key |
| B | dining room and kitchen |  |
| B | dining table close-up | shard_1 |
| B | cabinet above stove close-up | food and spices, pot, flashlight |
| B | left cabinet close-up | safe |
| B | right cabinet close-up | battery |
| B | cabinet above sink close-up | shard_2 |
| B | sink close-up | trash bin, cabinet_under_sink, garbage, study key |
| A | study |  |
| A | wall close-up | study wall |
| A | photo close-up | photo_1, photo_2, photo_3, shard_3 |
| A | desk close-up | desk lamp |
| A | locker close-up | locked locker door, hammer, shard_4 |

## 교차 정보

| 방향 | 단서 | 사용 대상 |
|---|---|---|
| A→B | mirror | toolbox |
| A→B | desk lamp | safe |
| A→B | study wall | safe |
| B→A | safe | right door to the exit |

## 보존 범위와 변형

- 원본의 정답·상태·숨겨진 물건·문 잠금·조합·선택적 행동·방해 물건을 유지합니다.
- 원본의 이동 그래프에서 현재 도달 가능한 자기 장면만 탐색할 수 있습니다. 잠긴 장면 뒤의 하위 구역도 차단합니다.
- 이동만 한 번으로 압축합니다. 원본 위치명은 두 방 안에 배정한 탐색 구역 이름입니다.
- 문/전선 등 원본 기계적 연결은 반대 방에도 영향을 줄 수 있습니다. 목록은 `remote_environmental_links`에 있습니다. 상대 관찰은 공유되지 않습니다.
- 원본 탈출 장치를 완료하면 팀이 탈출합니다. 별도의 인공 출구 퍼즐은 추가하지 않습니다.
- 종이도 원본처럼 수집·전달 가능합니다. 정보 공유 방식은 메시지와 종이 전달 모두 가능합니다.
- 정답 경로는 원본 행동을 원래 순서대로 전부 실행하고 이동·정보 확인·대화·물건 전달을 추가한 예시입니다.
- 모든 원본 행동을 보존했다는 것과 모든 행동이 탈출에 반드시 필요하다는 것은 다릅니다. 원본의 우회 가능성과 중복 단계도 그대로 남습니다.
- `environment.json`과 `reference.json`에는 정답이 있습니다. 에이전트에는 자기 관찰만 제공합니다.
