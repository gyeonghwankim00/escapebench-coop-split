"""One GPU/model load, matched solo conditions, independent seeds, resumable trials."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import statistics
import time

from scripts.run_model import HFModel, ROOT, write_json
from scripts.solo_experiment import (INSTRUCTIONS, PROTOCOL_VERSION, Settings, compile_reference,
                                     messages_for, new_world, run_trial)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_plan(path, seeds=None):
    plan = json.loads(Path(path).read_text())
    if seeds is not None:
        plan['seeds'] = seeds
    if not plan.get('seeds') or len(set(plan['seeds'])) != len(plan['seeds']):
        raise ValueError('Use distinct, nonempty seeds')
    if any(type(s) is not int or not 0 <= s < 2**32 for s in plan['seeds']):
        raise ValueError('Seeds must be integers in [0, 2**32)')
    paths = [ROOT / p for p in plan['datasets']]
    if not paths or len({p.parent.name for p in paths}) != len(paths) or not all(p.is_file() for p in paths):
        raise ValueError('Datasets must exist and have distinct parent names')
    ids = [c['id'] for c in plan['conditions']]
    if not ids or len(set(ids)) != len(ids) or not all(re.fullmatch('[a-z0-9_]+', x) for x in ids):
        raise ValueError('Invalid or duplicate condition identifiers')
    for condition in plan['conditions']:
        if set(condition) != {'id', 'thinking', 'hints'}:
            raise ValueError('Conditions may vary only thinking and hints')
        Settings(**plan['settings'], thinking=condition['thinking'], hints=condition['hints']).validate()
    return plan


def local_model_identity(model):
    path = Path(model)
    if not path.is_dir():
        return dict(repository=model)
    # Small config/tokenizer content hashes plus weight sizes/mtime. Not full weight hashes.
    identity = {}
    for p in sorted(path.iterdir()):
        if p.is_file() and p.suffix in ('.json', '.jinja', '.safetensors'):
            identity[p.name] = dict(size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns)
            if p.suffix != '.safetensors':
                identity[p.name]['sha256'] = sha(p)
    return identity


def trials(plan):
    for seed in plan['seeds']:
        for dataset in plan['datasets']:
            for condition in plan['conditions']:
                yield dict(dataset=dataset, seed=seed, condition=condition['id'],
                           settings=asdict(Settings(**plan['settings'], thinking=condition['thinking'], hints=condition['hints'])))


def trial_parent(output, trial):
    return output / Path(trial['dataset']).parent.name / trial['condition'] / f'seed-{trial["seed"]}'


def latest_summary(parent):
    attempts = sorted(parent.glob('attempt-*'))
    if not attempts:
        return None
    path = attempts[-1] / 'summary.json'
    return json.loads(path.read_text()) if path.exists() else None


def report(output, plan):
    rows = []
    for trial in trials(plan):
        result = latest_summary(trial_parent(output, trial))
        rows.append(dict(**trial, result=result))
    write_json(output/'results.json', rows)
    groups = []
    lines = ['# Solo pilot results', '',
             'One row per dataset and condition; seeds are repeats, not independent puzzles.',
             'Pre-help progress = first-hint progress, or final progress if no hint was given.',
             'A step/time cap before first stall or escape is censored. Errors/interrupted trials are excluded from means.', '',
             '| Dataset | Condition | Evaluated/planned | Escape | Pre-help progress | Final progress | Hints | Censored |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for dataset in plan['datasets']:
        for condition in plan['conditions']:
            selected = [r for r in rows if r['dataset'] == dataset and r['condition'] == condition['id']]
            valid = [r['result'] for r in selected if r['result'] and r['result']['stop_reason'] not in
                     ('error', 'interrupted', 'no_feasible_hint')]
            def mean(values):
                values = list(values)
                return statistics.mean(values) if values else None
            group = dict(dataset=dataset, condition=condition['id'], planned=len(selected), evaluated=len(valid),
                         successes=sum(r['success'] for r in valid),
                         pre_help_progress=mean((r['first_hint']['progress'] if r['first_hint'] else r['progress'])['fraction'] for r in valid),
                         final_progress=mean(r['progress']['fraction'] for r in valid),
                         hints=mean(r['hints_used'] for r in valid),
                         censored=sum(not r['first_stall'] and not r['success'] for r in valid))
            groups.append(group)
            def pct(x): return '—' if x is None else f'{x:.1%}'
            lines.append(f'| {Path(dataset).parent.name} | {condition["id"]} | {len(valid)}/{len(selected)} | '
                         f'{group["successes"]} | {pct(group["pre_help_progress"])} | {pct(group["final_progress"])} | '
                         f'{group["hints"] if valid else "—"} | {group["censored"]} |')
    write_json(output/'aggregate.json', groups)
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT/'experiments/solo_pilot.json')
    parser.add_argument('--model', default='Qwen/Qwen3-8B')
    parser.add_argument('--revision', default='main')
    parser.add_argument('--quantization', choices=['4bit', 'none'], default='4bit')
    parser.add_argument('--context-tokens', type=int, default=8192)
    parser.add_argument('--seeds', type=int, nargs='+')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--resume', type=Path, help='Skip completed trials; restart interrupted trials with the same seed.')
    parser.add_argument('--dry-run', action='store_true', help='Validate all references and save initial prompts, without loading a model.')
    parser.add_argument('--wall-seconds', type=int, default=36000)
    args = parser.parse_args()
    if args.resume and (args.output or args.dry_run):
        parser.error('--resume cannot be combined with --output or --dry-run')
    plan = load_plan(args.plan, args.seeds)
    if args.wall_seconds < 1 or plan['settings']['max_new_tokens'] >= args.context_tokens:
        parser.error('Invalid wall time or context budget')
    output = args.resume or args.output or ROOT/'outputs'/('experiment-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    fingerprint = dict(protocol=PROTOCOL_VERSION, plan=plan, model=args.model, revision=args.revision,
                       quantization=args.quantization, context_tokens=args.context_tokens,
                       local_model_identity=local_model_identity(args.model),
                       dataset_hashes={p: sha(ROOT/p) for p in plan['datasets']},
                       code_hashes={p: sha(ROOT/p) for p in ('scripts/run_experiment.py', 'scripts/solo_experiment.py',
                                                          'scripts/run_model.py', 'scripts/coop_escape.py')})
    if args.resume:
        if json.loads((output/'experiment.json').read_text()) != fingerprint:
            raise SystemExit('Resume settings, code, datasets or model identity changed. Start a new output directory.')
        if (output/'preview.json').exists():
            raise SystemExit('Cannot resume a dry run. Submit a new experiment.')
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output/'experiment.json', fingerprint)
    # Validate the hint oracle on all chosen problems before spending GPU inference time.
    for dataset in plan['datasets']:
        compile_reference(ROOT/dataset)
    if args.dry_run:
        for dataset in plan['datasets']:
            world = new_world(ROOT/dataset)
            for condition in plan['conditions']:
                settings = Settings(**plan['settings'], thinking=condition['thinking'], hints=condition['hints'])
                write_json(output/f'{Path(dataset).parent.name}-{condition["id"]}-prompt.json',
                           messages_for(world.observe('A'), [], settings))
        write_json(output/'preview.json', dict(trials=len(list(trials(plan))), model_loaded=False))
        print(f'Validated plan and references; prompt previews: {output}')
        return
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Model inference requires a Slurm allocation. Use --dry-run locally.')
    stopped = [False]
    signal.signal(signal.SIGUSR1, lambda *_: stopped.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: stopped.__setitem__(0, True))
    started = time.monotonic()
    def stop(): return stopped[0] or time.monotonic()-started >= args.wall_seconds
    pending = [t for t in trials(plan) if (s := latest_summary(trial_parent(output, t))) is None or s['stop_reason'] == 'interrupted']
    if not pending:
        rows = report(output, plan)
        print(f'All trials already recorded: {output}')
        if any(r['result']['stop_reason'] in ('error', 'no_feasible_hint') for r in rows):
            raise SystemExit(1)
        return
    # HFModel only needs these legacy constructor attributes in addition to the above.
    args.seed = plan['seeds'][0]
    args.max_new_tokens = plan['settings']['max_new_tokens']
    print(f'Experiment output: {output}; pending trials: {len(pending)}', flush=True)
    try:
        backend = HFModel(args)
    except Exception as exc:
        write_json(output/'load_error.json', dict(error=f'{type(exc).__name__}: {exc}'))
        raise
    with (output/'model_loads.jsonl').open('a') as handle:
        handle.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(), **backend.metadata))+'\n')
    if not (output/'model.json').exists():
        write_json(output/'model.json', backend.metadata)
    elif json.loads((output/'model.json').read_text()).get('resolved_revision') != backend.metadata.get('resolved_revision'):
        raise SystemExit('Model repository revision changed since the first run. Use a new output directory.')
    for trial in pending:
        if stop(): break
        parent = trial_parent(output, trial)
        attempt = parent / f'attempt-{len(list(parent.glob("attempt-*")))+1:03}'
        backend.torch.manual_seed(trial['seed'])
        backend.torch.cuda.manual_seed_all(trial['seed'])
        backend.torch.cuda.reset_peak_memory_stats()
        print(f'\nTrial {trial["dataset"]} {trial["condition"]} seed={trial["seed"]}', flush=True)
        result = run_trial(ROOT/trial['dataset'], backend, Settings(**trial['settings']), attempt, stop)
        write_json(attempt/'trial.json', trial)
        write_json(attempt/'gpu.json', dict(peak_allocated_bytes=backend.torch.cuda.max_memory_allocated(),
                                          peak_reserved_bytes=backend.torch.cuda.max_memory_reserved()))
        report(output, plan)
        if result['stop_reason'] == 'interrupted': break
    rows = report(output, plan)
    incomplete = any(not r['result'] or r['result']['stop_reason'] in ('interrupted', 'error', 'no_feasible_hint') for r in rows)
    print(f'Results: {output}/report.md', flush=True)
    if incomplete:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
