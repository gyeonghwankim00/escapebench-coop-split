"""Export the v1 (pilot) A/B scene assignment to data/roles/v1/<game>.json.

The assignment and clue annotations come from scripts/build_pilot.py CONFIGS, so
the 2-agent runner on the original engine uses exactly the same split as the
pilot dataset. Every upstream scene is listed once; unlisted scenes belong to A.
"""
import json
from pathlib import Path

import yaml

from scripts.build_pilot import CONFIGS

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_DATA = ROOT / 'vendor/escapebench/data'
OUT = ROOT / 'data/roles/v1'


def export():
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for config in CONFIGS:
        game = f'game{config["source"]}-easy'
        scenes = [s['name'] for s in yaml.safe_load((UPSTREAM_DATA/f'{game}.yaml').read_text())]
        b = [s for s in scenes if s in config['b']]
        assert set(b) == set(config['b']), (game, set(config['b']) - set(scenes))
        for name in scenes:
            assert ',' not in name and '(' not in name and ')' not in name, name
        spec = dict(game=game, pilot_id=config['id'], title=config['title'],
                    A=[s for s in scenes if s not in b], B=b,
                    clues=[dict(holder_source=c[0], target=c[1], answer=c[2], tokens=c[3])
                           for c in config['clues']],
                    note='Evaluator-only. Clue answers must never be shown to agents.')
        path = OUT/f'{game}.json'
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + '\n')
        written.append(path)
    return written


if __name__ == '__main__':
    for p in export():
        print(p.relative_to(ROOT))
