"""Write the A/B splits (v3) of all 12 EscapeBench games to data/roles/<game>.json.

Each B list below is the first-ranked split of `python -m scripts.search_splits
<game>` (criteria in that file), run on 2026-11-16. `--verify` reruns the search
and fails if any list is no longer ranked first (about 2 minutes).

History: v1 (data/roles/v1/, Codex pilot, 8 games, second role enters when
reachable) left one role with nothing to do in 5 of 8 games. A v2 draft
(2026-11-14) added the two-room start but counted only verbatim code clues and
allowed a close-up inside the partner's room; coop results made with it are
reported as stale by scripts/matrix_report.py.

Each file holds: the split, B's start scene, metrics from scripts.split_metrics,
the cross-room code clues and reference-path object handoffs (evaluator-only).
"""
import json
from pathlib import Path
import sys

from scripts.split_metrics import Quiet, load, metrics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/roles'
VERSION = 'v3'

SPLITS = {
    'game1-1-easy': ['bathroom', 'mirror close-up', 'ventilation fan close-up', 'dining room and kitchen',
                     'dining table close-up', 'cabinet above stove close-up', 'left cabinet close-up',
                     'right cabinet close-up', 'cabinet above sink close-up', 'sink close-up'],
    'game1-2-easy': ['elevator room', 'elevator interior', 'room 805', 'desk close-up', 'left bookshelf close-up',
                     'bedside table close-up', 'right bookshelf close-up', '805 right room'],
    'game1-3-easy': ['the billiard room', 'front desk', 'pool table'],
    'game1-4-easy': ['kitchen', 'storage room'],
    'game1-5-easy': ['the dormitory', 'bed close-up', 'cabinet close-up'],
    'game2-1-easy': ['corridor', 'world map', 'study room', 'utility room 2', 'bathroom'],
    'game2-2-easy': ['inner office', 'right side of inner office', 'left side of inner office', 'store room'],
    'game2-3-easy': ['workspace area', 'workspace cabinet close-up', 'desk close-up', 'workspace shelf close-up',
                     'car photos and map close-up', 'attic', 'attic door close-up', 'fingerprint scanner close-up',
                     'kitchen', 'shelf above sink close-up', 'mirror close-up', 'drawers below sink close-up',
                     'shelf above food preparation area close-up', 'drawers below food preparation area close-up',
                     'sink close-up', 'kitchen door close-up', 'storage room', 'storage room safe close-up',
                     'storage shelf close-up', 'cellar door close-up'],
    'game2-4-easy': ['hallway behind door', 'lab room overview', 'computer desk', 'wall of safes',
                     'experiment table area'],
    'game2-5-easy': ['passage way in van', 'drawers', 'bed overview', 'right side of bed', 'bed shelf inside'],
    'game3-1-easy': ['middle hallway', 'boxes pile in hallway', 'office door overview', 'office room overview',
                     'office room desk', 'office room drawers', 'shelves region overview', 'shelves region table',
                     'shelves region left', 'shelves region middle', 'control device on pillar', 'wash basin place'],
    'game3-2-easy': ['left corridor overview', 'end of left corridor', 'office room overview', 'office room right side'],
}
# No split of this game into whole rooms needs >= 15% of steps to involve a handoff.
LOW_INTERDEPENDENCE = {'game1-3-easy'}
KEEP = ('total', 'alone_A', 'alone_B', 'together_no_give', 'with_give', 'b_share', 'handoffs',
        'components', 'clue_inputs_cross')


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for game, b in SPLITS.items():
        names = [s['name'] for s in load(game)]
        assert set(b) <= set(names) and names[0] not in b, game
        with Quiet():
            m = metrics(game, set(b))
        spec = dict(version=VERSION, game=game, A=[n for n in names if n not in b],
                    B=[n for n in names if n in b], starts={'B': m['b_start']},
                    low_interdependence=game in LOW_INTERDEPENDENCE,
                    metrics={k: m[k] for k in KEEP},
                    cross_clues=m['cross_clues'], reference_handoffs=m['reference_handoffs'],
                    method='First-ranked split of scripts/search_splits.py; see scripts/make_roles.py',
                    note='Evaluator-only. Clues, handoffs and metrics must never be shown to agents.')
        path = OUT/f'{game}.json'
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\n')
        written.append(path)
    return written


def verify():
    from scripts.search_splits import search
    bad = []
    for game, b in SPLITS.items():
        result = search(game, top=1)
        names = [s['name'] for s in load(game)]
        first = result['top'][0]['B'] if result['top'] else None
        ok = first == [n for n in names if n in b] and result['low_interdependence'] == (game in LOW_INTERDEPENDENCE)
        print(f'{game}: {"ok" if ok else "MISMATCH"} (valid candidates: {result["candidates"]} of {result["tried"]})')
        if not ok:
            bad.append(game)
    if bad:
        raise SystemExit(f'Not first-ranked any more: {bad}')


if __name__ == '__main__':
    if '--verify' in sys.argv:
        verify()
    for p in build():
        print(p.relative_to(ROOT))
