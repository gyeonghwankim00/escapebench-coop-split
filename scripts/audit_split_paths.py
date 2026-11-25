"""Evaluator-only optimistic bypass audit: known answers, free reachable travel.
A witness here flags a structural risk, not an executable costed trajectory.
No witness is NOT proof that no bypass exists. Never change source puzzles.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
from scripts.split_metrics import World, reference, needed_tools
from scripts.coop_original import load_roles
from scripts.run_matrix import ALL_GAMES


def probe(game, omitted_role=None):
    spec=load_roles(game);owner={n:r for r in 'AB' for n in spec[r]}
    world=World(game,owner,spec.get('starts'));ref=reference(game)
    final=[]  # engine feedback below determines escape
    # Engine feedback, not a guessed final reference index, determines escape.
    escaped=[False];react=world.graph.react
    def capture(action):
        result=react(action)
        if 'game end' in result.lower():escaped[0]=True
        return result
    world.graph.react=capture
    done=set();changed=True
    while changed and not escaped[0]:
        changed=False
        for index,step in enumerate(ref):
            if index in done:continue
            role=owner[step['position'].split(' -> ')[-1]]
            # Permit only the exit action for the omitted role, testing whether
            # that role's puzzle chain became unnecessary after split starts.
            if role==omitted_role and index!=len(ref)-1:continue
            world.give_all(needed_tools(step),role)
            if world.try_step(role,step):done.add(index);changed=True
            if escaped[0]:break
    return dict(omitted_puzzle_role=omitted_role,escape=escaped[0],
                reference_steps_completed=len(done),reference_steps_total=len(ref))


def audit():
    result=[]
    with contextlib.redirect_stdout(io.StringIO()):
        for game in ALL_GAMES:
            checks=[probe(game,r) for r in (None,'A','B')]
            risky=any(c['escape'] for c in checks[1:])
            result.append(dict(game=game,checks=checks,
                cohort='control_or_review' if risky or load_roles(game)['low_interdependence'] else 'main_candidate',
                bypass_risk=risky,known_code_assumption=True,validation='optimistic structural audit; full costed witness still required'))
    return dict(protocol='escapebench-adaptive-v6',games=result,
                warning='Known codes can bypass information dependencies even in the original game. Flags require clue review and a costed witness; absence of bypass is not proof. Flagged games are excluded from primary comparisons pending review.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result=audit();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    for g in result['games']:print(g['game'],g['cohort'],'bypass='+str(g['bypass_risk']))

if __name__=='__main__':main()
