# 밴 외부와 내부

원본: `game2-5-easy.yaml`. 전체 원본 분할이며 축약본을 대체합니다.
객체 49/49, 장면 16/16, 원본 핵심 행동 58/58 보존.
협업 정답 경로: 97행동. 물건 전달 9회, 교차 정보 관계 5개.

## 방 배치

| 방 | 원본 장면 | 물건 |
|---|---|---|
| B | van in dessert | wild cactus, wood stick |
| B | back of the van |  |
| B | underneath part of the van | license plate space, iron wire, stepladder, bunch of keys, license plate, shelf key, mental card |
| B | top of the van | spotlight, solar panel slot, skylight, silver key |
| B | trunk of the van | trunk door, rag, wire cutter |
| B | repair kit in the trunk | repair kit box, engine oil |
| B | door of the van | van door, mud |
| A | van indoor front overview | seat switch, water bottle |
| A | front desk | left seat, solar panel, magazine |
| A | book shelf | wrench |
| A | computer on the desk | computer, old thesis paper |
| A | passage way in van | microwave, shelf door 1, shelf door 2, cup, tin foil, screwdriver, cup with hot water |
| B | drawers | top drawer, bottom drawer, battery clip, paper with names |
| A | bed overview | torch light, bed shelf 2, bed shelf 1, battery, torch light with power, light bulb |
| A | right side of bed | generator |
| A | bed shelf inside | safe box, scraper, USB flash disk |

## 교차 정보

| 방향 | 단서 | 사용 대상 |
|---|---|---|
| A→B | old thesis paper | top drawer |
| B→A | spotlight | safe box |
| A→B | magazine | bottom drawer |
| B→A | mud | computer |
| B→A | paper with names | computer |

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
