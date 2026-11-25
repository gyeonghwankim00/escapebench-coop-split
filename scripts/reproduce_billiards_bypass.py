"""Costed known-answer witness under legacy alternating split schedule.
Reproduces 73 actions / 71.05%; not a model run or a v7 timing claim.
"""
import argparse
from collections import deque
import contextlib
import hashlib
import io
import json
from pathlib import Path
from scripts.coop_original import CoopAgent
from scripts.split_metrics import reference
from scripts.original_escape import ROOT,verify_upstream


def reproduce(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
        agent=CoopAgent('game1-3-easy',tmp,None,max_steps=150)
        plan=[r for r in reference(agent.game) if r['position'].split(' -> ')[-1] in agent.role_scenes['B']]
        def call(step,messages):
            role=agent.active_role
            if role=='A':
                action='apply(key card 2, exit door)' if 'key card 2' in agent.bags['A'].tools else 'click(photo)'
            elif 'key card 2' in agent.bags['B'].tools:action='give(key card 2)'
            else:
                target=plan[0]['position'].split(' -> ')[-1];origin=agent.graph.current_scene
                if origin==target:action=plan.pop(0)['action_answer']
                else:
                    queue=deque([(origin,[])]);seen={origin};found=None
                    while queue:
                        node,path=queue.popleft()
                        if node==target:found=path;break
                        for label,dest in agent.role_relations('B',node).items():
                            if dest not in seen and (agent.graph.scenes[dest].visible or dest==agent.role_starts.get('B')):
                                seen.add(dest);queue.append((dest,path+[label]))
                    if not found:raise RuntimeError('No legal route to '+target)
                    action='move('+found[0]+')'
            return dict(raw='Action: '+action,messages=messages,backend='known-answer-witness')
        agent.model_call=call;rows=[];iterator=agent.iterate('witness',agent.game)
        while True:
            try:next(iterator)
            except StopIteration as final:
                result=final.value
                if len(agent.history)>len(rows):rows.append(agent.record())
                break
            rows.append(agent.record())
    summary=dict(game=agent.game,success=result[0],steps=len(rows),progress=rows[-1]['upstream']['tracking']['progress'],
        hints=rows[-1]['hints_used'],forced=sum(r['forced_action'] for r in rows),
        gives=sum(r['upstream']['action_answer'].startswith('give(') for r in rows),
        A_actions=sorted({r['upstream']['action_answer'] for r in rows if r['role']=='A'}),
        schedule='legacy A/B alternating',oracle='reference actions/codes known; legal movement; no helper',
        upstream_commit=verify_upstream()['commit'])
    assert summary['success'] and summary['steps']==73 and summary['progress']==71.05
    assert summary['hints']==summary['forced']==0 and summary['gives']==1
    files=['scripts/reproduce_billiards_bypass.py','scripts/coop_original.py','scripts/original_escape.py',
           'scripts/split_metrics.py','data/roles/game1-3-easy.json',
           'vendor/escapebench/data/game1-3-easy.yaml','vendor/escapebench/data/reference/key_log_1-3.txt']
    summary['sha256']={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}
    (output/'turns.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (output/'roles.json').write_bytes((ROOT/'data/roles/game1-3-easy.json').read_bytes())
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(reproduce(parser.parse_args().output),ensure_ascii=False,indent=2))
