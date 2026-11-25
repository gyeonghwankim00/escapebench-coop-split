"""Complete split-v4 easy dataset; dataset validation only, no model experiments.

build: materialize 12 games, roles, clues, reference paths, edit provenance.
verify: 11 eligible informed Solo/Peer witnesses, 1 explicit exclusion,
        observation-gated ablations, dead-branch probes and spatial exceptions.

Edits delete split-obsolete branches or move connections with their doors intact.
The missing upstream 2-3 easy shelf edge is restored explicitly. Object states,
clues and transition logic are not rewritten. Original vendor and v3 stay intact.
"""
from collections import deque
import contextlib
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

import yaml

import scripts.coop_original as co
import scripts.original_escape as oe
import scripts.split_metrics as sm

ROOT = oe.ROOT
UPSTREAM = ROOT / 'vendor/escapebench'
V4 = ROOT / 'data/split_v4'
VERSION = 'v4'

# Per game: deleted (scene, object) pairs and scenes, and connection moves. Reference steps that use a
# deleted object or stand in a deleted scene are dropped; expect_dropped guards against silent changes.
# rewire: move_items (object, from scene, to scene); unlink (scene, label); link (scene, label, target);
# relink (scene, old label, new label, new target); text (scene, old desc, new desc).
EDITS = {
    'game2-2-easy': dict(
        ref='2-2', expect_dropped=14,
        objects=[('entrace of a shop', 'cable'), ('reception room', 'pliers'),
                 ('administration office', 'flashlight'), ('administration office', 'air duct'),
                 ('administration office', 'golden key'), ('administration office', 'administration office door'),
                 ('administration office corner', 'draft'), ('administration office corner', 'desk safe'),
                 ('administration office corner', 'pencil'), ('administration office corner', 'waste paper'),
                 ('administration office corner', 'mirror')],
        scenes=[],
        why='B starts inside the inner office, the room the golden key opens, and A owns nothing behind '
            'that door. The whole chain (cable, pliers, flashlight, GB24 desk safe and mirror, air duct, '
            'golden key, door) only served to open it.'),
    'game1-2-easy': dict(
        ref='1-2', expect_dropped=4,
        objects=[('large cabinet close-up', 'large cabinet door'), ('large cabinet close-up', 'key for room 805'),
                 ('room 805 door view', 'room 805 door')],
        scenes=['large cabinet close-up', 'room 805 door view'],
        rewire=dict(
            unlink=[('hallway right', 'To the ventilation fan close-up')],
            link=[('room 805', 'To the ventilation fan close-up', 'ventilation fan close-up')],
            relink=[('ventilation fan close-up', 'Back to the hallway right', 'Back to room 805', 'room 805')],
            text=[('ventilation fan close-up', 'A closer look at the ventilation fan at the end of the hallway.',
                   'A closer look at the ventilation fan high on the wall of room 805.'),
                  ('room 805', 'You are inside room 805. There is a desk, a left bookshelf, a right bookshelf, a bed, '
                               'and a bedside table.',
                   'You are inside room 805. There is a desk, a left bookshelf, a right bookshelf, a bed, '
                   'and a bedside table. A ventilation fan is mounted high on the wall.'),
                  ('hallway right', 'A hallway with doors leading to Room 805, a small locked cabinet on the left, '
                                    'and a large open cabinet on the right. There\'s also a door leading to another '
                                    'room at the end of the hallway.',
                   'A hallway with a small locked cabinet on the left. There\'s also a door leading to another '
                   'room at the end of the hallway.')]),
        why='B starts inside room 805 and A owns nothing behind its door. The two close-ups held only the '
            'key and the door; the cabinet close-up text ("can be opened easily") would describe a deleted '
            'door, so both scenes go. The hallway right text no longer mentions them: A cannot enter room 805 '
            'and the large cabinet has no close-up left. '
            'The ventilation fan that leads to the elevator room moves from the end of A\'s hallway into '
            'room 805, so B no longer walks through A\'s hallway to reach its elevator room.'),
    'game1-3-easy': dict(
        ref='1-3', expect_dropped=11,
        objects=[('left corner of the hallway', 'pipe'), ('left corner of the hallway', 'book'),
                 ('the hallway', 'brick wall'), ('the hallway', 'strange key'), ('the hallway', 'black door'),
                 ('the hallway', 'paper 1'), ('the elevator room', 'wooden groove'),
                 ('the elevator room', 'lockbox'), ('the elevator room', 'gold key')],
        scenes=['left corner of the hallway'],
        why='B starts inside the billiard room, which the gold key opens, and A owns nothing behind the '
            'black door. The chain and its 7428 clue (paper 1, book) only served to open it; the left '
            'corner close-up is empty afterwards.'),
    'game1-1-easy': dict(
        ref='1-1', expect_dropped=0, objects=[], scenes=[],
        rewire=dict(
            move_items=[('bathroom door', 'bedroom', 'dining room and kitchen')],
            unlink=[('bedroom', 'To the bathroom')],
            link=[('dining room and kitchen', 'To the bathroom', 'bathroom')],
            relink=[('bathroom', 'To the bedroom', 'To the dining room and kitchen', 'dining room and kitchen')],
            text=[('bedroom', 'There is a bed, a visible hammer handle, a toolbox, a cardboard box, and a door '
                              'leading to the bathroom.',
                   'There is a bed, a visible hammer handle, a toolbox, and a cardboard box.'),
                  ('dining room and kitchen', 'A kitchen with several interactable areas. the dining table, the '
                   'cabinet above the stove, the left and right cabinets, the sink, and the cabinet above the sink.',
                   'A kitchen with several interactable areas. the dining table, the cabinet above the stove, the '
                   'left and right cabinets, the sink, and the cabinet above the sink. A door on the side leads to '
                   'the bathroom.')]),
        why='In v3 B\'s kitchen and bathroom lay on opposite sides of A\'s living room and bedroom, so B '
            'walked through A\'s rooms four times. The bathroom (and its door, which still needs the handle '
            'from A\'s cardboard box) now opens off the kitchen.'),
    'game2-1-easy': dict(
        ref='2-1', expect_dropped=0, objects=[], scenes=[],
        rewire=dict(
            unlink=[('study room', 'Turn left')],
            link=[('apartment hallway', 'Go to the utility room', 'utility room')],
            relink=[('utility room', 'Turn right', 'Go back', 'apartment hallway')]),
        why='In v3 A\'s utility room and sanctum lay beyond B\'s corridor and study, so A walked through '
            'them three times. The utility room (with the sanctum behind it) now opens off A\'s apartment '
            'hallway. No text states where it was.'),
}

# Additional edits adopted after the complete twelve-game review.
EDITS['game1-5-easy'] = dict(ref='1-5', expect_dropped=0, objects=[],
    scenes=['room on the left'], why='Move the system control room to the dormitory side; retain all puzzles and electrical triggers.',
    rewire=dict(move_items=[('safety door 3', 'room on the left', 'the dormitory')],
                link=[('the dormitory', 'Go to the control room', 'the control room')],
                relink=[('the control room', 'Back to room on the left', 'Back to the dormitory', 'the dormitory')],
                text=[('the dormitory', 'An abandoned dormitory. The beds are covered with dust.',
                       'An abandoned dormitory. The beds are covered with dust. An electrically controlled safety door leads to the control room.')]))
EDITS['game2-3-easy'] = dict(ref='2-3', expect_dropped=0, objects=[], scenes=[],
    why='Restore the kitchen-to-shelf link present in upstream default/hard and required by the shared reference. Reassign living room and upper floor to B to remove transit through partner scenes.',
    rewire=dict(link=[('kitchen', 'To the shelf above food preparation area close-up', 'shelf above food preparation area close-up')]))

# Text that mentions a deleted object's name but refers to something else.
NAME_FALSE_POSITIVES = {
    ('game2-2-easy', 'cable'): 'electrical cable (store room) is a different tool',
    ('game1-3-easy', 'brick wall'): 'the wall behind the wooden door in the billiard room, not the hallway brick wall',
}

# B scenes and B start for every v4 game. A owns the rest.
SPLITS = {
    'game1-1-easy': dict(start='dining room and kitchen', B=[
        'bathroom', 'mirror close-up', 'ventilation fan close-up', 'dining room and kitchen', 'dining table close-up',
        'cabinet above stove close-up', 'left cabinet close-up', 'right cabinet close-up', 'cabinet above sink close-up',
        'sink close-up'],
        why='Same scenes as v3; the bathroom now opens off B\'s kitchen (game file edited).'),
    'game1-2-easy': dict(start='room 805', B=[
        'elevator room', 'elevator interior', 'room 805', 'desk close-up', 'left bookshelf close-up',
        'bedside table close-up', 'right bookshelf close-up', '805 right room', 'ventilation fan close-up'],
        why='v3 scenes plus the ventilation fan close-up, which now belongs to room 805 (game file edited).'),
    'game1-3-easy': dict(start='the billiard room', B=['the billiard room', 'front desk', 'pool table'],
        why='Same scenes as v3 (game file edited).'),
    'game2-1-easy': dict(start='corridor', B=['corridor', 'world map', 'study room', 'utility room 2', 'bathroom'],
        why='Same scenes as v3; A\'s utility room now opens off A\'s hallway (game file edited).'),
    'game2-2-easy': dict(start='inner office', B=[
        'inner office', 'right side of inner office', 'left side of inner office', 'store room'],
        why='Same scenes as v3 (game file edited).'),
}

COHORT = {
    'game1-1-easy': dict(tier='core', cooperation_type='양방향 정보·도구 연쇄'),
    'game1-2-easy': dict(tier='extended', cooperation_type='도구 조립·부분 정보 결합'),
    'game1-3-easy': dict(tier='negative_control', cooperation_type='협력이 거의 필요 없는 단일 최종 전달'),
    'game2-1-easy': dict(tier='core', cooperation_type='간단한 코드 전달·물건 교환'),
    'game2-2-easy': dict(tier='core', cooperation_type='분산 자료 결합·상호 도구 처리'),
}

# Titles used by the playroom artifact (unchanged from v3).
TITLES = {
    'game1-1-easy': ('가정집', '거실·침실·욕실·서재'),
    'game1-2-easy': ('병원 805호', '복도·엘리베이터·805호·수술실'),
    'game1-3-easy': ('당구장 층', '엘리베이터 홀·프런트·당구장'),
    'game2-1-easy': ('실종자의 아파트', '탐정 편지·현관·서재·다용도실·성소'),
    'game2-2-easy': ('가게 사무실', '접수실·관리 사무실·안쪽 사무실·창고'),
}
# Complete dataset package: unchanged source games remain byte-identical copies.
_BASE_POLICY = json.loads((ROOT/'data/cohort_policy_v1.json').read_text())['games']
for _path in sorted((ROOT/'data/roles').glob('*.json')):
    _game, _role = _path.stem, json.loads(_path.read_text())
    SPLITS.setdefault(_game, dict(start=_role['starts']['B'], B=_role['B'], why='Retain v3 scene ownership; audited in the complete v4 package.'))
    EDITS.setdefault(_game, dict(ref=_game.removeprefix('game').removesuffix('-easy'), expect_dropped=0,
                                objects=[], scenes=[], why='Unmodified upstream puzzle and map.'))
    _pol = _BASE_POLICY[_game]
    COHORT.setdefault(_game, dict(tier=_pol['tier'], cooperation_type=_pol['cooperation_type']))
    TITLES.setdefault(_game, (_game, _pol['cooperation_type']))
SPLITS['game1-5-easy']['B'] = SPLITS['game1-5-easy']['B'] + ['the control room', 'the emergency exit']
SPLITS['game1-5-easy']['why'] = 'Dormitory and control room form one B area; A keeps the power distribution and downstream rooms.'
_cabin = json.loads((ROOT/'data/roles/game2-3-easy.json').read_text())
SPLITS['game2-3-easy'] = dict(start='living room', B=[n for n in _cabin['A'] if n not in
    ['outside of the cabin house', 'stairs close-up', 'front door close-up', 'windows close-up from outside']],
    why='B owns the complete living-room/upper-floor cluster; A owns outside/workspace/attic/kitchen/storage. No split close-ups or partner transit.')
EXCLUDED = {'game1-4-easy': 'Upstream circular clue: 7049 is revealed only after the safe requiring 7049. No blind guessing permitted.'}
TRANSIT_EXCEPTIONS = {'game2-4-easy': 'A reaches the cabin through B after the original gates open. Retain the machine puzzle and cabin evidence loop; this is an access-zone task, not two disjoint rooms.'}

KEEP = ('total', 'alone_A', 'alone_B', 'together_no_give', 'with_give', 'b_share', 'handoffs',
        'components', 'clue_inputs_cross')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    return str(Path(path).relative_to(ROOT))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def read_reference(path):
    dec, txt, out, i = json.JSONDecoder(), Path(path).read_text(), [], 0
    while i < len(txt):
        if txt[i].isspace():
            i += 1
            continue
        obj, i = dec.raw_decode(txt, i)
        out.append(obj)
    return out


def args_of(action):
    inner = action.split('(', 1)[1].rsplit(')', 1)[0]
    return [a.strip() for a in inner.split(',')]


# ---------------------------------------------------------------- build
def links(scenes):
    return {s['name']: dict(s.get('scene_relations') or {}) for s in scenes}


def path_ok(graph, start, path):
    p = path.split(' -> ')
    return p[0] == start and all(b in graph.get(a, {}).values() for a, b in zip(p, p[1:]))


def shortest_path(graph, start, target):
    queue, seen = deque([[start]]), {start}
    while queue:
        p = queue.popleft()
        if p[-1] == target:
            return ' -> '.join(p)
        for nxt in graph.get(p[-1], {}).values():
            if nxt not in seen:
                seen.add(nxt)
                queue.append(p + [nxt])
    raise AssertionError(f'no path {start} -> {target}')


def rewire(game, scenes, spec):
    """Move connections; returns {moved object: new scene}. Every edit must find exactly its target."""
    by = {s['name']: s for s in scenes}
    moved = {}
    for obj, src, dst in spec.get('move_items', []):
        hits = [i for i, w in enumerate(by[src].get('items') or []) if w['item']['name'].strip() == obj]
        assert len(hits) == 1, (game, obj, src)
        by[dst].setdefault('items', []).append(by[src]['items'].pop(hits[0]))
        moved[obj] = dst
    for scene, label in spec.get('unlink', []):
        assert label in by[scene]['scene_relations'], (game, scene, label)
        del by[scene]['scene_relations'][label]
    for scene, label, target in spec.get('link', []):
        assert target in by and label not in (by[scene].get('scene_relations') or {}), (game, scene, label)
        by[scene].setdefault('scene_relations', {})[label] = target
    for scene, old, new, target in spec.get('relink', []):
        rel_ = by[scene]['scene_relations']
        assert old in rel_, (game, scene, old)
        by[scene]['scene_relations'] = {(new if k == old else k): (target if k == old else v) for k, v in rel_.items()}
    for scene, old, new in spec.get('text', []):
        assert by[scene]['desc'] == old, (game, scene, by[scene]['desc'])
        by[scene]['desc'] = new
    return moved


def edit_game(game, spec):
    scenes = yaml.safe_load((UPSTREAM/'data'/f'{game}.yaml').read_text())
    start = scenes[0]['name']
    up_graph = links(scenes)
    moved = rewire(game, scenes, spec.get('rewire', {}))  # before deletions: a door may leave a scene being deleted
    drop_obj = set(spec['objects'])
    drop_scenes = set(spec['scenes'])
    names = {n for _, n in drop_obj}
    removed = []
    for s in scenes:
        for kind, key in (('items', 'item'), ('tools', 'tool')):
            if s.get(kind) is None:
                continue
            keep = []
            for w in s[kind]:
                pair = (s['name'], w[key]['name'].strip())
                (removed if pair in drop_obj else keep).append(pair if pair in drop_obj else w)
            s[kind] = keep
        if s['name'] in drop_scenes:
            assert not any(s.get(k) for k in ('items', 'tools')), f'{game}: scene {s["name"]} still has content'
        if s.get('scene_relations'):
            s['scene_relations'] = {k: v for k, v in s['scene_relations'].items() if v not in drop_scenes}
    scenes = [s for s in scenes if s['name'] not in drop_scenes]
    assert set(removed) == drop_obj, f'{game}: not found {drop_obj - set(removed)}'

    # No remaining mechanic may point at a deleted object or scene.
    problems, mentions = [], []
    for s in scenes:
        for kind, key in (('items', 'item'), ('tools', 'tool')):
            for w in s.get(kind) or []:
                for st in w[key].get('states') or []:
                    for target in (st.get('apply_to') or []) + (st.get('wait_for') or []):
                        if str(target).strip() in names:
                            problems.append((s['name'], w[key]['name'], 'refers to', target))
                    for tr in st.get('transitions') or []:
                        for t in [str(x) for x in (tr.get('wait_for') or []) + (tr.get('trigger') or [])]:
                            parts = [p.strip() for p in t.split(',')]
                            if any(p in names or p in drop_scenes for p in parts[1:]):
                                problems.append((s['name'], w[key]['name'], 'transition', t))
    assert not problems, f'{game}: dangling references {problems}'

    def texts(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                yield from texts(v, where + [k])
        elif isinstance(x, list):
            for v in x:
                yield from texts(v, where)
        elif isinstance(x, str) and where and where[-1] in ('desc', 'neg_reward', 'reward', 'position'):
            yield x
    for t in texts(scenes, []):
        for n in names | drop_scenes:
            if re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])', t, re.I):
                if not re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])',
                                 re.sub(r'electrical cable', '', t, flags=re.I), re.I):
                    continue
                mentions.append(dict(name=n, text=t[:160], accepted=NAME_FALSE_POSITIVES.get((game, n))))
    unexplained = [m for m in mentions if not m['accepted']]
    assert not unexplained, f'{game}: remaining text mentions deleted objects {unexplained}'

    ref = read_reference(UPSTREAM/'data/reference'/f'key_log_{spec["ref"]}.txt')
    graph = links(scenes)
    keep, dropped, repositioned = [], [], []
    for i, r in enumerate(ref):
        scene = r['position'].split(' -> ')[-1]
        if scene in drop_scenes or any(a in names for a in args_of(r['action_answer'])):
            dropped.append(dict(index=i, position=r['position'], action=r['action_answer']))
            continue
        target = next((moved[a] for a in args_of(r['action_answer']) if a in moved), scene)
        if target != scene or (path_ok(up_graph, start, r['position']) and not path_ok(graph, start, r['position'])):
            new = dict(r, position=shortest_path(graph, start, target))
            repositioned.append(dict(index=i, action=r['action_answer'], old=r['position'], new=new['position']))
            r = new
        keep.append(r)
    assert len(dropped) == spec['expect_dropped'], f'{game}: dropped {len(dropped)} steps'
    return scenes, keep, dropped, mentions, repositioned


def build():
    write_json(V4/'verification.json', dict(version=VERSION, passed=False, status='Needs verification after build'))
    (V4/'games').mkdir(parents=True, exist_ok=True)
    (V4/'reference').mkdir(parents=True, exist_ok=True)
    edits = {}
    for game, spec in EDITS.items():
        scenes, ref, dropped, mentions, repositioned = edit_game(game, spec)
        gpath, rpath = V4/'games'/f'{game}.yaml', V4/'reference'/f'key_log_{spec["ref"]}.txt'
        gpath.write_text(yaml.safe_dump(scenes, allow_unicode=True, sort_keys=False, width=100000))
        if not (spec['objects'] or spec['scenes'] or spec.get('rewire')):
            shutil.copyfile(UPSTREAM/'data'/f'{game}.yaml', gpath)
        rpath.write_text('\n'.join(json.dumps(r, indent=4, ensure_ascii=False) for r in ref) + '\n')
        rw = spec.get('rewire', {})
        edits[game] = dict(why=spec['why'],
                           upstream_game_sha256=sha(UPSTREAM/'data'/f'{game}.yaml'),
                           upstream_reference_sha256=sha(UPSTREAM/'data/reference'/f'key_log_{spec["ref"]}.txt'),
                           deleted_objects=[dict(scene=s, object=o) for s, o in spec['objects']],
                           deleted_scenes=spec['scenes'], dropped_reference_steps=dropped,
                           moved_objects=[dict(object=o, from_scene=a, to_scene=b) for o, a, b in rw.get('move_items', [])],
                           removed_links=[dict(scene=s, label=l) for s, l in rw.get('unlink', [])],
                           added_links=[dict(scene=s, label=l, target=t) for s, l, t in rw.get('link', [])],
                           changed_links=[dict(scene=s, old_label=o, new_label=n, target=t) for s, o, n, t in rw.get('relink', [])],
                           changed_texts=[dict(scene=s, old=o, new=n) for s, o, n in rw.get('text', [])],
                           repositioned_reference_steps=repositioned,
                           reference_steps=dict(upstream=len(ref) + len(dropped), v4=len(ref)),
                           name_mentions_kept=mentions,
                           game_file=rel(gpath), reference_file=rel(rpath))
    write_json(V4/'edits.json', dict(
        version=VERSION, policy='Delete split-obsolete chains; move connections with door puzzles preserved; restore the explicitly documented missing 2-3 easy shelf edge. No object state/transition changes. Original mode always uses upstream.', games=edits))

    clues_v3 = json.loads((ROOT/'data/clues.json').read_text())['games']
    clues = {}
    for game in SPLITS:
        gone = {o for _, o in EDITS.get(game, {}).get('objects', [])}
        clues[game] = [c for c in clues_v3[game]
                       if c['target'] not in gone and not any(s['object'] in gone for s in c['sources'])]
    write_json(V4/'clues.json', dict(
        note='Evaluator-only. Complete v4 clue annotations; deleted-branch clues removed. Never show annotations or answers to players.', games=clues))

    for old in (V4/'roles').glob('*.json'):
        old.unlink()
    with overlay():
        for game, s in SPLITS.items():
            names = [x['name'] for x in sm.load(game)]
            assert set(s['B']) <= set(names) and names[0] not in s['B'], game
            with sm.Quiet():
                m = sm.metrics(game, set(s['B']), b_start=s['start'])
            assert m['b_start'] == s['start'], game
            e = EDITS.get(game)
            spec = dict(version=VERSION, game=game, eligible=game not in EXCLUDED,
                        spatial_exception=TRANSIT_EXCEPTIONS.get(game),
                        A=[n for n in names if n not in s['B']], B=[n for n in names if n in s['B']],
                        starts={'B': s['start']},
                        low_interdependence=(m['total'] - m['together_no_give']) < 0.15 * m['total'],
                        game_file=e and rel(V4/'games'/f'{game}.yaml'),
                        reference_file=e and rel(V4/'reference'/f'key_log_{e["ref"]}.txt'),
                        change=dict(split=s['why'], game_file=e and e['why']),
                        metrics={k: m[k] for k in KEEP}, cross_clues=m['cross_clues'],
                        reference_handoffs=m['reference_handoffs'],
                        method='scripts/split_v4.py; metrics from scripts.split_metrics on the v4 game file',
                        note='Evaluator-only. Clues, handoffs and metrics must never be shown to agents.')
            write_json(V4/'roles'/f'{game}.json', spec)
    write_cohort()
    print('built', ', '.join(SPLITS))


def write_cohort():
    games = {}
    for game, c in COHORT.items():
        r = json.loads((V4/'roles'/f'{game}.json').read_text())
        m = r['metrics']
        cross = '; '.join(f"{x['answer']}: {'/'.join(x['partner_sources'])} → {x['target']}({x['target_role']})"
                          for x in r['cross_clues']) or '없음'
        hand = '; '.join(f"{h['tool']} {h['found_by']}→{h['used_by']}" for h in r['reference_handoffs'])
        games[game] = dict(c, reason=f"교차 암호 {m['clue_inputs_cross']}개 ({cross}). 정답 경로 물건 건네기 {m['handoffs']}번 ({hand}). "
                                     f"건네기 필요 단계 {m['total'] - m['together_no_give']}/{m['total']}.",
                           reference_total=m['total'], alone=dict(A=m['alone_A'], B=m['alone_B']))
    write_json(V4/'cohort_policy.json', dict(version='cohort-policy-v4', basis='Complete easy dataset; explicit exclusions and spatial exceptions in verification.json', games=games))


# ---------------------------------------------------------------- overlay
@contextlib.contextmanager
def overlay(use_v4=True):
    """Point the engine at upstream data with the v4 game files laid over it, and the role/clue
    lookups at v4 for the changed games. use_v4=False gives the untouched upstream + v3."""
    saved = (oe.UPSTREAM, co.ROLES_DIR, sm._CLUES)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)/'escapebench'
        shutil.copytree(UPSTREAM/'data', root/'data')
        shutil.copy(UPSTREAM/'UPSTREAM.json', root/'UPSTREAM.json')
        roles = Path(tmp)/'roles'
        shutil.copytree(ROOT/'data/roles', roles)
        clues = json.loads((ROOT/'data/clues.json').read_text())['games']
        if use_v4:
            for f in (V4/'games').glob('*.yaml'):
                shutil.copy(f, root/'data'/f.name)
            for f in (V4/'reference').glob('*.txt'):
                shutil.copy(f, root/'data/reference'/f.name)
            for f in (V4/'roles').glob('*.json'):
                shutil.copy(f, roles/f.name)
            if (V4/'clues.json').exists():
                clues.update(json.loads((V4/'clues.json').read_text())['games'])
        oe.UPSTREAM, co.ROLES_DIR, sm._CLUES = root, roles, clues
        try:
            yield
        finally:
            oe.UPSTREAM, co.ROLES_DIR, sm._CLUES = saved


# ---------------------------------------------------------------- checks
def play(game, owner, starts, ref, skip, clues=None):
    """Reference replay with free give(); input needs its clue sources observed when clues is given."""
    w = sm.World(game, owner, starts)
    seen = set()
    from scripts.split_evidence import key, contains

    def remember(scene, obj, text):
        for c in clues or []:
            for source in c['sources']:
                if source['scene'] == scene and source['object'] == obj and contains(text, source):
                    seen.add(key(source))

    def observe():
        for role in 'AB':
            for sc in w.reachable(role) | {w.starts.get(role)} - {None}:
                if owner.get(sc) != role:
                    continue
                scene = w.graph.scenes[sc]
                remember(sc, '@' + sc, scene.desc)
                for kind, attr in [('items', 'item'), ('tools', 'tool')]:
                    for n, wrapper in getattr(scene, kind).items():
                        obj = wrapper[attr]
                        if obj.visible:
                            remember(sc, n, obj.current_desc())
            for name, obj in w.bags[role].tools.items():
                for c in clues or []:
                    for source in c['sources']:
                        if source['object'] == name:
                            remember(source['scene'], name, obj.current_desc())
    observe()
    for i, st in enumerate(ref):
        if i in skip:
            continue
        scene = st['position'].split(' -> ')[-1]
        role = owner[scene]
        w.give_all(set(w.bags['B' if role == 'A' else 'A'].tools), role)
        act = st['action_answer']
        if clues is not None and act.startswith('input('):
            ans, tgt = args_of(act)[0], args_of(act)[-1]
            need = [c for c in clues if c['target'] == tgt and str(c['answer']) == ans and c['target_scene'] == scene]
            if not need or any(key(s) not in seen for c in need for s in c['sources']):
                continue
        with contextlib.redirect_stdout(io.StringIO()):
            sm.gv.bag = w.bags[role]
            if not act.startswith('craft'):
                if scene not in w.reachable(role) and scene != w.starts.get(role):
                    continue
                w.graph.current_scene = scene
            w.graph.describe()
            out = w.graph.react(act)
        remember(w.graph.current_scene, args_of(act)[-1], out)
        observe()
        if 'game end' in out.lower():
            return True
    return False


def dead_steps(game, spec):
    """v4 reference steps the upstream unsplit game needs but the v4 split can skip."""
    state = lambda: (oe.UPSTREAM, co.ROLES_DIR, sm._CLUES)

    def use(s):
        oe.UPSTREAM, co.ROLES_DIR, sm._CLUES = s
    with overlay(use_v4=False):
        upstream = state()
        names_up = [s['name'] for s in sm.load(game)]
        up_ref = sm.reference(game)
        up_clues = sm.clue_annotations(game)
        with overlay():
            v4 = state()
            ref = sm.reference(game)
            clues = sm._CLUES[game]
            # map each v4 step to its upstream index (v4 keeps the upstream order; positions may differ)
            index, j = [], 0
            for r in ref:
                while up_ref[j]['action_answer'] != r['action_answer']:
                    j += 1
                index.append(j)
                j += 1
            owner = {n: r for r in 'AB' for n in spec[r]}
            out = {}
            for mode, cl in (('known_codes', None), ('observed_clues', clues)):
                dead = []
                for i, r in enumerate(ref):
                    use(upstream)
                    needed = not play(game, {n: 'A' for n in names_up}, {}, up_ref, {index[i]}, up_clues if cl is not None else None)
                    use(v4)
                    if needed and play(game, owner, spec['starts'], ref, {i}, cl):
                        dead.append(dict(index=i, role=owner[r['position'].split(' -> ')[-1]], action=r['action_answer']))
                out[mode] = dead
    return out


def remote_effects(game, owner):
    scenes = sm.load(game)
    adj = sm.neighbors(scenes)
    where = {}
    for s in scenes:
        for kind, key in (('items', 'item'), ('tools', 'tool')):
            for w in s.get(kind) or []:
                where.setdefault((key, w[key]['name'].strip()), []).append(s['name'])
    out = []
    for s in scenes:
        for kind, key in (('items', 'item'), ('tools', 'tool')):
            for w in s.get(kind) or []:
                for st in w[key].get('states') or []:
                    for tr in st.get('transitions') or []:
                        for t in tr.get('trigger') or []:
                            p = [x.strip() for x in str(t).split(',')]
                            if len(p) < 3 or p[1] not in ('scene', 'item', 'tool'):
                                continue
                            for ts in ([p[2]] if p[1] == 'scene' else where.get((p[1], p[2]), [])):
                                if owner.get(ts, owner[s['name']]) != owner[s['name']]:
                                    out.append(dict(actor=owner[s['name']], scene=s['name'], object=w[key]['name'],
                                                    when=[str(x) for x in tr.get('wait_for') or []], effect=', '.join(p),
                                                    partner_scene=ts, adjacent=ts in adj[s['name']]))
    return out


def snapshot(agent):
    return dict(where=dict(agent.where), bags={r: sorted(agent.bags[r].tools) for r in 'AB'})


def route_of(agent, before):
    route = []
    for i, row in enumerate(agent.history):
        role = agent.step_roles[i]
        route.append(dict(step=i + 1, role=role, at=before[i]['where'][role], action=row['action_answer'],
                          response=row['response'], progress=row['tracking']['progress']))
    return route


def solo_replay(game):
    return informed_replay(game, solo=True)


def move_toward(agent, role, target):
    if agent.where[role] == target:
        return None
    queue, seen = deque([(agent.where[role], [])]), {agent.where[role]}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return 'move(' + path[0] + ')'
        for label, dest in agent.role_relations(role, node).items():
            if dest not in seen and (agent.graph.scenes[dest].visible or dest == agent.role_starts.get(role)):
                seen.add(dest)
                queue.append((dest, path + [label]))
    raise AssertionError(f'No legal route for {role}: {agent.where[role]} -> {target}')


def informed_replay(game, solo=False):
    from scripts.adaptive_escape import AdaptivePeer, AdaptiveSolo
    from scripts.split_evidence import EvidenceLedger, key
    before = []
    clues = sm.clue_annotations(game)
    ledger = EvidenceLedger(clues)
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        agent = (AdaptiveSolo if solo else AdaptivePeer)(game, tmp, None, max_steps=1500)
        # Dataset witness: retain actual observations, independent of experimental memory limits.
        agent.memory_budgets = {k: 1_000_000 for k in agent.memory_budgets}
        plan = deque(enumerate(sm.reference(game)))

        def call(step, messages):
            before.append(snapshot(agent))
            active = None if solo else re.search(r'Active role: ([AB])\.', messages[-1]['content'])[1]
            ledger.observe(agent, messages, 'AB' if solo else [active], step)
            assert plan, (game, 'Reference exhausted before escape')
            index, ref = plan[0]
            target, action = ref['position'].split(' -> ')[-1], ref['action_answer']
            role = agent.owner[target]
            op, args = action.split('(', 1)[0], args_of(action)

            def emit(actor, command):
                if not solo and active != actor:
                    return dict(raw='Thought: Let the required role proceed.\nAction: yield()', messages=messages)
                role_line = f'Role: {actor}\n' if solo else ''
                return dict(raw='Thought: Execute the evidence-backed reference plan.\n' + role_line + 'Action: ' + command, messages=messages)

            if not solo:
                for tool in (args[:1] if op == 'apply' else args if op == 'craft' else []):
                    holder, name = agent.holder(tool)
                    if holder and holder != role:
                        return emit(holder, f'give({name})')
            for clue in ledger.matching(action, target):
                for source in clue['sources']:
                    owners = 'AB' if solo else [role]
                    if any(key(source) in ledger.known[r] for r in owners):
                        continue
                    # A consumed/transferred clue may already have been observed by either role.
                    holder, _ = agent.holder(source['object'])
                    source_role = next((r for r in 'AB' if key(source) in ledger.known[r]),
                                       holder or agent.owner[source['scene']])
                    if not solo and active != source_role:
                        return emit(source_role, 'yield()')
                    if key(source) not in ledger.known[source_role]:
                        move = move_toward(agent, source_role, source['scene'])
                        assert move, (game, 'Source reached but evidence unavailable', source)
                        return emit(source_role, move)
                    assert not solo and source_role != role
                    return emit(source_role, ledger.message(source_role, role, source, step))
            if not solo and active != role:
                return emit(role, 'yield()')
            move = move_toward(agent, role, target)
            if move:
                return emit(role, move)
            ledger.require(role, action, target, step, shared=solo)
            plan.popleft()
            return emit(role, action)

        agent.model_call = call
        iterator = agent.iterate('split-v4-informed', game)
        try:
            while True:
                next(iterator)
        except StopIteration as final:
            escaped = final.value[0]
    route = route_of(agent, before)
    acts = [r['action'] for r in route]
    stats = dict(escaped=escaped, decisions=len(route), environment_actions=agent.cost,
                 memory_policy='Full observable notebook for dataset proof; not experiment memory settings',
                 skipped_reference_actions=[], remaining_reference_actions=len(plan),
                 clue_sources_not_messaged=[], input_evidence=ledger.checks, transmissions=ledger.transmissions,
                 messages=sum(a.startswith('send(') for a in acts), gives=sum(a.startswith('give(') for a in acts),
                 invalid_actions=sum(r['response'].startswith(('Error', 'Nothing happens')) for r in route),
                 partner_area_moves=[(r['role'], r['at'], r['action']) for r in route if co.VIA in r['action']])
    return stats, route


def peer_replay(game):
    return informed_replay(game)


def original_length(game):
    """Unsplit known-answer replay on the upstream file (what the 'original' mode plays)."""
    names = [s['name'] for s in sm.load(game)]
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        agent = co.CoopAgent(game, tmp, None, max_steps=600, roles=dict(A=names, B=[]), coop=False)
        plan = deque(sm.reference(game))

        def call(step, messages):
            while plan:
                target = plan[0]['position'].split(' -> ')[-1]
                if agent.where['A'] == target:
                    return dict(raw='Thought: replay\nAction: ' + plan.popleft()['action_answer'], messages=messages)
                return dict(raw='Thought: replay\nAction: ' + move_toward(agent, 'A', target), messages=messages)
            raise AssertionError('reference exhausted')
        agent.model_call = call
        iterator = agent.iterate('split-v4-original', game)
        try:
            while True:
                next(iterator)
        except StopIteration as final:
            escaped = final.value[0]
    assert escaped, f'{game}: original replay did not escape'
    return len(agent.history)


def constraints(m):
    t = m['total']
    need = max(1, math.ceil(0.1 * t))
    return dict(completable=m['with_give'] >= m['_baseline'] and m['b_enters_at_start'],
                no_idle_role=min(m['alone_A'], m['alone_B']) >= need,
                interdependent=(t - m['together_no_give']) >= 0.15 * t,
                thresholds=dict(alone_min=need, give_min=math.ceil(0.15 * t)))


def verify():
    write_json(V4/'verification.json', dict(version=VERSION, passed=False, status='Verification in progress'))
    results, artifact = {}, []
    v3_roles = {g: json.loads((ROOT/'data/roles'/f'{g}.json').read_text()) for g in SPLITS}
    from scripts.analyze_suitability import closure as informed_closure
    for game in SPLITS:
        spec = json.loads((V4/'roles'/f'{game}.json').read_text())
        owner = {n: r for r in 'AB' for n in spec[r]}
        with overlay(), sm.Quiet():
            ablations = {mode: informed_closure(game, mode) for mode in ('full', 'no_messages', 'no_give', 'only_A', 'only_B')}
        if game in EXCLUDED:
            assert not ablations['full']['escape'], 'Reconsider exclusion: evidence path now succeeds'
            results[game] = dict(eligible=False, reason=EXCLUDED[game], evidence_closure=ablations)
            continue
        with overlay():
            names = [s['name'] for s in sm.load(game)]
            with sm.Quiet():
                m = sm.metrics(game, set(spec['B']), b_start=spec['starts']['B'])
                m['_baseline'] = sm.closure(game, {n: 'A' for n in names}, ['A'])[0]
            stored = all(m[k] == spec['metrics'][k] for k in KEEP) and m['cross_clues'] == spec['cross_clues'] \
                and m['reference_handoffs'] == spec['reference_handoffs']
            keys, tools = oe.count_gobal(str(oe.UPSTREAM/'data'/f'{game}.yaml'))
            solo, solo_route = solo_replay(game)
            peer, peer_route = peer_replay(game)
            effects = remote_effects(game, owner)
            ref = sm.reference(game)
            clues = sm._CLUES[game]
            scenes = sm.load(game)
        with overlay(use_v4=False):
            original = None if game == 'game2-3-easy' else original_length(game)
            unsplit_on_v4 = None
        expect_alone = None
        if game in EDITS:
            # Deletions remove the opener of the partner's room, so the file cannot be won alone; a file with
            # only moved links must stay a normal one-player game.
            expect_alone = not EDITS[game]['objects']
            with overlay():
                unsplit_on_v4 = play(game, {n: 'A' for n in names}, {}, ref, set())
        dead = dead_steps(game, spec)
        cons = constraints(m)
        results[game] = dict(
            eligible=True, spatial_exception=TRANSIT_EXCEPTIONS.get(game), evidence_closure=ablations,
            quality=dict(initial_independent_observed={r:ablations['only_'+r]['completed'] for r in 'AB'},
                         message_blocked_reference_steps=len(ref)-ablations['no_messages']['completed'],
                         tool_blocked_reference_steps=len(ref)-ablations['no_give']['completed']),
            change=spec['change'],
            files={k: dict(path=spec[k], sha256=sha(ROOT/spec[k])) for k in ('game_file', 'reference_file') if spec[k]},
            stored_roles_match_recompute=stored,
            metrics={k: m[k] for k in KEEP}, v3_metrics=v3_roles[game]['metrics'],
            constraints=cons,
            dead_steps=dead,
            solo_replay=solo, peer_replay=peer,
            remote_effects=effects,
            progress_denominator=dict(keys=keys, tools=tools),
            original_mode=dict(file='vendor/escapebench (upstream, unchanged)', replay_actions=original,
                               note='Upstream 2-3 easy has a missing shelf edge; full original navigation replay unavailable.' if original is None else None,
                               v4_file_winnable_alone=unsplit_on_v4, expected_winnable_alone=expect_alone))
        write_json(V4/'replays'/f'{game}.solo.json', solo_route)
        write_json(V4/'replays'/f'{game}.peer.json', peer_route)
        title, subtitle = TITLES[game]
        pol = json.loads((V4/'cohort_policy.json').read_text())['games'][game]
        artifact.append(dict(
            id=game, scenes=scenes, A=spec['A'], B=spec['B'], starts=spec['starts'], metrics=spec['metrics'],
            cross=spec['cross_clues'], handoffs=spec['reference_handoffs'], tier=pol['tier'],
            ctype=pol['cooperation_type'], reason=pol['reason'], totals=dict(keys=keys, tools=tools),
            reference=ref, clues=clues,
            refLen=dict(solo=solo['environment_actions'], peer=peer['environment_actions'], steps=len(ref),
                        original=original),
            original_scenes='upstream' if game in EDITS else 'same', title=title, subtitle=subtitle, split_version=VERSION))
        print(f"{game}: steps {len(ref)} solo {solo['escaped']}/{solo['environment_actions']} peer {peer['escaped']}/"
              f"{peer['environment_actions']} dead {[len(v) for v in dead.values()]} constraints "
              f"{[k for k, v in cons.items() if v is False] or 'ok'} crossings solo {len(solo['partner_area_moves'])} "
              f"peer {len(peer['partner_area_moves'])} stored={stored}", flush=True)
    eligible = {g:r for g,r in results.items() if r['eligible']}
    ok = all(r['solo_replay']['escaped'] and r['peer_replay']['escaped'] and not r['solo_replay']['invalid_actions']
             and not r['peer_replay']['invalid_actions'] and not r['solo_replay']['skipped_reference_actions']
             and r['stored_roles_match_recompute'] and not r['dead_steps']['observed_clues']
             and r['evidence_closure']['full']['escape']
             and not r['peer_replay']['skipped_reference_actions']
             and not r['peer_replay']['clue_sources_not_messaged']
             and not r['solo_replay']['remaining_reference_actions']
             and not r['peer_replay']['remaining_reference_actions']
             and (g in TRANSIT_EXCEPTIONS or (not r['solo_replay']['partner_area_moves'] and not r['peer_replay']['partner_area_moves']))
             and r['original_mode']['v4_file_winnable_alone'] == r['original_mode']['expected_winnable_alone']
             for g, r in eligible.items())
    write_json(V4/'verification.json', dict(
        version=VERSION, passed=ok, eligible_games=list(eligible), excluded=EXCLUDED, spatial_exceptions=TRANSIT_EXCEPTIONS,
        scope='Informed known-answer witnesses with complete observable memory, not model performance or shortest-path proofs. Evidence required before every input. Ten eligible games have no partner transit; 2-4 is an explicit exception. Dead-step probes are reference-relative, not exhaustive.',
        dataset_sha256={rel(p): sha(p) for folder in ('games','reference','roles') for p in sorted((V4/folder).iterdir()) if p.is_file()} |
                       {rel(V4/name):sha(V4/name) for name in ('clues.json','cohort_policy.json','edits.json')},
        code_sha256={p: sha(ROOT/p) for p in ('scripts/split_v4.py', 'scripts/split_metrics.py',
                                              'scripts/coop_original.py', 'scripts/adaptive_escape.py',
                                              'scripts/check_protocol.py', 'scripts/split_evidence.py', 'scripts/analyze_suitability.py')},
        games=results))
    write_json(V4/'artifact_games.json', artifact)
    print('verification', 'PASS' if ok else 'FAIL')
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    {'build': build, 'verify': verify}[sys.argv[1]]()
