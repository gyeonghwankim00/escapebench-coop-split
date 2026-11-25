"""Build eight full-source cooperative instances. PyYAML is build-only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import yaml

from scripts.coop_escape import World

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/source/escapebench'
OUT = ROOT / 'data/pilot'

# Every original scene is assigned exactly once, including empty scenes and distractors.
# Gates may operate across the partition; their original effects are not deleted.
CONFIGS = [
 dict(source='1-1', id='01_mirror_workshop', title='거울과 작업실',
      b=['toolbox close-up','dining room and kitchen','dining table close-up',
         'cabinet above stove close-up','left cabinet close-up','right cabinet close-up',
         'cabinet above sink close-up','sink close-up'],
      clues=[('mirror','toolbox','cs546',['cs546']),
             ('desk lamp','safe','4713',['AMDG']),
             ('study wall','safe','4713',['A=4 D=1 G=3 M=7']),
             ('safe','right door to the exit','655324223',['655324223'])]),
 dict(source='1-3', id='02_records_billiards', title='명부와 당구실',
      b=['left corner of the hallway','the elevator room','pool table'],
      clues=[('paper 1','lockbox','7428',['Patient 2 John','Patient 3 Eric','Patient 4 Steven','Patient 7 Patrick','Patient 8 Andera']),
             ('book','lockbox','7428',['Patrick, Steven, John, Andera']),
             ('paper 2','safe','4305',['square, triangle, circle and pentagon']),
             ('pockets','pockets','2134',['XI-IX, XV-XIV, X-VII, IX-V'])]),
 dict(source='2-1', id='03_cabinet_mechanism', title='공구함과 기계 장치',
      b=['hallway cabinet','study room','utility room 2'],
      clues=[('scrip 2','safe 2','424389',['424389']),
             ('credential','phone','47515',['47515']),
             ('paper 2','locked box 2','870472',['870472'])]),
 dict(source='1-2', id='04_hospital_elevator', title='병실과 엘리베이터',
      b=['blocked path close-up','small cabinet close-up','large cabinet close-up',
         'elevator room','elevator interior','desk close-up','805 right room',
         'surgical table close-up','upper cabinet close-up'],
      clues=[('painting2','bedside drawer','150',['150']),
             ('locked drawer','locked drawer','8*4+6=6*7-4',['8 4 6 = 6 7 4']),
             ('paper with code','safe','2333',['1121 =']),
             ('drawer contents','safe','2333',['1212 +'])]),
 dict(source='2-2', id='05_shop_offices', title='상점과 사무실',
      b=['administration office corner','inner office','right side of inner office'],
      clues=[('draft','desk safe','GB24',['GB']),('waste paper','desk safe','GB24',['24']),
             ('drawer','wall safe','1040',['1040']),
             ('code note','bookshelf safe','3816',['3816']),
             ('old photo in frame','bookshelf safe 2','1986',['1986']),
             ('camera','left bookshelf safe','Genshin',['Genshin']),
             ('printed note','left bookshelf safe','10011001',['11000011']),
             ('wooden door','left bookshelf safe','10011001',['01011010']),
             ('large mouse pad','left bookshelf safe','10011001',['XOR'])]),
 dict(source='2-4', id='06_basement_laboratory', title='지하실과 실험실',
      b=['basement leftside','computer desk','experiment table area','hallway behind door'],
      clues=[('printed code paper','safe 2','7248',['7(black)-7(blue)-5(blue)-2(black)-4(black)-0(blue)-8(black)-9(blue)']),
             ('lighter','cabinate 1','9750',['IX VII L']),
             ('printed code paper','drawer 1','7509',['7(black)-7(blue)-5(blue)-2(black)-4(black)-0(blue)-8(black)-9(blue)']),
             ('sound list','waveform detector','crow',['crow(circled)']),
             ('frequency list','waveform detector','130',['crow 130 Hz']),
             ('waveform detector','iron door','2463',['2, 4, 6, 3'])]),
 dict(source='2-5', id='07_van_escape', title='밴 외부와 내부',
      b=['van in dessert','back of the van','underneath part of the van','top of the van',
         'trunk of the van','repair kit in the trunk','door of the van','drawers'],
      clues=[('old thesis paper','top drawer','2610',['[26]','[10]']),
             ('spotlight','safe box','3149',['3149']),
             ('license plate','bottom drawer','05062011',['May California 2011']),
             ('magazine','bottom drawer','05062011',['California 06']),
             ('mud','computer','Jacob Korakon',['Jacob Korakon']),
             ('paper with names','computer','1927',['Ally Liam Michael Violet']),
             ('@book shelf','computer','1927',['Ally 1','Violet 7','Michael 2','Liam 9'])]),
 dict(source='3-2', id='08_laundry_escape', title='세탁실과 관리실',
      b=['left corridor overview','end of left corridor','laundry room left corner',
         'end of right corridor','office room right side'],
      clues=[('game machine','information board','5974',['5974']),
             ('left half paper','office door password pad','5891',['58']),
             ('right half paper','office door password pad','5891',['91']),
             ('graffiti','red mail box','1998',['I - 9, II - 1, III - 4, IV - 2']),
             ('red mail box','red mail box','1998',['II I I/II I-II']),
             ('piece of paper hint','tool box','1232',['1 4 2 3 +']),
             ('code paper','tool box','1232',['4 2 1 3 (mod 4)'])]),
]


def parse_reference(path):
    """Upstream uses consecutive JSON objects, not a JSON list."""
    text = path.read_text(); decoder = json.JSONDecoder(); rows = []
    while text.strip():
        row, end = decoder.raw_decode(text.lstrip())
        rows.append(row); text = text.lstrip()[end:]
    return rows


def parse_action(raw):
    op, args = re.fullmatch(r'(\w+)\((.*)\)', raw).groups()
    args = [x.strip() for x in args.split(',')]
    keys = {'click':['target'], 'apply':['tool','target'],
            'input':['value','target'], 'craft':['first','second']}[op]
    assert len(keys) == len(args), raw
    return dict(type=op, **dict(zip(keys,args)))


def build(config):
    gid = config['source']; folder = OUT/config['id']; folder.mkdir(parents=True,exist_ok=True)
    src = SOURCE/f'game{gid}-easy.yaml'; ref = SOURCE/'reference'/f'key_log_{gid}.txt'
    original = yaml.safe_load(src.read_text()); source_rows = parse_reference(ref)
    zones = []; entities = []; scenes = []; changes = []
    for actor in 'AB':
        zones.append(dict(name=f'room {actor}', room=actor, visible=True,
                          desc=f'You are in room {actor}. Explore your accessible areas. '
                          'You can send messages and pass held objects to your partner from any area. '
                          'Original doors and mechanisms can unlock areas in either room. '
                          'Completing the original escape mechanism lets the team escape.'))
    for scene in original:
        name = scene['name']; actor = 'B' if name in config['b'] else 'A'
        zones.append(dict(name=name, room=actor, desc=scene['desc'],
                          visible=scene.get('visible',True), source_scene=name))
        scenes.append({k:deepcopy(v) for k,v in scene.items() if k not in ('items','tools')})
        for kind in ('item','tool'):
            for wrapper in scene.get(kind+'s',[]):
                obj = deepcopy(wrapper[kind]); obj['name'] = obj['name'].strip()
                obj.update(kind=kind, room=actor, zone=name,
                           position=wrapper.get('position'),
                           source=dict(file=src.name, scene=name, kind=kind, name=obj['name'],
                                       logic_sha256=hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest()))
                for state in obj['states']:
                    for t in state.get('transitions',[]):
                        if 'GAME END!' in t.get('reward',''):
                            t.setdefault('trigger',[]).append('finish_team')
                            changes.append(dict(entity=obj['name'], change='Append finish_team to original GAME END transition.'))
                entities.append(obj)
    by_name = {e['name']:e for e in entities}; by_zone = {z['name']:z for z in zones}
    assert len(by_name) == len(entities)
    assert set(config['b']) <= set(by_zone)
    clues = []
    for index,(source,target,answer,tokens) in enumerate(config['clues'],1):
        is_scene = source.startswith('@'); source_name = source.lstrip('@')
        source_obj = by_zone[source_name] if is_scene else by_name[source_name]
        clues.append(dict(id=f'I{index:02}',holder=source_obj['room'],receiver=by_name[target]['room'],
                          **({'source_scene':source_name} if is_scene else {'source_entity':source_name}),
                          target_entity=target, accepted_input=answer, evidence_text=tokens,
                          evidence_channel='description_or_action_feedback',
                          evaluation='Exposure is not comprehension. Guessed answers are bypasses.'))
    remote = []
    for e in entities:
        for si,state in enumerate(e['states']):
            for ti,t in enumerate(state.get('transitions',[])):
                for trigger in t.get('trigger',[]):
                    p = [x.strip() for x in trigger.split(',')]
                    if len(p)==4:
                        target = by_zone[p[2]] if p[1]=='scene' else by_name[p[2]]
                        if target['room'] != e['room']:
                            remote.append(dict(entity=e['name'],state=si,transition=ti,trigger=trigger,
                                               reason='Preserved original mechanical link; no remote observation is sent.'))
    spec = dict(schema_version='0.2',id=config['id'],title=config['title'],
                purpose='Full original easy instance partitioned between two actors; no puzzle/entity omission.',
                language='en',source_repository='https://github.com/qiancheng0/EscapeBench',
                source_files=[dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (src,ref)],
                rules=dict(actors=['A','B'],goal='Complete the original escape mechanism together.',
                           navigation='One move to any owned scene reachable in the original visible scene graph from its start. Free traversal is collapsed; original gates remain.',
                           communication='Explicit free-text send only; source papers remain transferable tools.',
                           hatch='Pass held tools from any area.',
                           environmental_links='Original cross-room mechanical unlocks are retained and audited.',
                           scheduling='Explicit actor, no model or budget scheduler.'),
                navigation=dict(start=original[0]['name'],scenes=scenes),zones=zones,entities=entities,
                annotations=dict(information_links=[c for c in clues if c['holder']!=c['receiver']],
                                 local_information_links=[c for c in clues if c['holder']==c['receiver']],
                                 object_links=[],failure_labels=['non-discovery','non-transmission','non-uptake']),
                modifications=['All original scenes, entities, descriptions, initial visibility, tool uses, and transitions retained.',
                               'Scenes are allocated to A/B; freely traversable paths collapse into one move.',
                               'Original remote mechanical effects retained. Each actor observes only their own scenes.',
                               'The original terminal mechanism opens the shared team escape; no added exit puzzle.',
                               'Reference adds exploration of input clues, messages, movement and required object handoffs.'],
                source_changes=changes,remote_environmental_links=remote,omitted_source_entities=[],
                limitations=['Public static answers can be guessed; communication is not hard-enforced.',
                             'Preserves upstream optional/redundant branches, including any upstream shortcuts.',
                             'No LLM evaluation or automatic semantic failure classifier has been run.'])
    path=folder/'environment.json'
    def save(): path.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
    save(); world=World(path); trace=[]; source_map=[]; announced=set()
    def step(actor,action,**meta):
        result=world.step(actor,action)
        assert result['valid'] and (result['effect'] or action['type']=='look'), (gid,len(trace)+1,actor,action,result['feedback'])
        trace.append(dict(actor=actor,action=action,**meta))
        return result
    def go(actor,zone):
        if world.location[actor]!=zone:step(actor,dict(type='move',target=zone))
    def hold(actor,name,target):
        if name in world.bags[actor]:return
        other='B' if actor=='A' else 'A'
        assert name in world.bags[other], (gid,'uncollected tool',name,target)
        step(other,dict(type='pass',tool=name))
        spec['annotations']['object_links'].append(dict(id=f'O{len(spec["annotations"]["object_links"])+1:02}',
                      object=name,sender=other,receiver=actor,target=target))
    for index,row in enumerate(source_rows,1):
        action=parse_action(row['action_answer']); typ=action['type']
        if typ=='craft':
            actor=next(a for a in 'AB' if action['second'] in world.bags[a])
            hold(actor,action['first'],action['second']); hold(actor,action['second'],action['first'])
        else:
            target=by_name[action['target']];actor=target['room']
            if typ=='input':
                for c in clues:
                    if c['target_entity']!=target['name'] or c['accepted_input']!=action['value']:continue
                    holder=c['holder']; name=c.get('source_entity'); zone=c.get('source_scene')
                    if name:
                        # A transferred paper is readable by its current owner.
                        holders=[a for a in 'AB' if name in world.bags[a]]
                        if holders:holder=holders[0]
                        else:go(holder,by_name[name]['zone'])
                    else:go(holder,zone)
                    observation=world.observe(holder)
                    evidence=observation['description'] if zone else next((e['description'] for e in observation['objects']+observation['inventory'] if e['name']==name),'')
                    if not all(t in evidence for t in c['evidence_text']):
                        # Some upstream clues appear only in a successful action reward.
                        evidence=next((e['feedback'] for e in reversed(world.events) if e['type']=='action' and e['actor']==holder and e['action'].get('target')==name and all(t in e['feedback'] for t in c['evidence_text'])), '')
                    assert evidence and all(t in evidence for t in c['evidence_text']), (gid,'clue unavailable',c,evidence)
                    if holder!=actor and c['id'] not in announced:
                        step(holder,dict(type='send',message=f'{name or zone}: {evidence}'))
                        announced.add(c['id'])
            go(actor,target['zone'])
            if typ=='apply':hold(actor,action['tool'],target['name'])
        step(actor,action,source_step=index,source_action=row['action_answer'])
        source_map.append(dict(source_step=index,cooperative_step=len(trace),action=action))
    assert world.success,(gid,'no terminal')
    spec['preservation']=dict(source_entities=len(entities),retained_entities=len(entities),
                             source_scenes=len(original),retained_scenes=len(original),
                             source_key_actions=len(source_rows),replayed_source_key_actions=len(source_map),
                             source_action_mapping=source_map)
    save()
    (folder/'reference.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n')
    initial=World(path)
    for actor in 'AB':(folder/f'initial_{actor}.json').write_text(json.dumps(initial.observe(actor),ensure_ascii=False,indent=2)+'\n')
    info=spec['annotations']['information_links'];objects=spec['annotations']['object_links']
    summary=dict(id=config['id'],title=config['title'],source=f'game{gid}-easy',
                 reference_actions=len(trace),source_key_actions=len(source_rows),
                 entities=len(entities),information_links=len(info),object_transfers=len(objects))
    lines=[f'# {config["title"]}','',f'원본: `game{gid}-easy.yaml`. 전체 원본 분할이며 축약본을 대체합니다.',
           f'객체 {len(entities)}/{len(entities)}, 장면 {len(original)}/{len(original)}, 원본 핵심 행동 {len(source_rows)}/{len(source_rows)} 보존.',
           f'협업 정답 경로: {len(trace)}행동. 물건 전달 {len(objects)}회, 교차 정보 관계 {len(info)}개.','',
           '## 방 배치','','| 방 | 원본 장면 | 물건 |','|---|---|---|']
    for z in zones:
        if 'source_scene' in z:lines.append(f'| {z["room"]} | {z["name"]} | '+', '.join(e['name'] for e in entities if e['zone']==z['name'])+' |')
    lines+=['','## 교차 정보','','| 방향 | 단서 | 사용 대상 |','|---|---|---|']
    for c in info:lines.append(f'| {c["holder"]}→{c["receiver"]} | {c.get("source_entity",c.get("source_scene"))} | {c["target_entity"]} |')
    lines+=['','## 보존 범위와 변형','',
            '- 원본의 정답·상태·숨겨진 물건·문 잠금·조합·선택적 행동·방해 물건을 유지합니다.',
            '- 원본의 이동 그래프에서 현재 도달 가능한 자기 장면만 탐색할 수 있습니다. 잠긴 장면 뒤의 하위 구역도 차단합니다.',
            '- 이동만 한 번으로 압축합니다. 원본 위치명은 두 방 안에 배정한 탐색 구역 이름입니다.',
            '- 문/전선 등 원본 기계적 연결은 반대 방에도 영향을 줄 수 있습니다. 목록은 `remote_environmental_links`에 있습니다. 상대 관찰은 공유되지 않습니다.',
            '- 원본 탈출 장치를 완료하면 팀이 탈출합니다. 별도의 인공 출구 퍼즐은 추가하지 않습니다.',
            '- 종이도 원본처럼 수집·전달 가능합니다. 정보 공유 방식은 메시지와 종이 전달 모두 가능합니다.',
            '- 정답 경로는 원본 행동을 원래 순서대로 전부 실행하고 이동·정보 확인·대화·물건 전달을 추가한 예시입니다.',
            '- 모든 원본 행동을 보존했다는 것과 모든 행동이 탈출에 반드시 필요하다는 것은 다릅니다. 원본의 우회 가능성과 중복 단계도 그대로 남습니다.',
            '- `environment.json`과 `reference.json`에는 정답이 있습니다. 에이전트에는 자기 관찰만 제공합니다.']
    (folder/'README.md').write_text('\n'.join(lines)+'\n')
    return summary


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=dict(schema_version='0.2',split='development-only',instances=[build(c) for c in CONFIGS])
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
