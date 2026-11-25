"""Fixed full-game cohort; no failure-case selection or prompt tuning."""
from scripts.cohort_policy import load_policy, DEFAULT_POLICY
import argparse
import json
import os
from pathlib import Path
import pwd
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
GAMES = [f'game{series}-{number}-easy' for series, count in [(1, 5), (2, 5), (3, 2)]
         for number in range(1, count + 1)]
TASKS = [(size, condition, game) for game in GAMES for size in ('14B', '32B')
         for condition in ('solo', 'coop')]
BUDGETS = (50, 200, 500, 1000)


def command(index, output_root):
    size, condition, game = TASKS[index]
    lab = Path('/shared/s2/lab04') / pwd.getpwuid(os.getuid()).pw_name / 'escape-lab'
    model = (ROOT if size == '14B' else lab) / 'models' / f'Qwen3-{size}'
    out = output_root / f'cohort-v2-{size}-{condition}-{game}'
    return [sys.executable, '-m', 'scripts.run_matrix', '--model', str(model),
            '--output', str(out), '--conditions', condition, '--games', game,
            '--interface', 'original', '--quantization', '4bit', '--max-batch', '1',
            '--max-steps', '4000', '--context-tokens', '8192', '--wall-seconds', '40200']


def budget_metrics(rows, summary, budget):
    # Missing/time-limited observations must never become zero scores.
    if sum(r.get('action_cost',1) for r in rows) < budget and summary.get('stop_reason') != 'success':
        return None
    if not rows:
        return None
    prefix=[]
    cost=0
    for row in rows:
        if cost >= budget:break
        prefix.append(row);cost+=row.get('action_cost',1)
    last = prefix[-1]
    # Escaped within this budget: the run succeeded and its final (escape) row is inside the prefix.
    escaped = summary.get('stop_reason') == 'success' and len(prefix) == len(rows)
    return dict(progress=last['upstream']['tracking']['progress'], escaped=escaped,
                hints=last['hints_used'],
                forced=sum(bool(r['forced_action']) for r in prefix),
                actions_observed=cost, decisions_observed=len(prefix),
                input_tokens=sum((r.get('generation') or {}).get('input_tokens',0) for r in prefix),
                output_tokens=sum((r.get('generation') or {}).get('output_tokens',0) for r in prefix),
                errors=sum(r['upstream']['response'].startswith('Error') for r in prefix))


def report(base, tasks=TASKS, max_steps=4000, prefix='cohort-v2', model_names=None, budgets=BUDGETS, context_tokens=8192, required_protocol=None, classification_path=DEFAULT_POLICY):
    model_names = model_names or {size: f'Qwen3-{size}' for size in ('14B', '32B')}
    policy, classification = load_policy(classification_path)
    results = []
    common = None
    roles = {}
    for index, (size, condition, game) in enumerate(tasks):
        run = base/f'{prefix}-{size}-{condition}-{game}'
        manifest_path = run/'experiment.json'
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if required_protocol and manifest.get('protocol') != required_protocol:
                raise ValueError(f'Legacy Solo definition: {run}')
            expected = dict(interface='original', max_batch=1, max_steps=max_steps, context_tokens=context_tokens)
            if (manifest.get('dry_run') or manifest['conditions'] != [condition]
                    or manifest['games'] != [game]
                    or Path(manifest['model']).name != model_names[size]
                    or any(manifest['settings'].get(k) != v for k,v in expected.items())):
                raise ValueError(f'Not a matching cohort run: {run}')
            signature = {k: manifest[k] for k in ('settings','code_hashes','generation_version','upstream_commit','quantization')}
            if common is not None and common != signature:
                raise ValueError(f'Mixed protocol/code in cohort: {run}')
            common = signature
            role = manifest['role_hashes'][game]
            if game in roles and roles[game] != role:
                raise ValueError(f'Mixed splits for {game}')
            roles[game] = role
        folder = run/condition/game
        summary = json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else {}
        rows = []
        trace = folder/'turns.jsonl'
        if trace.exists():
            with trace.open() as stream:
                for line in stream:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        raise ValueError(f'Incomplete/corrupt trace: {trace}; download again after the job stops')
        result = dict(index=index, model=size, condition=condition, game=game,
                      cohort=policy['games'].get(game,{}).get('tier','unreviewed'), classification=classification,
                      state=summary.get('stop_reason', 'started' if rows else 'excluded' if policy['games'].get(game,{}).get('tier')=='excluded' else 'missing'),
                      structural_review=policy['games'].get(game,{}),
                      summary=summary,
                      budgets={str(b): budget_metrics(rows, summary, b) for b in budgets})
        results.append(result)
    base.mkdir(parents=True, exist_ok=True)
    history=base/'classification_history'
    history.mkdir(exist_ok=True)
    (history/(classification['sha256']+'.json')).write_text(json.dumps(dict(metadata=classification,policy=policy),ensure_ascii=False,indent=2)+'\n')
    (base/'cohort-policy-used.json').write_text(json.dumps(dict(metadata=classification,policy=policy),ensure_ascii=False,indent=2)+'\n')
    (base/'cohort-results.json').write_text(json.dumps(results, indent=2)+'\n')
    lines = ['# Fixed 12-game cohort', '',
             f"Classification: {classification['version']}; SHA256: {classification['sha256']}", '',
             'Each game is one paired unit. Fixed-budget progress includes help: read hints/forced alongside it.',
             'Pre-help windows have different lengths; they are not fixed-budget performance.', '',
             '| Index | Model | Condition | Game | Cohort | State | Pre-help % / first hint step (0-based) | @500 progress / escaped / hints / forced |',
             '|---|---|---|---|---|---|---|---|']
    for r in results:
        s, b = r['summary'], r['budgets']['500']
        pre = f"{s.get('pre_help_progress_percent', '—')} / {s.get('first_hint_step', 'none')}" if s else '—'
        at = f"{b['progress']} / {'yes' if b['escaped'] else 'no'} / {b['hints']} / {b['forced']}" if b else 'unavailable'
        lines.append(f"| {r['index']} | {r['model']} | {r['condition']} | {r['game']} | {r['cohort']} | {r['state']} | {pre} | {at} |")
    lines += ['', 'Primary comparisons: core only. Extended comparisons are reported separately; controls/excluded never enter either mean.',
              'Escaped = original final escape action succeeded within the budget (count of complete pairs).',
              '| Tier / Model | Budget (environment actions) | Complete pairs | Solo progress | Peer progress | Solo escaped | Peer escaped |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for tier in ('core','extended'):
        for size in model_names:
            for budget in budgets:
                pairs=[]
                for game in dict.fromkeys(t[2] for t in tasks):
                    pair={r['condition']:r for r in results if r['model']==size and r['game']==game and r['cohort']==tier}
                    if all(c in pair and pair[c]['budgets'][str(budget)] is not None for c in ('solo','coop')):
                        pairs.append([pair[c]['budgets'][str(budget)] for c in ('solo','coop')])
                means=[f"{sum(p[i]['progress'] for p in pairs)/len(pairs):.2f}" for i in (0,1)] if pairs else ['unavailable']*2
                escapes=[f"{sum(p[i]['escaped'] for p in pairs)}/{len(pairs)}" for i in (0,1)] if pairs else ['unavailable']*2
                lines.append(f'| {tier} / {size} | {budget} | {len(pairs)} | {means[0]} | {means[1]} | {escapes[0]} | {escapes[1]} |')
    unfinished = [str(r['index']) for r in results if r['state'] in ('missing', 'started', 'interrupted')]
    errors = [str(r['index']) for r in results if r['state'] in ('error', 'upstream_exit')]
    lines += ['', 'Unfinished indices (resume after existing jobs stop): '+(','.join(unfinished) or 'none'),
              'Error/unexpected-exit indices (inspect, do not silently retry): '+(','.join(errors) or 'none')]
    (base/'cohort-report.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, choices=range(len(TASKS)))
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--classification', type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()
    if args.report:
        report(args.output_root, classification_path=args.classification)
        return
    if args.index is None:
        parser.error('--index is required for execution')
    cmd = command(args.index, args.output_root)
    print(shlex.join(cmd), flush=True)
    if args.dry_run:
        return
    if not os.environ.get('SLURM_JOB_ID'):
        parser.error('Inference requires a Slurm allocation')
    # The existing runner verifies model/code/data/settings and exact replay on resume.
    os.chdir(ROOT)
    os.execv(sys.executable, cmd)  # preserve Slurm signals for the actual runner


if __name__ == '__main__':
    main()
