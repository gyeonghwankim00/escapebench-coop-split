"""Run independent solo episodes with one model load on an allocated GPU."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import traceback

from scripts.run_model import HFModel, ROOT, SOLO_INSTRUCTIONS, make_solo_world, run_episode, write_json


def run_suite(datasets, backend, output, max_steps, history_turns, stopped, seed):
    results = []
    for index, dataset in enumerate(datasets):
        if stopped[0]:
            break
        dataset = Path(dataset)
        episode = output / dataset.parent.name
        episode.mkdir()
        print(f'\n=== {dataset.parent.name}: {dataset} ===', flush=True)
        try:
            # Repeatable independent seed per episode, independent of earlier episode length.
            if hasattr(backend, 'torch'):
                backend.torch.manual_seed(seed + index)
                backend.torch.cuda.manual_seed_all(seed + index)
            config = dict(dataset=str(dataset), dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
                          instructions_sha256=hashlib.sha256(SOLO_INSTRUCTIONS.encode()).hexdigest(),
                          mode='solo', seed=seed + index, max_steps=max_steps,
                          history_turns=history_turns, thinking=False,
                          memory_policy='Recent action and feedback only; oldest dropped to fit context.')
            write_json(episode/'config.json', config)
            result = run_episode(make_solo_world(dataset), backend, SOLO_INSTRUCTIONS,
                                 episode, max_steps, history_turns, lambda: stopped[0], solo=True)
            results.append(dict(dataset=str(dataset), **result))
        except Exception as exc:
            traceback.print_exc()
            results.append(dict(dataset=str(dataset), stop_reason='error', error=f'{type(exc).__name__}: {exc}'))
        write_json(output/'suite_summary.json', dict(results=results, planned=len(datasets), interrupted=stopped[0]))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', action='append', type=Path, help='Repeat to select specific problems.')
    parser.add_argument('--model', default='Qwen/Qwen3-8B')
    parser.add_argument('--revision', default='main')
    parser.add_argument('--quantization', choices=['4bit', 'none'], default='4bit')
    parser.add_argument('--max-steps', type=int, default=150)
    parser.add_argument('--history-turns', type=int, default=30)
    parser.add_argument('--context-tokens', type=int, default=8192)
    parser.add_argument('--max-new-tokens', type=int, default=192)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.max_steps < 1 or args.history_turns < 0 or not 0 < args.max_new_tokens < args.context_tokens:
        parser.error('Invalid turn or token budget.')
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Allocate a GPU with Slurm first.')
    datasets = args.dataset or sorted((ROOT/'data/pilot').glob('*/environment.json'))
    if not datasets or len({p.parent.name for p in datasets}) != len(datasets):
        parser.error('Select at least one dataset with unique parent folder names.')
    output = args.output or ROOT/'outputs'/('solo-suite-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True, exist_ok=False)
    stopped = [False]
    def handle_signal(signum, frame):
        stopped[0] = True
        print(f'Received signal {signum}; stopping after current turn.', flush=True)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGUSR1, handle_signal)
    write_json(output/'suite_config.json', {**{k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items() if k != 'dataset'},
                                           'datasets': [str(p) for p in datasets], 'output': str(output)})
    print(f'Logs: {output}', flush=True)
    try:
        backend = HFModel(args)
    except Exception as exc:
        write_json(output/'suite_summary.json', dict(results=[], planned=len(datasets),
                   stop_reason='model_load_error', error=f'{type(exc).__name__}: {exc}'))
        raise
    write_json(output/'model.json', backend.metadata)
    results = run_suite(datasets, backend, output, args.max_steps, args.history_turns, stopped, args.seed)
    print(json.dumps(dict(completed=len(results), planned=len(datasets), interrupted=stopped[0]), indent=2), flush=True)
    if stopped[0] or any(x['stop_reason'] == 'error' for x in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
