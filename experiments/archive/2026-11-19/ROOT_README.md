> 2026-11-19 정리 직전의 과거 문서입니다. 현재 실행 명령은 [서버 안내](../../../server/README.md)를 사용하세요. 본문에는 당시의 현재/미검증 표현이 남아 있습니다. 상대 링크만 새 보관 위치에 맞췄습니다.

# Cooperative Escape Room Lab

**현재 전체 설계와 최종 문제 분류:** [CURRENT_DESIGN_AND_DATASET_REVIEW.md](../../CURRENT_DESIGN_AND_DATASET_REVIEW.md) — 분할 근거, Solo/Peer, 프롬프트·기억·스케줄·비용, 12문제 적합성 및 미완료 항목.

**현재 실행 (nightly-v6 / 프로토콜 v7):** Solo는 공용 가방과 양쪽 관측을 보고 매번 A/B를 선택합니다. Peer는 최대 4판단 연속 실행하고 yield/send/give로 넘깁니다. 관측 기억을 보존하고, 기본 실험은 힌트 없이 팀 500환경 행동·최대 1000판단을 사용합니다. 버전 분류 파일의 핵심 6개·확장 4개를 별도 집계하고 원본 결함 1-4는 실행에서 제외합니다. 역할별 기억 예산과 출력 형식도 통일했습니다. [설계](MATRIX_PROTOCOL.md) · [실행](../../../server/README.md).

**기존 파일럿·형식 진단은 탐색 분석으로 보관합니다.** 현재 주 실험에는 추가 안내를 사용하지 않으며, 해당 결과를 주 실험의 결측값 대신 넣지 않습니다.

**Solo vs 2-agent 본 실험은 [MATRIX_PROTOCOL.md](MATRIX_PROTOCOL.md)를 따릅니다.**
두 조건 모두 같은 분할 장면과 원본 퍼즐 엔진·기본 프롬프트·greedy 생성을 사용합니다. Solo에는 중앙 관측·공용 가방 규칙을, Peer에는 지역 관측·분리 가방·`send`·`give` 규칙을 추가합니다. 원본 기본 게임 12개 전체(easy)를 v3 분할(`data/roles/`)과 단서 주석(`data/clues.json`)으로 씁니다. 현재는 **`bash server/submit-nightly.sh`로 Qwen/Phi 500행동 파일럿을 실행**합니다. 실제 greedy 설정을 검사하는 generation 2이며, 이전 generation 1 결과는 새 비교에서 제외됩니다. [업로드·제출·결과 받기](../../../server/README.md)를 참고하세요. 전체 12문제 확장용 `submit-matrix.sh`도 유지합니다.

원본 비교용 `original_solo`는 [원본 BaseAgent 프로토콜](../../ORIGINAL_PROTOCOL.md)을 사용합니다.
원본 엔진·프롬프트·파서·힌트 처리를 고정 커밋에서 가져왔고,
서버에서는 `sbatch server/original.sbatch`로 14B의 easy 8문제를 실행합니다.
아래 기존 `run_experiment`/two-models 방식은 원본과 다른 **개발용 파일럿**입니다.

EscapeBench 원본 문제를 두 에이전트의 방으로 나눈 개발 데이터셋과 로컬 플레이 앱입니다. **현재 8개 문제 = 기존 3개 전체 복원 + 신규 5개**입니다. 방 A/B는 한 문제의 두 역할이므로 16개 문제로 세지 않습니다.

이전 v0.1은 원본 일부만 뽑은 축약 파일럿이었습니다. 현재 v0.2는 이를 교체하며, 선택한 easy 원본의 **객체 339/339개, 장면 103/103개, 정답 로그의 핵심 행동 397/397개**를 보존합니다. 원본의 설명·암호·숨김 상태·도구 조합·문 개방 조건·선택적 경로·방해 물건도 유지합니다. 예전 출력 로그와 세션은 v0.1 결과이므로 새 실행과 섞지 마세요.

## 문제 목록

| 번호 | 문제 | 원본 | 원본 객체 | 원본 핵심 행동 | 협업 정답 행동 |
|---|---|---|---:|---:|---:|
| 01 | [거울과 작업실](../../../data/pilot/01_mirror_workshop/README.md) | game1-1-easy | 38 | 40 | 74 |
| 02 | [명부와 당구실](../../../data/pilot/02_records_billiards/README.md) | game1-3-easy | 34 | 38 | 61 |
| 03 | [공구함과 기계 장치](../../../data/pilot/03_cabinet_mechanism/README.md) | game2-1-easy | 40 | 45 | 67 |
| 04 | [병실과 엘리베이터](../../../data/pilot/04_hospital_elevator/README.md) | game1-2-easy | 34 | 45 | 73 |
| 05 | [상점과 사무실](../../../data/pilot/05_shop_offices/README.md) | game2-2-easy | 55 | 66 | 95 |
| 06 | [지하실과 실험실](../../../data/pilot/06_basement_laboratory/README.md) | game2-4-easy | 47 | 57 | 83 |
| 07 | [밴 외부와 내부](../../../data/pilot/07_van_escape/README.md) | game2-5-easy | 49 | 58 | 97 |
| 08 | [세탁실과 관리실](../../../data/pilot/08_laundry_escape/README.md) | game3-2-easy | 42 | 48 | 81 |

협업 행동에는 원본 핵심 행동 외에 이동, 입력 전 단서 확인, 메시지, 물건 전달이 포함됩니다. 최단 경로나 모델 예상 턴 수가 아닙니다. 원본 정답 로그는 모든 이동을 포함한 로그가 아니므로 두 열을 순수 협업 비용으로 비교하면 안 됩니다.

원본 아카이브에는 **기본 문제 12개 × easy/기본/hard 3종 = YAML 36개**가 있습니다. 현재는 서로 다른 기본 문제 8개의 easy 버전만 분할했습니다. 나머지 기본 문제는 `game1-4`, `game1-5`, `game2-3`, `game3-1`입니다. 모두 확장하면 기본 협업 문제 12개, 난이도까지 모두 변환하면 설정 36개가 됩니다. 난이도 변형을 독립 문제 36개로 간주하거나 train/test에 나눠 넣으면 안 됩니다. 파일 목록은 [원본 인벤토리](../../../data/source/escapebench/upstream_inventory.json)에 있습니다.

## 무엇을 보존했고 어떻게 나눴는가

각 원본 장면을 A 또는 B에 한 번씩 배정합니다. 원본의 큰 지도는 두 방 안의 탐색 구역들로 재배치됩니다. 각 문제 README에 장면별 배치와 교차 정보 관계가 있습니다.

- **퍼즐 로직:** 원본 객체를 삭제하거나 미리 열어 두지 않습니다. `wait_for`, `apply_to`, 상태 전이와 정답을 유지합니다. 종이도 원본처럼 집어서 전달할 수 있습니다.
- **접근 조건:** 원본 시작점에서 현재 보이는 장면 연결을 따라 도달 가능한 자기 구역만 방문할 수 있습니다. 잠긴 서재 뒤의 사진 확대 구역처럼, 하위 구역 자체가 visible이어도 입구가 막혀 있으면 접근할 수 없습니다.
- **이동:** 접근 가능한 자기 구역까지의 자유 이동을 한 행동으로 압축합니다. 상대 구역으로 직접 이동하거나 상대 물건을 조작할 수 없습니다.
- **기계적 연결:** 원본 장치가 반대 방의 문이나 물건을 해제하는 효과는 보존합니다. 직접 트리거는 `remote_environmental_links`에 기록하고, 문 뒤 하위 구역의 간접 개방은 `navigation`의 원본 연결 그래프로 결정합니다. 상대의 관찰 내용은 자동 공유하지 않습니다. 따라서 완전히 독립적인 방에 메시지와 해치만 연결된 설정과는 다릅니다.
- **탈출:** 원본 `GAME END!` 조건을 만족하면 팀 탈출입니다. 기존 축약본의 인공 출구 덮개·추가 출구 퍼즐은 제거했습니다. API의 `own_exit_open` 두 값은 원본 최종 탈출 시 함께 true가 됩니다.

1번은 서랍→칼→상자→문손잡이→욕실, 배수구→서재 열쇠, 사진 뒤 거울 조각, 거울→공구함, 환풍기→사물함 열쇠→망치 조합→벽 파괴, 손전등 조합, 램프 수리, 문자 대응→금고→최종 출구를 모두 복원했습니다. 드라이버도 다시 원본 환풍기에 사용합니다.

## 이전 개발용 모델 테스트

기존 8문제 Solo GPU 실행 결과를 바탕으로 [새 Solo 비교 실험](../../README.md)을 추가했습니다.
02·06번에서 thinking 켬/끔 × 정체 시 힌트 있음/없음을 비교하고, 실제 퍼즐 진행률과
첫 힌트 전 진행률을 기록합니다. 새 프로토콜은 아직 GPU에서 실행하지 않았습니다.

```bash
python3 -m scripts.run_experiment --dry-run
bash server/upload.sh
# 서버의 ~/escape-lab에서 제출
# sbatch server/experiment.sbatch
```

[서버 실행 안내](../../../server/README.md)에 SSH 접속·설치·Slurm 제출 절차가 있습니다.
기본 모델은 Qwen3-8B NF4 4비트입니다. 아래 기존 명령은 A/B 플레이의 간단한 실행
확인용으로 유지하며 새 Solo 실험과 결과를 구분합니다.

```bash
# 로컬: 모델 다운로드 없이 A/B 입력만 미리 보기
python3 -m scripts.run_model --dry-run

# 서버: 반드시 Slurm GPU 할당 안에서 실행
bash server/setup.sh
bash server/run.sh --max-steps 30
```

## 브라우저 실행

Python 3.10 이상에서 별도 패키지·GPU·API 키 없이 실행합니다.

```bash
python3 app.py
```

브라우저에서 <http://127.0.0.1:8765>를 엽니다. 이미 실행 중인 이전 서버가 있다면 `Ctrl+C`로 종료하고 다시 실행해야 새 8개 목록을 읽습니다. 포트가 사용 중이면 `python3 app.py --port 8766`을 사용합니다.

혼자 체험하면 A/B를 전환할 수 있습니다. 두 사람 모드의 참여 링크는 같은 컴퓨터의 다른 탭에서 사용합니다. 서버는 로컬 접속만 허용합니다. 각 역할은 자기 방 관찰과 자기 인벤토리, 받은 메시지만 봅니다. UI는 한국어이며 원본 설명과 새 구역 이름은 영어입니다.

구역 이동, 물건 수집·사용·조합, 문자열 입력, 메시지, 해치 전달을 지원합니다. **진행은 서버 메모리에만 저장**됩니다. 종료 전에 저장 버튼으로 역할별 기록을 내려받으세요.

## 검증과 재생

```bash
python3 -m scripts.validate_pilot
python3 -m unittest discover -s tests -v
python3 scripts/coop_escape.py data/pilot/01_mirror_workshop/environment.json \
  --replay --log outputs/01_full_reference.jsonl
```

8개 모두 정답 재생으로 팀 탈출을 확인했습니다. 검증은 원본 파일 SHA-256, 객체 로직 지문, 모든 원본 핵심 행동의 순서·내용, 장면 잠금, 교차 트리거 목록, 단서 노출, 물건 전달을 검사합니다. 결과는 [validation.json](../../../data/pilot/validation.json)에 기록됩니다.

원본에서 사용 후 사라지는 `blender machine`과 `pipe on machine`은 정의되지 않은 종료 상태 번호를 가리킵니다. 원본을 수정하지 않고, 같은 전이에서 영구적으로 숨겨지는 경우만 허용하여 검증 결과에 별도로 기록했습니다.

**원본 과정을 모두 보존한다는 것이 모든 과정의 필수성을 뜻하지는 않습니다.** 원본의 선택적 행동이나 우회도 유지했습니다. 고정 답을 아는 스크립트는 메시지를 전부 제거해도 8개 모두 성공합니다. 물건 전달을 제거하면 8개 모두 정답 경로의 중간 행동이 실패하지만, 1번은 알려진 최종 암호 입력만으로 탈출할 수 있습니다. `scripted_ablation_controls`에 이 결과를 남겼습니다. 이는 모델 실험이나 모든 경로에 대한 필수성 증명이 아닙니다.

## 파일과 모델 연결

```text
data/source/escapebench/           수정하지 않은 원본 YAML 8개와 정답 로그
data/pilot/manifest.json          현재 8개 문제 목록
data/pilot/<id>/environment.json  서버 전용 전체 상태·정답·원본 보존 기록
data/pilot/<id>/reference.json    원본 행동+협업 행동 정답 경로
data/pilot/<id>/initial_A.json    A의 초기 관찰
data/pilot/<id>/initial_B.json    B의 초기 관찰
data/pilot/<id>/README.md         방 배치와 교차 정보 관계
data/pilot/agent_instructions.txt 공통 행동 지침
scripts/build_pilot.py            재현 가능한 원본→협업 데이터 생성기
scripts/coop_escape.py            환경 실행기
scripts/validate_pilot.py         보존 검사와 재생 검증
```

`environment.json`과 `reference.json`은 모델에게 주면 안 됩니다. 오픈 모델 호출·A/B 교대·턴 예산은 `scripts/run_model.py`에 구현했습니다. 실제 GPU 실행은 아직 검증하지 못했고, 실패 유형 자동 분류기는 구현하지 않았습니다.

```python
from scripts.coop_escape import World
world = World("data/pilot/01_mirror_workshop/environment.json")
observation = world.observe("A")  # A 모델의 독립 문맥에만 전달
result = world.step("A", {"type": "move", "target": "bedroom"})
# B는 다음 자기 턴에 world.observe("B")를 받음
```

행동은 `look`, `move`, `click`, `apply`, `input`, `craft`, `send`, `pass`, `wait`입니다. 정확한 JSON 형식은 `agent_instructions.txt`를 참고하세요.

정보 주석은 원본 단서에서 반대 방 입력 대상으로 이어지는 관계를 기록합니다. 이들만으로 모든 협업 행동이 주석화되는 것은 아닙니다. 단서 노출은 현재 설명이나 자기 행동 피드백으로 읽은 사실이며 이해를 보장하지 않습니다. 종이 전달도 정보 전달 수단이므로 실패 분석에서 메시지만 세면 안 됩니다. non-discovery / non-transmission / non-uptake를 적용할 때 선행 조건 미충족은 blocked, 기회 부족은 censored, 추측은 bypass로 구분해야 합니다. 공개 정답의 오염 방지와 모델 실험은 아직 진행하지 않았습니다.

## 데이터 재생성

생성된 데이터로 실행·검증할 때는 외부 패키지가 필요 없습니다. 원본 YAML부터 다시 생성할 때만 PyYAML이 필요합니다.

```bash
python3 -m pip install -r requirements-build.txt
python3 -m scripts.build_pilot
python3 -m scripts.validate_pilot
```

출처: [EscapeBench 공식 저장소](https://github.com/qiancheng0/EscapeBench), [ACL 2025 논문](https://aclanthology.org/2025.acl-long.39/). 원본 출처와 스냅샷 정보는 [source README](../../../data/source/escapebench/README.md)에 있습니다.
