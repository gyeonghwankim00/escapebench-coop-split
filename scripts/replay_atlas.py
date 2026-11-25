"""Evaluator-only atlas witnesses. Oracle action order; real v7 observations and rules."""
from collections import deque
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile

from scripts.adaptive_escape import AdaptivePeer
from scripts.check_protocol import replay_solo
from scripts.split_metrics import reference

ROOT=Path(__file__).resolve().parents[1]


def snapshot(agent):
    return dict(where=dict(agent.where),bags={r:sorted(agent.bags[r].tools) for r in 'AB'})


def move_toward(agent,role,target):
    if agent.where[role]==target:return None
    queue=deque([(agent.where[role],[])]);seen={agent.where[role]}
    while queue:
        node,path=queue.popleft()
        if node==target:return 'move('+path[0]+')'
        for label,dest in agent.role_relations(role,node).items():
            if dest not in seen and (agent.graph.scenes[dest].visible or dest==agent.role_starts.get(role)):
                seen.add(dest);queue.append((dest,path+[label]))
    raise AssertionError(f'No legal route for {role}: {agent.where[role]} -> {target}')


def peer_replay(game,on_prompt):
    """Sequential reference plan with real gives, yields and observable-source messages.

    The coordinator knows reference answers and clue annotations. This is a mechanics
    witness, not two autonomous agents or proof that the messages suffice for reasoning.
    """
    with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
        agent=AdaptivePeer(game,tmp,None,max_steps=1000)
        plan=deque(enumerate(reference(game)))
        clues=json.loads((ROOT/'data/clues.json').read_text())['games'][game]
        sent=set();chunks={}
        def call(step,messages):
            on_prompt(step,messages,agent)
            active=re.search(r'Active role: ([AB])\.',messages[-1]['content'])[1]
            index,ref=plan[0];target=ref['position'].split(' -> ')[-1]
            role=agent.owner[target];action=ref['action_answer']
            op,args=action.split('(',1);args=[a.strip() for a in args[:-1].split(',')]
            # Transfer prerequisite tools before working at the reference location.
            required=args[:1] if op=='apply' else args if op=='craft' else []
            for tool in required:
                holder,name=agent.holder(tool)
                if holder and holder!=role:
                    raw=f'give({name})' if active==holder else 'yield()'
                    return dict(raw='Thought: Transfer the required tool.\nAction: '+raw,messages=messages)
            if op=='input':
                for clue in clues:
                    if clue['target']!=args[-1] or str(clue['answer'])!=args[0]:continue
                    for source in clue['sources']:
                        task=(index,source['scene'],source['object'])
                        if task in sent:continue
                        holder,_=agent.holder(source['object'])
                        source_role=holder or agent.owner[source['scene']]
                        if source_role==role:
                            sent.add(task);continue
                        if active!=source_role:return dict(raw='Thought: Allow the clue owner to share observations.\nAction: yield()',messages=messages)
                        if task not in chunks:
                            if holder:
                                obj=agent.bags[holder].tools[source['object']]
                            else:
                                move=move_toward(agent,source_role,source['scene'])
                                if move:return dict(raw='Thought: Visit the clue source.\nAction: '+move,messages=messages)
                                scene=agent.graph.scenes[source['scene']]
                                wrap=scene.items.get(source['object']) or scene.tools.get(source['object'])
                                assert wrap,source
                                obj=wrap.get('item') or wrap.get('tool')
                                assert obj.visible,source
                            # Copy only the actual public description, not annotation answers.
                            desc=' '.join(obj.current_desc().split())
                            assert desc in ' '.join(messages[-1]['content'].split()),(game,source)
                            payload=source['object']+': '+desc
                            chunks[task]=deque(payload[i:i+280] for i in range(0,len(payload),280))
                        message=chunks[task].popleft()
                        if not chunks[task]:sent.add(task)
                        return dict(raw='Thought: Share the observed clue text.\nAction: send('+message+')',messages=messages)
            if active!=role:return dict(raw='Thought: Allow the reference action owner to proceed.\nAction: yield()',messages=messages)
            move=move_toward(agent,role,target)
            if move:action=move
            else:plan.popleft()
            return dict(raw='Thought: Execute the reference plan.\nAction: '+action,messages=messages)
        agent.model_call=call
        iterator=agent.iterate('atlas-reference',game)
        try:
            while True:next(iterator)
        except StopIteration as final:escaped=final.value[0]
        assert escaped,game
    return agent,escaped


def trace(game,condition):
    before=[];prompts=[]
    def observe(step,messages,agent):
        before.append(snapshot(agent));prompts.append(deepcopy(messages))
    agent,escaped=(replay_solo if condition=='solo' else peer_replay)(game,observe)
    assert escaped
    names=list(agent.graph.scenes)
    route=[];cost=0
    for i,row in enumerate(agent.history):
        role=agent.step_roles[i];action=row['action_answer']
        assert not row['response'].startswith(('Error','Nothing happens')),(game,i,row)
        cost+=action!='yield()'
        after=before[i+1] if i+1<len(before) else snapshot(agent)
        # The legacy atlas bag field is the acting role's bag for Peer, shared bag for Solo.
        pre=dict(before[i],bag=before[i]['bags'][role]);post=dict(after,bag=after['bags'][role])
        route.append(dict(step=i+1,role=role,action=action,response=row['response'],
            before=pre,after=post,scene=names.index(pre['where'][role]),progress=row['tracking']['progress'],
            messages=prompts[i],environment_actions=cost,action_cost=int(action!='yield()')))
    return route
