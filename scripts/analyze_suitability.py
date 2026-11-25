"""Evaluator-only optimistic closure with observed-clue gates.
Free travel within reachable scenes, known interpretation, reference actions only.
This screens structural cooperation; it is neither a model trial nor a minimal path proof.
"""
import contextlib
import io
import json
from pathlib import Path
from scripts.split_metrics import World,reference,needed_tools,clue_annotations
from scripts.coop_original import load_roles
from scripts.run_matrix import ALL_GAMES,ROOT
from scripts.cohort_policy import load_policy


def norm(s):return ' '.join(str(s).lower().replace('\\n',' ').split())


def closure(game, mode, original=False):
    spec=load_roles(game);owner={n:r for r in 'AB' for n in spec[r]}
    if original:owner={n:'A' for n in owner}
    world=World(game,owner,None if original else spec['starts'])
    ref=reference(game);clues=clue_annotations(game)
    seen={r:set() for r in 'AB'};done=set();trace=[];escaped=False
    actors=['A'] if original or mode=='only_A' else ['B'] if mode=='only_B' else list('AB')
    def remember(role,scene,obj,text):
        for i,c in enumerate(clues):
            for j,s in enumerate(c['sources']):
                if s['object']==obj and s['scene']==scene and all(norm(e) in norm(text) for e in s['evidence']):seen[role].add((i,j))
    def observe():
        for role in actors:
            for name in world.reachable(role):
                scene=world.graph.scenes[name];remember(role,name,'@'+name,scene.desc)
                for kind in ('items','tools'):
                    key='item' if kind=='items' else 'tool'
                    for wrapper in getattr(scene,kind).values():
                        obj=wrapper[key]
                        if obj.visible:remember(role,name,obj.name,obj.current_desc())
            for tool in world.bags[role].tools.values():
                # A transferred clue tool is readable in recipient's bag.
                for c in clues:
                    for s in c['sources']:
                        if s['object']==tool.name:remember(role,s['scene'],tool.name,tool.current_desc())
    def gate(step,role):
        action=step['action_answer']
        if not action.startswith('input('):return True
        scene=step['position'].split(' -> ')[-1]
        target=action.rsplit(',',1)[-1].rstrip(')').strip()
        matches=[(i,c) for i,c in enumerate(clues) if c['target']==target and c['target_scene']==scene and norm(action.split('(',1)[1].rsplit(',',1)[0])==norm(c['answer'])]
        if not matches:return False
        knowledge=seen[role] if mode=='no_messages' or mode.startswith('only_') or original else seen['A']|seen['B']
        return any(all((i,j) in knowledge for j in range(len(c['sources']))) for i,c in matches)
    feedback=[];react=world.graph.react
    def capture(action):
        result=react(action);feedback.append((world.graph.current_scene,action,result));return result
    world.graph.react=capture
    for sweep in range(len(ref)+2):
        before=(len(done),len(seen['A'])+len(seen['B']));observe()
        for k,step in enumerate(ref):
            if k in done:continue
            scene=step['position'].split(' -> ')[-1];role=owner[scene]
            candidates=actors if step['action_answer'].startswith('craft(') else [role] if role in actors else []
            for role in candidates:
                if scene not in world.reachable(role) and not step['action_answer'].startswith('craft('):continue
                if not gate(step,role):continue
                if mode not in ('no_give','only_A','only_B') and not original:
                    world.give_all(needed_tools(step),role)
                feedback.clear();success=world.try_step(role,step)
                for where,action,reward in feedback:
                    target=action.split('(',1)[-1].rstrip(')').split(',')[-1].strip()
                    remember(role,where,target,reward)
                    if 'game end' in reward.lower():escaped=True
                if success:
                    done.add(k);trace.append(dict(index=k,role=role,scene=scene,action=step['action_answer']))
                    observe();break
            if escaped:break
        if escaped or before==(len(done),len(seen['A'])+len(seen['B'])):break
    blocked=[]
    for i,c in enumerate(clues):
        missing=[s['object'] for j,s in enumerate(c['sources']) if (i,j) not in seen['A']|seen['B']]
        if missing:blocked.append(dict(target=c['target'],missing_observed_evidence=missing))
    return dict(escape=escaped,completed=len(done),total=len(ref),trace=trace,unobserved_clues=blocked)


def main():
    policy,policy_metadata=load_policy()
    results=[]
    with contextlib.redirect_stdout(io.StringIO()):
        for game in ALL_GAMES:
            result=dict(game=game,metrics=load_roles(game)['metrics'],assessment=policy['games'][game])
            result['original']=closure(game,'full',original=True)
            for mode in ('full','no_messages','no_give','only_A','only_B'):result[mode]=closure(game,mode)
            results.append(result)
    out=ROOT/'outputs/analysis/cooperation-suitability.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(classification=policy_metadata,recommendation={t:[g for g,a in policy['games'].items() if a['tier']==t] for t in ('core','extended','negative_control','excluded')},assumptions=['Observed annotated evidence gates code inputs; no clue is invented.',
        'All reachable visible scenes are inspected for free; interpretations and reference actions are known.',
        'Full shares observations for free. no_messages allows physical clue-tool transfer; no_give shares information.',
        'No escape found is not proof of impossibility. Annotation errors and missing alternative paths can block closure.'],games=results),indent=2)+'\n')
    for r in results:
        print(r['game'],' '.join(f"{m}={r[m]['completed']}/{r[m]['total']}:{r[m]['escape']}" for m in ('original','full','no_messages','no_give','only_A','only_B')))
    print(out)

if __name__=='__main__':main()
