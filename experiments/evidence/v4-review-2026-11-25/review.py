"""Read-only v4 audit. Run from repository root; writes only this audit's JSON.

Known-answer execution and annotated evidence visibility are separate checks.
The evidence check is a substring screen, not proof of reasoning or minimality.
"""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts import split_v4 as v4
from scripts import analyze_suitability as suitability
from scripts.adaptive_escape import AdaptivePeer


def provenance():
    paths = [ROOT/'scripts/split_v4.py', ROOT/'scripts/analyze_suitability.py',
             ROOT/'scripts/split_metrics.py', ROOT/'data/clues.json', Path(__file__).resolve()]
    paths += list((ROOT/'data/roles').glob('*.json'))
    paths += [p for p in (ROOT/'data/split_v4').rglob('*') if p.is_file()]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def check_object_preservation():
    import yaml
    result = {}
    for game, spec in v4.EDITS.items():
        def objects(path):
            return {(s['name'], kind, w[key]['name'].strip()): w[key]
                    for s in yaml.safe_load(path.read_text())
                    for kind, key in [('items', 'item'), ('tools', 'tool')]
                    for w in s.get(kind) or []}
        old = objects(v4.UPSTREAM/'data'/f'{game}.yaml')
        new = objects(v4.V4/'games'/f'{game}.yaml')
        removed = set(spec['objects'])
        moved = {(src, name): dst for name, src, dst in spec.get('rewire', {}).get('move_items', [])}
        expected = {(moved.get((scene, name), scene), kind, name): obj
                    for (scene, kind, name), obj in old.items() if (scene, name) not in removed}
        result[game] = dict(remaining_objects_unchanged=expected == new,
                            original_objects=len(old), remaining_objects=len(new))
        assert expected == new, game
    return result


def norm(text):
    return ' '.join(str(text).lower().split())


def evidence_replay(game, repair_feedback=False):
    original_iterate = AdaptivePeer.iterate
    seen = {'A': '', 'B': ''}
    checks, replacements = [], []

    def iterate(agent, *args, **kwargs):
        original_call = agent.model_call

        def call(step, messages):
            import re
            role = re.search(r'Active role: ([AB])\.', messages[-1]['content'])[1]
            content = norm('\n'.join(m['content'] for m in messages))
            seen[role] += '\n' + content
            result = original_call(step, messages)
            action = result['raw'].split('Action: ', 1)[-1]
            if repair_feedback and action == 'send(drawer: an opened drawer)':
                discovery = next(d for d in agent.discoveries[role]
                                 if d['action'] == 'apply(entrance guard card, drawer)')
                # Use only the actual successful feedback already visible to B.
                text = next(str(value) for value in discovery.values() if '1040' in str(value))
                assert norm(text) in content
                replacement = 'send(' + text + ')'
                assert len(text) <= 300
                result = dict(result, raw='Thought: Share the observed drawer result.\nAction: ' + replacement)
                replacements.append(dict(decision=step, role=role, before=action, after=replacement))
            if action.startswith('input('):
                ans, target = v4.args_of(action)
                for clue in v4.sm.clue_annotations(game):
                    if str(clue['answer']) != ans or clue['target'] != target:
                        continue
                    missing_ever = [dict(object=s['object'], evidence=e) for s in clue['sources']
                                    for e in s['evidence'] if norm(e) not in seen[role]]
                    missing_current = [dict(object=s['object'], evidence=e) for s in clue['sources']
                                       for e in s['evidence'] if norm(e) not in content]
                    checks.append(dict(decision=step, role=role, action=action,
                                       missing_ever=missing_ever, missing_current=missing_current))
            return result

        agent.model_call = call
        return (yield from original_iterate(agent, *args, **kwargs))

    with patch.object(AdaptivePeer, 'iterate', iterate):
        stats, route = v4.peer_replay(game)
    return dict(stats=stats, checks=checks, replacements=replacements)


def main():
    generated = {}
    def collect(path, value):
        generated[str(path.relative_to(ROOT))] = value
    with patch.object(v4, 'write_json', collect):
        v4.verify()
    result = dict(provenance=provenance(), object_preservation=check_object_preservation(),
                  verification=generated['data/split_v4/verification.json'],
                  evidence={}, suitability={})
    with v4.overlay():
        for game in v4.SPLITS:
            result['evidence'][game] = evidence_replay(game)
            print('Evidence checked:', game, flush=True)
        result['feedback_repair_probe'] = evidence_replay('game2-2-easy', True)
        for game in sorted(p.stem for p in (ROOT/'data/roles').glob('*.json')):
            modes = {}
            with contextlib.redirect_stdout(io.StringIO()):
                for mode in ('full', 'no_messages', 'no_give', 'only_A', 'only_B'):
                    r = suitability.closure(game, mode)
                    modes[mode] = {k:v for k,v in r.items() if k != 'trace'}
            result['suitability'][game] = modes
            print('Ablations checked:', game, flush=True)
    output = Path(__file__).with_name('review.json')
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(output)


if __name__ == '__main__':
    main()
