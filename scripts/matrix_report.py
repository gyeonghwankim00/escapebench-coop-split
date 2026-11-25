"""Paired Solo vs 2-agent comparison across outputs/matrix/<run>/ directories.

Which results count
  * Solo: one controller of both roles in the split environment (current protocol).
  * Legacy solo records are labeled original_solo and excluded from Solo/Peer pairs.
  * Coop: only runs made with the current role file of that game and the
    current coop layer. Results from older splits are listed as "stale".
  * Older generation versions (including old Solo) are shown as "old_generation"
    and excluded from paired comparisons.
Dry runs and smoke checks never count. Each game is one paired sample;
differences are reported per game, never pooled as independent trials.

Usage: python -m scripts.matrix_report [--status] [outputs/matrix ...]
  --status  only print which (model, condition, game) results exist, are
            running/interrupted, stale or missing (use it to decide what to submit).
Several directories may be given; a later one overrides earlier ones.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys

from scripts.run_matrix import ALL_GAMES, FINAL, GENERATION_VERSION, ROLES_DIR, file_hash, PROTOCOL

ROOT = Path(__file__).resolve().parents[1]
FULL = dict(max_steps=4000, context_tokens=8192, max_new_tokens=256)


def collect(base, interface='original'):
    """(model, condition, game) -> dict(state=..., row=summary or None, run=dir name)."""
    coop_code = file_hash(ROOT/'scripts/coop_original.py')
    roles = {g: file_hash(ROLES_DIR/f'{g}.json') for g in ALL_GAMES}
    found = {}
    for exp in sorted(base.glob('*/experiment.json')):
        manifest = json.loads(exp.read_text())
        settings = manifest['settings']
        if settings.get('interface', 'original') != interface:
            continue
        if manifest.get('dry_run') or exp.parent.name.startswith('smoke'):
            continue
        if any(settings.get(k) != v for k, v in FULL.items()):
            continue
        incompatible_generation = manifest.get('generation_version', 1) != GENERATION_VERSION
        model = Path(manifest['model']).name
        for stored_condition in manifest['conditions']:
            condition = ('original_solo' if stored_condition == 'solo'
                         and not manifest.get('protocol', '').startswith(('escapebench-split-solo-vs-peer-', 'escapebench-adaptive-'))
                         else stored_condition)
            for game in manifest['games']:
                summary = exp.parent/stored_condition/game/'summary.json'
                row = json.loads(summary.read_text()) if summary.exists() else None
                stale = condition in ('solo', 'coop') and (manifest['role_hashes'].get(game) != roles.get(game)
                                                 or manifest['code_hashes']['scripts/coop_original.py'] != coop_code)
                if condition == 'solo' and manifest['code_hashes'].get('scripts/central_solo.py') != file_hash(ROOT/'scripts/central_solo.py'):
                    stale = True
                if condition in ('solo','coop') and (manifest.get('protocol') != PROTOCOL or manifest['code_hashes'].get('scripts/adaptive_escape.py') != file_hash(ROOT/'scripts/adaptive_escape.py')):
                    stale = True
                if incompatible_generation:
                    state = 'old_generation'
                elif stale:
                    state = 'stale'
                elif row is None:
                    turns = exp.parent/stored_condition/game/'turns.jsonl'
                    state = 'started' if turns.exists() else 'queued'
                else:
                    state = 'done' if row['stop_reason'] in FINAL else row['stop_reason']
                entry = dict(state=state, row=row, run=exp.parent.name)
                old = found.get((model, condition, game))
                rank = {'done': 4, 'interrupted': 3, 'started': 3, 'error': 2, 'queued': 1,
                        'stale': 0, 'old_generation': -1}
                if old is None or rank[state] >= rank[old['state']]:
                    found[model, condition, game] = entry
    return found


def fmt(value, suffix=''):
    return '—' if value is None else f'{value:g}{suffix}'


def status(found):
    lines = ['# Coverage (stale = older split/code; old_generation = excluded decoding version; — = missing)', '']
    for model in sorted({k[0] for k in found}) or ['(no runs found)']:
        lines += [f'## {model}', '', '| Game | Split Solo | Peer | Original Solo (legacy) |', '|---|---|---|---|']
        for game in ALL_GAMES:
            cells = []
            for condition in ('solo', 'coop', 'original_solo'):
                e = found.get((model, condition, game))
                if e is None:
                    cells.append('—')
                elif e['row'] is not None and e['state'] not in ('stale', 'old_generation'):
                    cells.append(f'{e["state"]} ({e["row"]["steps"]} steps, {e["run"]})')
                else:
                    cells.append(f'{e["state"]} ({e["run"]})')
            lines.append(f'| {game} | {cells[0]} | {cells[1]} |')
        lines.append('')
    return lines


def comparison(found):
    lines = ['# Solo vs 2-agent: paired by game', '',
             'Finished episodes only (success / step budget). Hints = original 50-step stagnation helps; '
             'fewer is better. Pre-help = progress before the first hint.', '']
    for model in sorted({k[0] for k in found}):
        lines += [f'## {model}', '',
                  '| Game | Solo hints | Coop hints | Δ hints | Solo pre-help | Coop pre-help | '
                  'Solo steps | Coop steps | Coop msgs / gives before 1st hint |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        deltas = []
        for game in ALL_GAMES:
            def final(condition):
                e = found.get((model, condition, game))
                return e['row'] if e and e['state'] == 'done' else None
            s, c = final('solo'), final('coop')
            delta = c['hints_used'] - s['hints_used'] if s and c else None
            if delta is not None:
                deltas.append(delta)
            lines.append(
                f'| {game} | {fmt(s and s["hints_used"])} | {fmt(c and c["hints_used"])} | {fmt(delta)} | '
                f'{fmt(s and s["pre_help_progress_percent"], "%")} | {fmt(c and c["pre_help_progress_percent"], "%")} | '
                f'{fmt(s and s["steps"])} | {fmt(c and c["steps"])} | '
                f'{(str(c["messages_before_first_hint"]) + " / " + str(c["gives_before_first_hint"])) if c else "—"} |')
        if deltas:
            lines += ['', f'Paired games: {len(deltas)}/{len(ALL_GAMES)}. Median Δ hints (coop − solo): '
                      f'{statistics.median(deltas):g}; coop fewer / equal / more: '
                      f'{sum(d < 0 for d in deltas)} / {sum(d == 0 for d in deltas)} / {sum(d > 0 for d in deltas)}.', '']
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bases', nargs='*', type=Path)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--interface', choices=['original', 'move_labels', 'action_labels'], default='original')
    args = parser.parse_args()
    bases = args.bases or [ROOT/'outputs/matrix']
    found = {}
    for base in bases:
        found.update(collect(base, args.interface))
    if args.status:
        print('\n'.join(status(found)))
        return
    lines = comparison(found) + [''] + status(found)
    out = bases[-1]/('comparison.md' if args.interface == 'original' else f'comparison-{args.interface}.md')
    out.write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print(f'\nWritten: {out}')


if __name__ == '__main__':
    main()
