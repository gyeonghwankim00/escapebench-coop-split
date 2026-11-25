"""Check that the A/B splits in roles/ fit a local copy of EscapeBench.

Usage:
    pip install PyYAML
    python check_split.py /path/to/EscapeBench/data

For each game it checks:
  * the game YAML is byte-identical to the pinned upstream version (sha256 in
    verification.json); a different YAML means scene names may not match;
  * every scene is assigned to exactly one role (A or B);
  * the original start scene (first scene in the YAML) belongs to A;
  * B's start scene belongs to B;
  * each role's scenes, plus the scenes it may cross (see README, rule 2), are
    connected in the scene graph, so no owned scene is unreachable by design.

It does not replay the game; verification.json records the replay checks.
"""
import hashlib
import json
from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent


def neighbors(scenes):
    adj = {s['name']: set() for s in scenes}
    for s in scenes:
        for t in (s.get('scene_relations') or {}).values():
            adj[s['name']].add(t)
            adj[t].add(s['name'])
    return adj


def reachable(start, adj, allowed):
    seen, stack = {start}, [start]
    while stack:
        for v in adj[stack.pop()]:
            if v in allowed and v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


def check(game, data_dir, expected_sha):
    problems = []
    path = data_dir / f'{game}.yaml'
    if not path.exists():
        return [f'{path} not found']
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        problems.append('YAML differs from the pinned upstream version (scene names may not match)')
    spec = json.loads((HERE / 'roles' / f'{game}.json').read_text())
    scenes = yaml.safe_load(raw.decode())
    names = [s['name'] for s in scenes]
    a, b = spec['A'], spec['B']
    if sorted(a + b) != sorted(names) or set(a) & set(b):
        missing = set(names) - set(a) - set(b)
        extra = (set(a) | set(b)) - set(names)
        problems.append(f'scenes not assigned exactly once (missing={sorted(missing)}, unknown={sorted(extra)}, '
                        f'both={sorted(set(a) & set(b))})')
        return problems
    if names[0] not in a:
        problems.append(f'original start scene {names[0]!r} is not owned by A')
    b_start = spec['starts']['B']
    if b_start not in b:
        problems.append(f'B start {b_start!r} is not owned by B')
    adj = neighbors(scenes)
    # A role crosses partner scenes but never stops there; graph-wise every scene
    # is allowed, so this only flags owned scenes with no path at all.
    for role, start, own in (('A', names[0], set(a)), ('B', b_start, set(b))):
        lost = own - reachable(start, adj, set(names))
        if lost:
            problems.append(f'{role} owns scenes unreachable from its start: {sorted(lost)}')
    return problems


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    data_dir = Path(sys.argv[1])
    ver = json.loads((HERE / 'verification.json').read_text())
    failed = 0
    for game, info in ver['games'].items():
        problems = check(game, data_dir, info['upstream_yaml_sha256'])
        failed += bool(problems)
        print(f'{game}: ' + ('ok' if not problems else 'FAIL'))
        for p in problems:
            print(f'    - {p}')
    print(f'\n{len(ver["games"]) - failed}/{len(ver["games"])} games ok '
          f'(upstream {ver["upstream"]["repository"]} @ {ver["upstream"]["commit"][:7]})')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
