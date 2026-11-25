"""Offline, evaluator-only evidence trails. No model calls or prompt changes.

Usage: python -m scripts.analyze_collaboration outputs/matrix/<run>
Uses the saved role snapshot, never silently applies a new split to old logs.
Information labels are REVIEW CANDIDATES: literal matching cannot establish
message correctness, model understanding, or unsatisfied puzzle prerequisites.
"""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def norm(text):
    return ' '.join(str(text).replace('\\n', '\n').casefold().split())


def contains(text, value):
    value = norm(value)
    return bool(value) and re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', norm(text)) is not None


def action(text):
    match = re.fullmatch(r'(\w+)\((.*)\)', text.strip(), re.S)
    return (match[1].lower(), match[2].strip()) if match else ('', '')


def same_action(left, right):
    lop, larg = action(left)
    rop, rarg = action(right)
    if lop != rop or not lop:
        return False
    # The engine accepts optional whitespace and either order of craft tools.
    la, ra = [norm(x) for x in larg.split(',')], [norm(x) for x in rarg.split(',')]
    return sorted(la) == sorted(ra) if lop == 'craft' else la == ra


def is_help(row):
    return bool(row.get('helper_active') or row.get('forced_action')
                or row.get('first_hint_progress') is not None)


def analyze(game, rows, spec=None, annotations=None):
    spec = spec or json.loads((ROOT/'data/roles'/f'{game}.json').read_text())
    annotations = annotations if annotations is not None else json.loads((ROOT/'data/clues.json').read_text())['games'][game]
    owner = {s: r for r in 'AB' for s in spec[r]}
    shared_inventory = bool(rows) and all(r.get('inventory_mode') == 'shared' for r in rows)
    boundary = next((i for i, r in enumerate(rows) if is_help(r)), len(rows))
    contexts, events, prior_feedback = [], [], {'A': deque(maxlen=10), 'B': deque(maxlen=10)}
    for step, row in enumerate(rows):
        role, up = row['role'], row['upstream']
        partner = 'B' if role == 'A' else 'A'
        generation = row.get('generation')
        user = '\n'.join(m['content'] for m in (generation or {}).get('messages', []) if m['role'] == 'user')
        scene = row.get('evaluation', {}).get('scene', up.get('position', '').split(' -> ')[-1])
        observation = up.get('scene', '') + '\n' + up.get('possible_actions', '')
        # Only evidence genuinely supplied in an actual call; forced turns have no observation exposure.
        env_text = observation if generation and norm(observation) in norm(user) else ''
        feedback = [text for text in prior_feedback[role] if text and text in user]
        contexts.append(dict(step=step, role=role, scene=scene, text=env_text,
                             feedback=feedback, row=row))
        op, arg = action(up.get('action_answer', ''))
        success = up.get('response', '').startswith('Action executed successfully')
        phase = 'before_first_hint' if step < boundary else 'after_first_hint'
        base = dict(step=step, role=role, phase=phase)
        if op in ('send', 'give'):
            payload = arg.strip('"\'` ').strip()[:300] if op == 'send' else arg
            events.append(dict(base, kind=op, to=partner, payload=payload, success=success))
        if user:
            for message in row.get('inbox', []):
                if message in user:
                    events.append(dict(base, kind='received_update', payload=message, success=True))
        before = row.get('evaluation', {}).get('bags_before', {}).get(role)
        if before is not None:
            for tool in sorted(set(row.get('bags', {}).get(role, [])) - set(before)):
                events.append(dict(base, kind='acquired_tool', payload=tool, success=success))
        prior_feedback[role].append(up.get('response', ''))

    def window(limit):
        ctx, ev = contexts[:limit], [e for e in events if e['step'] < limit]
        role_stats = {r: dict(steps=0, progress_gain_percentage_points=0.0, errors=0,
                             messages=0, gives=0, repeated_messages=0) for r in 'AB'}
        previous_progress = 0
        for c in ctx:
            up, stats = c['row']['upstream'], role_stats[c['role']]
            progress = up.get('tracking', {}).get('progress', previous_progress)
            stats['steps'] += 1
            stats['progress_gain_percentage_points'] += max(0, progress - previous_progress)
            stats['errors'] += up.get('response', '').startswith('Error') or up.get('action_answer') == 'No action'
            previous_progress = progress
        for role, stats in role_stats.items():
            sent = [e for e in ev if e['role'] == role and e['kind'] == 'send' and e['success']]
            stats['messages'] = len(sent)
            stats['gives'] = sum(e['role'] == role and e['kind'] == 'give' and e['success'] for e in ev)
            stats['repeated_messages'] = len(sent) - len({norm(e['payload']) for e in sent})
            stats['progress_gain_percentage_points'] = round(stats['progress_gain_percentage_points'], 2)
        clues = []
        for index, clue in enumerate(annotations):
            target_role = owner[clue['target_scene']]
            sources = [s for s in clue['sources'] if owner[s['scene']] != target_role]
            if not sources:
                continue
            observations = []
            for source in sources:
                hits, reachable = [], []
                for c in ctx:
                    if c['role'] != owner[source['scene']]:
                        continue
                    reach = c['row'].get('evaluation', {}).get('reachable_scenes')
                    if reach is not None:
                        reachable.append(source['scene'] in reach[c['role']])
                    # Scope current evidence to source scene or the named tool in the bag.
                    in_scope = c['scene'] == source['scene'] or contains(c['text'].split('Tools in Bag:')[-1], source['object'])
                    shown = in_scope and all(contains(c['text'], x) for x in source['evidence'])
                    feedback_shown = any(contains(f, source['object']) and
                        all(contains(f, x) for x in source['evidence']) for f in c['feedback'])
                    if shown or feedback_shown:
                        hits.append(c['step'])
                observations.append(dict(source=source, holder=owner[source['scene']],
                    observed_steps=hits, ever_scene_reachable=any(reachable) if reachable else None))
            delivered = [e for e in ev if e['kind'] == 'received_update' and e['role'] == target_role]
            candidates = [e['step'] for e in delivered if
                contains(e['payload'], clue['answer']) or
                any(all(contains(e['payload'], x) for x in s['evidence']) for s in sources)]
            carried = []
            for source in sources:
                transfers = [e for e in ev if e['kind'] == 'give' and e['success'] and e['to'] == target_role
                             and norm(e['payload']) == norm(source['object'])]
                for c in ctx:
                    if c['role'] != target_role or not any(e['step'] < c['step'] for e in transfers):
                        continue
                    bag_text = c['text'].split('Tools in Bag:')[-1]
                    if contains(bag_text, source['object']) and all(contains(bag_text, x) for x in source['evidence']):
                        carried.append(c['step'])
            uses = []
            for c in ctx:
                up = c['row']['upstream']
                op, arg = action(up.get('action_answer', ''))
                if c['role'] == target_role and c['scene'] == clue['target_scene'] and op == 'input':
                    if same_action(up['action_answer'], f'input({clue["answer"]}, {clue["target"]})'):
                        uses.append(dict(step=c['step'], success=up.get('response', '').startswith('Action executed successfully')))
            solved = any(u['success'] for u in uses)
            all_seen = all(o['observed_steps'] for o in observations)
            unreachable = any(o['ever_scene_reachable'] is False and not o['observed_steps'] for o in observations)
            stage = ('resolved' if solved else 'not_yet_reachable' if unreachable else
                     'non_discovery_candidate' if not all_seen else
                     'non_transmission_candidate' if not (candidates or carried) else 'non_uptake_candidate')
            if shared_inventory and not solved:
                stage = 'unresolved_central_control'  # no communication obligation
            clues.append(dict(id=f'code-{index}', target=clue['target'], target_role=target_role,
                answer=clue['answer'], observations=observations,
                literal_received_candidate_steps=candidates, object_carried_candidate_steps=sorted(set(carried)),
                uses=uses, stage_candidate=stage,
                needs_review=not solved, prerequisites_verified=False))

        objects = []
        for index, link in enumerate(spec.get('reference_handoffs', [])):
            op, arg = action(link['action'])
            tools = [x.strip() for x in arg.split(',')] if op == 'craft' else [link['tool']]
            holdings = {tool: [] for tool in tools}
            for c in ctx:
                for tool in tools:
                    bags = ({'shared': c['row']['shared_bag']} if shared_inventory
                            else c['row'].get('bags', {}))
                    for r, bag in bags.items():
                        if tool in bag:
                            holdings[tool].append(dict(step=c['step'], role=r))
            transfers = [e for e in ev if e['kind'] == 'give' and e['success'] and
                         any(norm(e['payload']) == norm(t) for t in tools)]
            correct_transfers = [e for e in transfers if link['used_by'] == 'either' or e['to'] == link['used_by']]
            uses = [dict(step=c['step'], role=c['role']) for c in ctx if
                    same_action(c['row']['upstream'].get('action_answer', ''), link['action']) and
                    c['row']['upstream'].get('response', '').startswith('Action executed successfully') and
                    (link['used_by'] == 'either' or c['role'] == link['used_by'])]
            collected = all(holdings.values())
            stage = ('resolved' if uses else 'non_collection_candidate' if not collected else
                     'non_transfer_candidate' if not correct_transfers else 'non_use_candidate')
            if shared_inventory and not uses:
                stage = 'unresolved_central_control'
            objects.append(dict(id=f'object-{index}', **link, holdings=holdings, transfers=correct_transfers,
                                uses=uses, stage_candidate=stage, needs_review=not bool(uses),
                                prerequisites_verified=False))
        return dict(steps=limit, roles=role_stats, clues=clues, objects=objects,
                    stage_counts=dict(Counter(x['stage_candidate'] for x in clues + objects)),
                    messages=sum(e['kind'] == 'send' and e['success'] for e in ev),
                    gives=sum(e['kind'] == 'give' and e['success'] for e in ev))

    return dict(version=1, game=game, roles_version=spec.get('version'),
        communication_stages_applicable=not shared_inventory,
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        low_interdependence=spec.get('low_interdependence', False),
        first_help_row=boundary if boundary < len(rows) else None,
        notes=['Steps are zero-based rows in turns.jsonl.',
               'Shared-inventory Solo has no transmission/transfer obligation. Its unresolved links are not collaboration failure stages; role-local exposure fields are not a full central observation audit.',
               'before_first_hint is the only autonomous prefix; later non-helper turns remain help-exposed.',
               'Candidate labels require human review. Literal messages can be negated, incomplete, or unrelated.',
               'Source reachability is scene travel only, not puzzle prerequisites. Missing telemetry means unknown.',
               'Object holdings/transfers/use are observed facts; failure causes and craft ordering require review.',
               'Objects can carry clues; inspect received updates and subsequent bag descriptions before labeling.',
               'Resolved means the target action succeeded, not that a preceding message caused it.',
               'Cross-clue links are nested within games, not independent statistical samples.'],
        before_first_hint=window(boundary), full_episode=window(len(rows)), events=events)


def write_analysis(directory, result):
    directory = Path(directory)
    (directory/'collaboration.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    lines = ['# Collaboration evidence (evaluator only)', '',
             'Provisional labels, not final failure-stage ground truth. Steps are zero-based.', '']
    for name in ('before_first_hint', 'full_episode'):
        w = result[name]
        lines += [f'## {name}', '', f'{w["steps"]} steps; {w["messages"]} messages; {w["gives"]} successful gives.', '',
                  '| Role | Steps | Progress gain (pp) | Errors | Repeated messages |',
                  '|---|---:|---:|---:|---:|']
        for role, stats in w['roles'].items():
            lines.append(f'| {role} | {stats["steps"]} | {stats["progress_gain_percentage_points"]} | '
                         f'{stats["errors"]} | {stats["repeated_messages"]} |')
        lines += ['',
                  '| Link | Target/action | Candidate | Review |', '|---|---|---|---|']
        for link in w['clues'] + w['objects']:
            label = link.get('target', link.get('action', '')).replace('|', '\\|')
            lines.append(f'| {link["id"]} | {label} | {link["stage_candidate"]} | {link["needs_review"]} |')
        lines.append('')
    lines.extend(result['notes'])
    (directory/'collaboration.md').write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run/'experiment.json').read_text())
    for game in manifest['games']:
        path = args.run/'coop'/game/'turns.jsonl'
        if not path.exists():
            continue
        spec_path = args.run/'evaluation_inputs'/'roles'/f'{game}.json'
        clues_path = args.run/'evaluation_inputs'/'clues.json'
        if not spec_path.exists() or not clues_path.exists():
            raise SystemExit('Missing frozen evaluation inputs. Refusing to analyze old logs with current roles.')
        raw = spec_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest['role_hashes'][game]:
            raise SystemExit(f'Role snapshot changed: {game}')
        if hashlib.sha256(clues_path.read_bytes()).hexdigest() != manifest['evaluation_hashes']['data/clues.json']:
            raise SystemExit('Clue snapshot changed')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        result = analyze(game, rows, json.loads(raw), json.loads(clues_path.read_text())['games'][game])
        write_analysis(path.parent, result)
        print(path.parent/'collaboration.md')


if __name__ == '__main__':
    main()
