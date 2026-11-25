"""Write data/clues.json: where the clue for every code input lives (all 12 games).

Evaluator-only and independent of any A/B split. For each reference `input`
step it lists the source objects (or '@scene' for a scene description) whose
text is needed to derive the answer, with an evidence string that must occur
verbatim in that object's text in the upstream YAML (checked here).

Sources: the 8 pilot games reuse the annotations in scripts/build_pilot.py
(Codex-built, token-checked); the other 4 games (1-4, 1-5, 2-3, 3-1) were
annotated on 2026-11-14 by reading the upstream YAML. All listed sources are
jointly needed unless the derivation note says otherwise.
"""
import json
from pathlib import Path

from scripts.build_pilot import CONFIGS
from scripts.split_metrics import load, reference

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/clues.json'

# game -> answer -> (derivation note, [(source object or @scene, evidence substring), ...])
NEW = {
    'game1-4-easy': {
        '17:45': ('time shown on the watch', [('watch', '17:45')]),
        '7049': ('number that appears on the front door after authorization', [('front door', '7049')]),
        '690716': ('six-digit number on the birthday chart', [('birthday chart', '690716')]),
    },
    'game1-5-easy': {
        '3141': ('first digits of pi; the box says to skip the dot', [('paper 1', 'large pi'), ('iron box', 'dot between the first and the second digit')]),
        '55401530': ('ZZ=55 and ZX+AZ=68 give Z=5, X=3, A=1; substitute into ZZ, 40, AZ, X0',
                     [('paper', 'ZZ, 40, AZ, X0'), ('paper 2', 'ZZ=55, ZX+AZ=68')]),
        '2451': ('pattern on paper 3', [('paper 3', '2451')]),
        '1991281': ('characters on the imprinted photo paper', [('imprinted photo paper', '1991281')]),
        '18437': ('graffiti initials C Y O D W map to 1 7 4 8 3; reorder as CDOWY',
                  [('graffiti', '^Care ^Yourself ^Or the ^Doctor ^Will'), ('paper 4', '17483'), ('shaking mirror', 'CDOWY')]),
    },
    'game2-3-easy': {
        '5487': ('swapped clock digits', [('@clock and photos close-up', '5487')]),
        '330': ('number behind the spade card once it is stuck on the wall', [('adhesive tape remaining', '330')]),
        'diamond-square-triangle-circle': ('car colours red, green, blue, yellow -> shapes under the same-coloured solids',
            [('colored car photo', 'red, green, blue, and yellow'), ('red pyramid', 'diamond'),
             ('green cylinder placed on shelf', 'square'), ('blue hemisphere', 'triangle'), ('yellow cube', 'circle')]),
        'D2-A5-D5-G5-D8': ('badge order bird, tree, flag, hill, castle -> map coordinates',
            [('five badge slots', 'a bird badge, a tree badge, a flag badge, a hill badge, and a castle badge'),
             ('map', 'Tree (A 5). Flag (D 5). Castle (D 8). Birds (D 2)')]),
        '| 1 | 4 |   | 8 |\\n|   |   | 6 |   |\\n| 2 | 7 | 5 |   |\\n|   |   | 3 |   |': (
            'numbers of the table sheet at the cells that turn blue on the heated mug',
            [('table sheet', '| 1 | 4 | 2 | 8 |'), ('cup of hot water', '| x | x |   | x |')]),
        '0368': ('ROT13 of the note gives NIHILUM TRES SEX OCTO; the handbook maps Latin to digits',
                 [('note sheet', 'AVUVYHZGERFFRKBPGB'), ('@handbook close-up', '0 - zero - nihilum')]),
    },
    'game3-1-easy': {
        '16': ('S-16 on the dried shipping list', [('wet shipping list', 'S-16')]),
        '1325': ('owner name Jack looked up in the daily table: J 1, A 3, C 2, K 5',
                 [('daily service password', 'Place 1 - H 5, N 6, J 1'), ('name slot', 'Jack')]),
        'blue': ('missing colour of the painting sequence', [('painting', 'yellow, red, blue, and green'), ('iron safe', 'red, green, __ , yellow')]),
        '23415': ('water levels in the communicator channels', [('communicator', '2, 3, 4, 1, 5')]),
        '84459731': ('PUK code on the paper from the drawer', [('piece of paper code', '84459731')]),
        '3499': ('chat on the unlocked phone', [('old-fashioned phone', '3499')]),
        '100': ('12 + 28 + 25 + 35; the door shows a Sigma sign', [('exit code paper', '12 + 28 + 25 + 35'), ('exit door', 'Sigma')]),
    },
}


def texts(game):
    """object name or '@scene name' -> (scene, all description/reward text)."""
    out = {}
    for s in load(game):
        out['@' + s['name']] = (s['name'], s.get('desc', ''))
        for kind, key in (('items', 'item'), ('tools', 'tool')):
            for w in s.get(kind) or []:
                obj = w[key]
                parts = []
                for st in obj['states']:
                    parts.append(st.get('desc', ''))
                    parts += [t.get('reward', '') for t in st.get('transitions', []) or []]
                out[obj['name'].strip()] = (s['name'], ' '.join(parts))
    return out


def build():
    pilot = {f'game{c["source"]}-easy': c['clues'] for c in CONFIGS}
    data, problems = {}, []
    for game in sorted(set(pilot) | set(NEW)):
        tx = texts(game)
        entries = []
        for step in reference(game):
            action = step['action_answer']
            if not action.startswith('input('):
                continue
            answer, target = [x.strip() for x in action[6:-1].split(',', 1)]
            if game in NEW:
                note, sources = NEW[game][answer]
                sources = [(name, [ev]) for name, ev in sources]
            else:
                note = 'pilot annotation (scripts/build_pilot.py)'
                sources = [(c[0], list(c[3])) for c in pilot[game] if c[1] == target and c[2] == answer]
            if not sources:
                problems.append(f'{game}: no source for {answer!r}')
            rows = []
            for name, evidence in sources:
                if name not in tx:
                    problems.append(f'{game}: unknown source {name!r}')
                    continue
                scene, text = tx[name]
                for ev in evidence:
                    if ev not in text:
                        problems.append(f'{game}: {ev!r} not in text of {name!r}')
                rows.append(dict(object=name, scene=scene, evidence=evidence))
            entries.append(dict(target=target, target_scene=step['position'].split(' -> ')[-1],
                                answer=answer, derivation=note, sources=rows))
        data[game] = entries
    if problems:
        raise SystemExit('Clue annotation problems:\n  ' + '\n  '.join(problems))
    OUT.write_text(json.dumps(dict(
        note='Evaluator-only. Never shown to agents. Sources are where the clue is first found; '
             'clue tools (papers) can also be handed over with give().', games=data),
        indent=2, ensure_ascii=False) + '\n')
    return data


if __name__ == '__main__':
    built = build()
    print(OUT.relative_to(ROOT), {g: len(v) for g, v in built.items()}, 'inputs:', sum(map(len, built.values())))
