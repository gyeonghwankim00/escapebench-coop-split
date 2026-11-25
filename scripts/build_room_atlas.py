from pathlib import Path
import json,html,re
import yaml
R=Path(__file__).resolve().parents[1]; OUT=R/'experiments/figures';OUT.mkdir(exist_ok=True)
configs={
'game1-1-easy':dict(title='거울과 작업실',tag='핵심 · 양방향 연쇄',why='거울 복원 정보와 공구, 서재의 단서와 주방 금고, 마지막 출구가 양쪽을 오간다.',groups=[(0,'거실',40,80,350,170,[1]),(2,'침실',430,80,350,245,[3,4]),(5,'욕실',430,405,350,230,[6,7]),(8,'식당·주방',40,405,350,370,[9,10,11,12,13,14]),(15,'서재',820,80,350,370,[16,17,18,19])],labels={1:'전화 수납장',3:'공구상자',4:'종이상자',6:'거울',7:'환풍기',9:'식탁',10:'가스레인지 위 수납장',11:'왼쪽 수납장',12:'오른쪽 수납장',13:'싱크대 위 수납장',14:'싱크대',16:'서재 벽',17:'사진',18:'책상',19:'사물함'}),
'game1-3-easy':dict(title='당구장',tag='대조군 · 시작 위치 우회',why='B가 잠긴 당구장 안에서 시작해 A의 진입 과정을 우회한다. 메시지 없이 내부를 풀고 최종 카드만 전달하는 경로가 있다.',groups=[(0,'복도',40,100,350,150,[]),(1,'복도 왼쪽 구석',40,400,350,150,[]),(2,'엘리베이터실',430,100,350,150,[]),(3,'당구장',820,400,350,270,[4,5])],labels={4:'프런트 데스크',5:'당구대'}),
'game2-4-easy':dict(title='지하 연구실',tag='핵심 · 후반 통신 병목',why='B의 소리·주파수 자료 → A의 파형 검출기 → B의 출구로 정보가 돌아온다. 메시지 병목은 참조 행동의 마지막 3/57에 집중된다.',groups=[(0,'지하실 입구',40,100,350,150,[]),(1,'지하실 왼쪽',40,400,350,230,[2]),(3,'문 뒤 복도',430,100,350,150,[]),(4,'연구실',820,100,350,310,[5,6,7]),(8,'캐빈실',820,535,350,150,[])],labels={2:'제어 장치',5:'컴퓨터 책상',6:'금고 벽',7:'실험 테이블'})}
def esc(s):return html.escape(str(s),quote=True)
def text(x,y,s,size=16,fill='#243247',weight='400'):
 return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}">{esc(s)}</text>'
payload={}
for game,c in configs.items():
 scenes=yaml.safe_load((R/'vendor/escapebench/data'/f'{game}.yaml').read_text()); roles=json.loads((R/'data/roles'/f'{game}.json').read_text()); names=[s['name'] for s in scenes]
 assert sorted(i for g in c['groups'] for i in [g[0],*g[6]])==list(range(len(scenes)))
 owner={n:r for r in 'AB' for n in roles[r]};starts={'A':names[0],'B':roles['starts']['B']}
 group_by_name={scenes[g[0]]['name']:g for g in c['groups']}
 for mode in ['original','A','B']:
  parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="860" viewBox="0 0 1200 860" role="img">',f'<title>{esc(c["title"])} — {mode}</title>', '<rect width="1200" height="860" fill="#f5f7fb"/>','<g font-family="Arial, Apple SD Gothic Neo, sans-serif">']
  parts += [text(40,35,('원본 전체 공간' if mode=='original' else f'분할 후 역할 {mode} 영역')+' · '+c['title'],24,weight='700'),text(40,60,'개념 평면도 · 실제 치수/방향 아님 · 숫자는 원본 장면 번호 · 세부 이동은 연결 목록 참조',14)]
  # Inter-room topology only; lines are drawn in free gutters, not physical walls.
  seen=set()
  for name,g in group_by_name.items():
   for target in (scenes[g[0]].get('scene_relations') or {}).values():
    if target not in group_by_name:continue
    pair=tuple(sorted([name,target]))
    if pair in seen:continue
    seen.add(pair);h=group_by_name[target]
    ax,ay=g[2]+g[4]/2,g[3]+g[5]/2;bx,by=h[2]+h[4]/2,h[3]+h[5]/2
    cross=mode!='original' and owner[name]!=owner[target]
    col='#b38024' if cross else '#7e91a8'
    parts.append(f'<path d="M {ax} {ay} L {bx} {by}" fill="none" stroke="{col}" stroke-width="5" stroke-dasharray="{("9 7" if cross else "none")}"/>')
  for idx,label,x,y,w,h,children in c['groups']:
   name=names[idx];o=owner[name];own=mode=='original' or o==mode
   color=('#e9eff7' if mode=='original' else '#e1eefc' if mode=='A' else '#e0f2eb') if own else '#eceef1'
   stroke=('#344f74' if mode=='original' else '#2866aa' if mode=='A' else '#19775d') if own else '#b6beca'
   parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{color}" stroke="{stroke}" stroke-width="3"/>')
   parts.append(text(x+15,y+28,f'{idx+1:02}  {label}'+('' if own else ' · 상대 구역'),21,weight='700'))
   parts.append(text(x+15,y+51,name,12))
   marks=[]
   if mode=='original' and idx==0:marks.append('원본 시작')
   if mode!='original' and name==starts[mode]:marks.append(mode+' 시작')
   if not scenes[idx].get('visible',True):marks.append('원본 초기 hidden')
   parts.append(text(x+15,y+76,' / '.join(marks) or ('A 배정' if o=='A' else 'B 배정') if mode!='original' else ' / '.join(marks),13,'#805b19'))
   if not own:
    parts.append(text(x+15,y+112,'이 역할은 내부에서 직접 행동 불가',15,'#687386'));continue
   for j,child in enumerate(children):
    cy=y+92+j*42
    parts.append(f'<rect x="{x+12}" y="{cy}" width="{w-24}" height="36" rx="4" fill="#ffffff" stroke="#bcc8d6"/>')
    suffix=' [hidden]' if not scenes[child].get('visible',True) else ''
    parts.append(text(x+22,cy+24,f'{child+1:02}  '+c['labels'][child]+suffix,16))
  parts += [text(40,815,'실선: 원본의 구역 간 연결 존재(방향·가시 조건은 아래 목록)   점선: A/B를 가르는 원본 연결',14),text(40,840,'hidden은 장면 자체의 초기 값. 하위 장면이 visible이어도 부모 진입이 막히면 접근 불가. 회색은 설명용이며 모델에 제공하지 않음.',13),'</g></svg>']
  (OUT/f'{game}-{mode}.svg').write_text(''.join(parts))
 payload[game]={'title':c['title'],'tag':c['tag'],'why':c['why'],'roles':roles,'scenes':scenes}

# Rich atlas: object dependencies from YAML + annotated clue links, verified Solo trace.
from scripts.replay_atlas import trace
clues=json.loads((R/'data/clues.json').read_text())['games']
for game,d in payload.items():
    scene_names=[s['name'] for s in d['scenes']]
    owner={n:r for r in 'AB' for n in d['roles'][r]}
    objects=[]; links=[]
    for si,scene in enumerate(d['scenes']):
        for plural,kind in [('items','item'),('tools','tool')]:
            for entry in scene.get(plural,[]):
                obj=entry[kind]
                objects.append(dict(id=len(objects),name=obj['name'],scene=si,kind=kind,
                    position=entry.get('position',''),hidden=not obj.get('visible',True),
                    desc=obj['states'][0].get('desc',''),states=obj['states']))
    byname={o['name']:o for o in objects}
    def link(source,target,kind,note):
        if source not in byname or target not in byname:return
        a,b=byname[source],byname[target]
        record=dict(source=a['id'],target=b['id'],kind=kind,note=note,
                    cross=owner[scene_names[a['scene']]]!=owner[scene_names[b['scene']]])
        if not any((l['source'],l['target'],l['kind'])==(a['id'],b['id'],kind) for l in links):links.append(record)
    for obj in objects:
        for state in obj['states']:
            if obj['kind']=='tool':
                for target in state.get('apply_to',[]):
                    link(obj['name'],target,'craft' if target in byname and byname[target]['kind']=='tool' else 'tool','YAML의 도구 사용 대상. 사용 전 상태·해금 조건이 필요할 수 있음.')
            else:
                for transition in state.get('transitions',[]):
                    for requirement in transition.get('wait_for',[]):
                        op,sep,value=requirement.partition(',')
                        if op.strip()=='apply':link(value.strip(),obj['name'],'tool','YAML의 apply 선행 조건')
                    for trigger in transition.get('trigger',[]):
                        parts=[x.strip() for x in trigger.split(',')]
                        if len(parts)==4 and parts[0]=='change_visible' and parts[1] in ('tool','item') and parts[-1]=='True':
                            link(obj['name'],parts[2],'reveal','이 대상의 특정 전이가 숨은 물건을 공개함. 클릭만으로 항상 공개되는 것은 아님.')
    for clue in clues.get(game,[]):
        for source in clue['sources']:link(source['object'],clue['target'],'clue','평가용 단서 주석. 다른 단서와 결합하거나 후속 상태에서 읽어야 할 수 있음.')
    route=trace(game,'solo')
    peer_route=trace(game,'peer')
    d.update(objects=objects,links=links,route=route,peer_route=peer_route,escaped=True,
             groups=[dict(scene=g[0],title=g[1],children=g[6]) for g in configs[game]['groups']],
             labels={str(i):configs[game]['labels'].get(i,next((g[1] for g in configs[game]['groups'] if g[0]==i),scene_names[i])) for i in range(len(scene_names))})
    for obj in objects:del obj['states']
template=(R/'scripts/room_atlas_template.html').read_text()
(OUT/'room-atlas.html').write_text(template.replace('__ATLAS_DATA__',json.dumps(payload,ensure_ascii=False).replace('</','<\/')))
print('Built atlas:', [(k,len(v['objects']),len(v['links']),len(v['route']),len(v['peer_route'])) for k,v in payload.items()])
