"""Freeze four observed failure states; no model calls. Evaluator data only."""
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('move', 'pilot-v3-g2-14B-main', 'game2-4-easy', 1),
    ('collect_key', 'pilot-v3-g2-14B-control', 'game1-3-easy', 63),
    ('collect_hammer', 'pilot-v3-g2-14B-control', 'game1-3-easy', 103),
    ('request_not_give', 'diagnostic-v3-g2-14B-move-labels', 'game2-4-easy', 100),
]


def main():
    dest = ROOT/'data/state_probes'
    dest.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, run, game, step in CASES:
        root = ROOT/'outputs/matrix'/run
        source = root/'coop'/game/'turns.jsonl'
        rows = [json.loads(x) for x in source.read_text().splitlines()][:step+1]
        assert len(rows) == step+1 and not any(r['helper_active'] for r in rows)
        roles = json.loads((root/'evaluation_inputs/roles'/f'{game}.json').read_text())
        manifest = json.loads((root/'experiment.json').read_text())
        case = dict(id=name, game=game, step=step, source=run,
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    source_interface=manifest['settings'].get('interface', 'original'), roles=roles, rows=rows)
        (dest/f'{name}.json').write_text(json.dumps(case, ensure_ascii=False)+'\n')
        cases.append(name)
    (dest/'manifest.json').write_text(json.dumps(dict(version=1, cases=cases,
        note='Selected failure states, not representative benchmark samples; one next-action probe per condition.'), indent=2)+'\n')
    print(dest)


if __name__ == '__main__':
    main()
