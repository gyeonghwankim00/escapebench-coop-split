"""Broad diagnostic: Qwen3-14B and Phi-4, 12 easy games, Solo/Peer, 500 team actions."""
import argparse
import os
from pathlib import Path
import pwd
import shlex
import sys
from scripts.run_cohort import GAMES, ROOT, report
from scripts.run_matrix import PROTOCOL
from scripts.cohort_policy import load_policy, DEFAULT_POLICY

MODELS = {'qwen14': 'Qwen3-14B', 'phi14': 'phi-4'}
EPISODES = [(condition, game) for game in GAMES for condition in ('solo', 'coop')]
TASKS = [(key, condition, game) for key in MODELS for condition, game in EPISODES]
PREFIX = 'nightly-v6'


def lab_root():
    return Path('/shared/s2/lab04')/pwd.getpwuid(os.getuid()).pw_name/'escape-lab'


def command(key, index, out):
    condition, game = EPISODES[index]
    model = (ROOT if key == 'qwen14' else lab_root())/'models'/MODELS[key]
    return [sys.executable, '-m', 'scripts.run_matrix', '--model', str(model),
            '--output', str(out/f'{PREFIX}-{key}-{condition}-{game}'),
            '--conditions', condition, '--games', game, '--interface', 'original',
            '--quantization', '4bit', '--max-batch', '1', '--max-steps', '500',
            '--context-tokens', '8192', '--wall-seconds', '40200']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=MODELS)
    p.add_argument('--index', type=int, choices=range(24))
    p.add_argument('--output-root', type=Path)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--report', action='store_true')
    p.add_argument('--classification', type=Path, default=DEFAULT_POLICY)
    args = p.parse_args()
    out = args.output_root or lab_root()/'outputs/nightly-v6'
    if args.report:
        report(out, tasks=TASKS, max_steps=500, prefix=PREFIX, model_names=MODELS, budgets=(50,200,500), context_tokens=8192, required_protocol=PROTOCOL, classification_path=args.classification)
        print('Report indices 0–23 = qwen14; 24–47 = phi14 (subtract 24 for phi array index).')
        return
    if args.model is None or args.index is None:
        p.error('--model and --index are required')
    policy,_=load_policy(args.classification)
    game=EPISODES[args.index][1]
    if policy['games'][game]['tier']=='excluded':
        print(f'Skipping excluded source defect: {game}')
        return
    cmd = command(args.model, args.index, out)
    print(shlex.join(cmd), flush=True)
    if args.dry_run:
        return
    if not os.environ.get('SLURM_JOB_ID'):
        p.error('Use a Slurm GPU allocation')
    os.chdir(ROOT)
    os.execv(sys.executable, cmd)


if __name__ == '__main__':
    main()
