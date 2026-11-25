"""Validate source fingerprints, full reference preservation, gates and replays."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from scripts.coop_escape import World, replay

ROOT = Path(__file__).resolve().parents[1]


def validate(path):
    path=Path(path); data=json.loads(path.read_text())
    entities={e['name']:e for e in data['entities']}; zones={z['name']:z for z in data['zones']}
    assert len(entities)==len(data['entities']); assert len(zones)==len(data['zones'])
    for source in data['source_files']:
        assert hashlib.sha256((ROOT/source['path']).read_bytes()).hexdigest()==source['sha256']
    assert data['omitted_source_entities']==[]
    scenes={s['name']:s for s in data['navigation']['scenes']}
    assert len(scenes)==data['preservation']['source_scenes']
    assert len(entities)==data['preservation']['source_entities']
    for name,s in scenes.items():
        assert zones[name]['desc']==s['desc']
        assert zones[name]['visible']==s.get('visible',True)
        assert set(s.get('scene_relations',{}).values()) <= scenes.keys()
    remote=[]; hidden_state_anomalies=[]
    for e in entities.values():
        assert e['room'] in ('A','B') and zones[e['zone']]['room']==e['room']
        assert e['source']['scene']==e['zone'] and e['source']['kind']==e['kind']
        original=deepcopy(e)
        for key in ('kind','room','zone','source','position'):original.pop(key)
        for s in original['states']:
            for t in s.get('transitions',[]):
                if 'finish_team' in t.get('trigger',[]):
                    assert 'GAME END!' in t.get('reward','')
                    t['trigger'].remove('finish_team')
        assert hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()==e['source']['logic_sha256'], ('Changed source logic',e['name'])
        for si,s in enumerate(e['states']):
            for target in s.get('apply_to',[])+s.get('wait_for',[]):assert target in entities
            for ti,t in enumerate(s.get('transitions',[])):
                for wait in t['wait_for']:
                    p=[v.strip() for v in wait.split(',')]
                    assert p[0] in ('click','input','apply')
                    if p[0]=='apply':
                        assert entities[p[1]]['kind']=='tool'
                        assert any(e['name'] in x.get('apply_to',[]) for x in entities[p[1]]['states'])
                for trigger in t.get('trigger',[]):
                    p=[v.strip() for v in trigger.split(',')]
                    assert p[0] in ('change_state','change_visible','change_interact','become_tool','finish_team')
                    if p[0]=='finish_team':continue
                    if p[0]=='become_tool':
                        assert entities[p[1]]['kind']=='tool';continue
                    target=e
                    if len(p)==4:
                        target=zones[p[2]] if p[1]=='scene' else entities[p[2]]
                        if p[1]!='scene':assert target['kind']==p[1]
                        if target['room']!=e['room']:
                            remote.append((e['name'],si,ti,trigger))
                    else:assert len(p)==2
                    if p[0]=='change_state' and not 0<=int(p[-1])<len(target['states']):
                        # Two upstream one-use objects disappear while entering an undefined state.
                        # Preserve their bytes, but allow only permanently hidden terminal objects.
                        assert target is e and 'change_visible, False' in t['trigger']
                        assert not any(f'change_visible, item, {e["name"]}, True' in tr
                                       for other in entities.values() for st in other['states']
                                       for tx in st.get('transitions',[]) for tr in tx.get('trigger',[]))
                        hidden_state_anomalies.append(e['name'])
    assert remote==[(r['entity'],r['state'],r['transition'],r['trigger']) for r in data['remote_environmental_links']]
    for c in data['annotations']['information_links']:
        assert c['holder']!=c['receiver']
        source=entities[c['source_entity']] if 'source_entity' in c else zones[c['source_scene']]
        assert source['room']==c['holder']
        target=entities[c['target_entity']];assert target['room']==c['receiver']
        assert any(f'input, {c["accepted_input"]}' in t.get('wait_for',[]) for s in target['states'] for t in s.get('transitions',[]))
        assert c['evidence_text'] and all(token in json.dumps(source,ensure_ascii=False) for token in c['evidence_text'])
    # Compare every original key action in original order, independently of the builder's counts.
    reference_source=next(ROOT/f['path'] for f in data['source_files'] if f['path'].endswith('.txt'))
    raw=reference_source.read_text(); originals=[];decoder=json.JSONDecoder()
    while raw.strip():
        row,end=decoder.raw_decode(raw.lstrip());originals.append(row['action_answer']);raw=raw.lstrip()[end:]
    trace=json.loads(path.with_name('reference.json').read_text())
    source_steps=[r for r in trace if 'source_step' in r]
    assert [r['source_step'] for r in source_steps]==list(range(1,len(originals)+1))
    assert [r['source_action'] for r in source_steps]==originals
    for row in source_steps:
        a=row['action'];op=a['type']
        keys={'click':['target'],'apply':['tool','target'],'input':['value','target'],'craft':['first','second']}[op]
        assert op+'('+', '.join(a[k] for k in keys)+')'==row['source_action']
    world=replay(path)
    for c in data['annotations']['information_links']:
        assert c['id'] in world.exposures[c['holder']], ('Missing reference exposure',c['id'])
    actual=[(e['actor'],e['action']['tool']) for e in world.events if e['type']=='action' and e['action']['type']=='pass']
    expected=[(c['sender'],c['object']) for c in data['annotations']['object_links']]
    assert actual==expected
    controls={}
    for removed in ('send','pass'):
        control=World(path);failed=0
        for row in trace:
            if row['action']['type']!=removed:
                result=control.step(row['actor'],row['action'])
                failed+=not (result['valid'] and result['effect'])
        controls[f'without_{removed}']={'team_success':control.success,'failed_actions':failed}
    return dict(scripted_ablation_controls=controls,id=data['id'],reference_actions=world.turn,both_exits_open=world.success,
                source_entities_preserved=len(entities),source_scenes_preserved=len(scenes),
                source_key_actions_preserved=len(originals),source_logic_fingerprints_match=True,
                information_links=len(data['annotations']['information_links']),object_transfers=len(actual),
                source_hashes_match=True,remote_mechanical_links=len(remote),
                upstream_hidden_terminal_state_anomalies=hidden_state_anomalies)


if __name__=='__main__':
    results=[validate(p) for p in sorted((ROOT/'data/pilot').glob('*/environment.json'))]
    report={'validated_instances':results}
    (ROOT/'data/pilot/validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
