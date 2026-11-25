"""Search A/B scene splits for an upstream game by explicit criteria.

Territory units (what is assigned to a role as a whole)
  A dead-end group of scenes is merged into the scene it opens from when it is
  a sub-view rather than a room: its entry scene is named "... close-up", or it
  is a single scene that can be entered freely at the start. Rooms (several
  scenes, or a single scene behind a locked door) stay separate units. So a
  role never owns a close-up inside the partner's room.
Every assignment of units to A/B is scored (the start unit is always A, B starts
inside its own territory; see scripts.split_metrics).

Hard constraints
  * with give() the split completes as many reference steps as the unsplit
    game does under the same greedy check
  * each role can do at least 10% of the reference steps with no partner action
    (no idle role; an 8B smoke run showed what alone=0 does)
  * cooperation is required: at least 15% of steps need an object handoff.
    If no split of a game satisfies this one, it is dropped for that game and
    the game is flagged low_interdependence.
Order of preference among valid splits
  1. splits with at least one cross-room code clue (data/clues.json)
  2. score = 3 * min(alone_A, alone_B) / total        both have real work
           - 2 * |b_share - 0.5|                      balanced workload
           - 0.5 * (components_A + components_B - 2)  one connected territory each
           + 0.5 * min(handoffs, 8) / 8               object exchange
           + 1.0 * min(clue_inputs_cross, 3) / 3      cross-room code clues
           - 1.0 * max(0, handoffs - 12) / 12         not handoff-dominated

Usage: python -m scripts.search_splits game1-4-easy [more] [--top 5]
"""
import argparse
import itertools
import json
import math
from multiprocessing import Pool

from scripts.split_metrics import Quiet, closure, load, metrics, neighbors


def units(game):
    scenes = load(game)
    names = [s['name'] for s in scenes]
    visible = {s['name']: s.get('visible', True) for s in scenes}
    adj = neighbors(scenes)
    group = {n: n for n in names}
    start = names[0]
    changed = True
    while changed:
        changed = False
        for g in list(dict.fromkeys(group.values())):
            if g == group[start]:
                continue
            members = [n for n in names if group[n] == g]
            hosts = {group[v] for n in members for v in adj[n]} - {g}
            if len(hosts) != 1:
                continue
            host = next(iter(hosts))
            entries = [n for n in members if any(group[v] == host for v in adj[n])]
            sub_view = (any('close-up' in n for n in entries)
                        or (len(members) == 1 and visible[members[0]]))
            if sub_view:
                for n in members:
                    group[n] = host
                changed = True
    result = {}
    for n in names:
        result.setdefault(group[n], []).append(n)
    return names, sorted(result.values(), key=lambda ms: min(names.index(m) for m in ms))


def check(m, baseline):
    """Names of the hard constraints a split violates."""
    total, failed = m['total'], []
    if m['with_give'] < baseline or not m['b_enters_at_start']:
        failed.append('not_completable')
    if min(m['alone_A'], m['alone_B']) < max(1, math.ceil(0.1 * total)):
        failed.append('idle_role')
    if total - m['together_no_give'] < 0.15 * total:
        failed.append('low_interdependence')
    return failed


def score(m):
    total = m['total']
    return (3 * min(m['alone_A'], m['alone_B']) / total
            - 2 * abs(m['b_share'] - 0.5)
            - 0.5 * (m['components']['A'] + m['components']['B'] - 2)
            + 0.5 * min(m['handoffs'], 8) / 8
            + 1.0 * min(m['clue_inputs_cross'], 3) / 3
            - max(0, m['handoffs'] - 12) / 12)


def _evaluate(job):
    game, b, baseline = job
    with Quiet():
        m = metrics(game, set(b))
    m['failed'] = check(m, baseline)
    m['score'] = round(score(m), 3)
    return m


def rank(results):
    """Valid splits in order of preference; falls back to low-interdependence
    splits (flagged) when a game has no fully valid one."""
    key = lambda m: (m['clue_inputs_cross'] >= 1, m['score'])
    valid = sorted((m for m in results if not m['failed']), key=key, reverse=True)
    if valid:
        return valid, False
    relaxed = sorted((m for m in results if m['failed'] == ['low_interdependence']), key=key, reverse=True)
    return relaxed, True


def search(game, top=5, workers=8):
    names, grouped = units(game)
    with Quiet():
        baseline = closure(game, {n: 'A' for n in names}, ['A'])[0]
    rest = grouped[1:]
    jobs = []
    for bits in itertools.product((0, 1), repeat=len(rest)):
        b = [n for g, bit in zip(rest, bits) if bit for n in g]
        if b:
            jobs.append((game, b, baseline))
    with Pool(workers) as pool:
        results = pool.map(_evaluate, jobs, chunksize=4) if jobs else []
    ranked, low = rank(results)
    return dict(game=game, groups=grouped, baseline=baseline, tried=len(jobs), candidates=len(ranked),
                low_interdependence=low, top=ranked[:top])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('games', nargs='+')
    parser.add_argument('--top', type=int, default=5)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    for game in args.games:
        print(json.dumps(search(game, args.top, args.workers), ensure_ascii=False))


if __name__ == '__main__':
    main()
