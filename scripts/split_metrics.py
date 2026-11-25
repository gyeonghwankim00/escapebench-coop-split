"""Measure how a scene split shapes cooperation, using the original engine.

For a split (scene -> A/B) of an upstream game, replay the upstream reference
key steps under the 2-agent rules and report:

  alone_A / alone_B  reference steps a role completes with NO partner action at
                     all (partner never moves, never gives, never unlocks).
                     0 means that role is idle until the partner helps.
  together_no_give   steps both complete acting independently, each with its
                     own bag, without any give(). total - this = steps that
                     require at least one object handoff.
  b_share            share of reference steps located in B's scenes.
  handoffs           reference applies/crafts whose tool is first found by the
                     other role (object transfers on the reference path; a tool
                     crafted from parts counts by where the named tool lies).
                     reference_handoffs lists them.
  components         connected pieces of each role's scenes in the scene graph.
  b_enters_at_start  B has a reachable scene at t=0.
  clue_inputs_cross  code inputs for which at least one clue source lies in the
                     other role's scenes (data/clues.json, hand-annotated for
                     all 54 inputs). cross_clues lists them.

Greedy closure uses reference steps as the action vocabulary (input codes count
as known), so alone_* is an upper bound for an agent that knows every answer.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import yaml

import scripts.original_escape as oe

gv = oe.gv


def reference(game):
    gid = game.replace('-easy', '').replace('-hard', '').replace('game', '')
    return oe.read_jsonl_multiline(str(oe.UPSTREAM/'data/reference'/f'key_log_{gid}.txt'))


def load(game):
    return yaml.safe_load((oe.UPSTREAM/'data'/f'{game}.yaml').read_text())


def neighbors(scenes):
    adj = {s['name']: set() for s in scenes}
    for s in scenes:
        for t in (s.get('scene_relations') or {}).values():
            adj[s['name']].add(t)
            adj[t].add(s['name'])
    return adj


def components(names, adj):
    left, count = set(names), 0
    while left:
        count += 1
        stack = [left.pop()]
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v in left:
                    left.remove(v)
                    stack.append(v)
    return count


class World:
    """Original Graph plus per-role bags; no LLM."""

    def __init__(self, game, owner, starts=None):
        self.graph = oe.Graph(str(oe.UPSTREAM/'data'/f'{game}.yaml'), use_index=False)
        gv.reset_global_vars()
        self.owner = owner
        self.bags = {'A': gv.bag, 'B': gv.Bag()}
        self.start = next(iter(self.graph.scenes))
        self.starts = dict(starts or {})
        self.relations = {n: dict(s.scene_relations) for n, s in self.graph.scenes.items()}

    def reachable(self, role):
        """Own scenes reachable from the role's start through visible scenes (any
        owner in between). Same rule as CoopAgent.role_relations/entry_scene."""
        origin = self.starts.get(role, self.start)
        seen, queue, own = {origin}, [origin], set()
        while queue:
            u = queue.pop(0)
            if self.owner[u] == role:
                own.add(u)
            for v in self.relations[u].values():
                if v not in seen and self.graph.scenes[v].visible:
                    seen.add(v)
                    queue.append(v)
        return own

    def progress(self):
        return gv.count.key_steps + gv.count.tool_collected

    def try_step(self, role, step):
        action = step['action_answer']
        op = action.split('(')[0].strip()
        scene = step['position'].split(' -> ')[-1]
        if op == 'move':
            return False
        if op != 'craft' and (self.owner[scene] != role or scene not in self.reachable(role)):
            return False
        gv.bag = self.bags[role]
        self.graph.current_scene = scene if op != 'craft' else self.graph.current_scene
        before = self.progress()
        self.graph.describe()
        self.graph.react(action)
        return self.progress() > before

    def give_all(self, tool_names, to):
        src = 'B' if to == 'A' else 'A'
        for name in list(self.bags[src].tools):
            if name in tool_names:
                self.bags[to].add_tool(self.bags[src].tools.pop(name))


def closure(game, owner, roles, allow_give=False, starts=None):
    world = World(game, owner, starts)
    ref = reference(game)
    done, changed = set(), True
    while changed:
        changed = False
        for k, step in enumerate(ref):
            if k in done:
                continue
            for role in roles:
                if allow_give:
                    world.give_all(needed_tools(step), role)
                if world.try_step(role, step):
                    done.add(k)
                    changed = True
                    break
    return len(done), len(ref)


_CLUES = None


def clue_annotations(game):
    global _CLUES
    if _CLUES is None:
        _CLUES = json.loads((oe.ROOT/'data/clues.json').read_text())['games']
    return _CLUES[game]


def needed_tools(step):
    action = step['action_answer']
    op = action.split('(')[0].strip()
    args = [a.strip() for a in action.split('(')[1].split(')')[0].split(',')]
    return set(args[:1]) if op == 'apply' else (set(args) if op == 'craft' else set())


def text_blob(scene):
    parts = [scene.get('desc', '')]
    for kind in ('items', 'tools'):
        for w in scene.get(kind) or []:
            obj = w['item' if kind == 'items' else 'tool']
            for st in obj['states']:
                parts.append(st.get('desc', ''))
                for t in st.get('transitions', []) or []:
                    parts.append(t.get('reward', ''))
    return ' '.join(parts)


def nearest_scene(game, b_scenes):
    """B's default start: its scene closest to the original start (graph distance,
    ignoring locks), i.e. the room right behind the first door."""
    scenes = load(game)
    adj = neighbors(scenes)
    start = scenes[0]['name']
    order, seen = [start], {start}
    for u in order:
        for v in sorted(adj[u], key=[s['name'] for s in scenes].index):
            if v not in seen:
                seen.add(v)
                order.append(v)
    return next(n for n in order if n in b_scenes)


def metrics(game, b_scenes, b_start='nearest'):
    """b_start: 'nearest' (two-room start), None (enter when reachable, v1 rule) or a scene."""
    scenes = load(game)
    names = [s['name'] for s in scenes]
    owner = {n: ('B' if n in b_scenes else 'A') for n in names}
    adj = neighbors(scenes)
    if b_start == 'nearest':
        b_start = nearest_scene(game, b_scenes)
    starts = {'B': b_start} if b_start else None
    ref = reference(game)
    tool_origin = {}
    for s in scenes:
        for w in s.get('tools') or []:
            tool_origin[w['tool']['name'].strip()] = owner[s['name']]
    by_role = {'A': 0, 'B': 0}
    handoff_list = []
    for step in ref:
        op = step['action_answer'].split('(')[0].strip()
        scene = step['position'].split(' -> ')[-1]
        actor = owner[scene]
        if op != 'craft':
            by_role[actor] += 1
        for tool in needed_tools(step):
            if tool in tool_origin and tool_origin[tool] != actor and op != 'craft':
                handoff_list.append(dict(tool=tool, found_by=tool_origin[tool], used_by=actor,
                                         action=step['action_answer']))
        if op == 'craft':
            origins = {t: tool_origin.get(t) for t in needed_tools(step)}
            if len(set(origins.values()) - {None}) > 1:
                handoff_list.append(dict(tool=' + '.join(sorted(origins)), found_by='both', used_by='either',
                                         action=step['action_answer']))
    handoffs = len(handoff_list)
    cross_clues = []
    for clue in clue_annotations(game):
        actor = owner[clue['target_scene']]
        partner_sources = [x['object'] for x in clue['sources'] if owner[x['scene']] != actor]
        if partner_sources:
            cross_clues.append(dict(answer=clue['answer'], target=clue['target'], target_role=actor,
                                    partner_sources=partner_sources,
                                    all_sources_with_partner=len(partner_sources) == len(clue['sources'])))
    with Quiet():
        alone_a = closure(game, owner, ['A'], starts=starts)[0]
        alone_b = closure(game, owner, ['B'], starts=starts)[0]
        together = closure(game, owner, ['A', 'B'], starts=starts)[0]
        with_give = closure(game, owner, ['A', 'B'], allow_give=True, starts=starts)[0]
        world = World(game, owner, starts)
        b_enters = bool(world.reachable('B'))
    total = len(ref)
    counted = by_role['A'] + by_role['B']
    return dict(game=game, scenes=len(names), B=sorted(b_scenes, key=names.index), b_start=b_start, total=total,
                alone_A=alone_a, alone_B=alone_b, together_no_give=together, with_give=with_give,
                b_share=round(by_role['B']/counted, 2) if counted else 0, handoffs=handoffs,
                components={r: components([n for n in names if owner[n] == r], adj) for r in 'AB'},
                b_enters_at_start=b_enters, clue_inputs_cross=len(cross_clues), cross_clues=cross_clues,
                reference_handoffs=handoff_list)


class Quiet:
    """The upstream engine prints (including correct codes); keep stdout clean."""

    def __enter__(self):
        import contextlib
        import io
        self._cm = contextlib.redirect_stdout(io.StringIO())
        self._cm.__enter__()

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


def main():
    roles_dir = oe.ROOT/'data/roles'
    files = [Path(p) for p in sys.argv[1:]] or sorted(roles_dir.glob('*.json'))
    for f in files:
        spec = json.loads(f.read_text())
        m = metrics(spec['game'], set(spec['B']), spec.get('starts', {}).get('B'))
        m.pop('B')
        print(json.dumps(m, ensure_ascii=False))


if __name__ == '__main__':
    main()
