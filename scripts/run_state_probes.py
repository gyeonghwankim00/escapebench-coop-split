"""Matched next-action probes, 4 states x 3 interfaces, batch size one.

Replay the recorded actions without model calls, validate every state and the
target prompt, then ask one new action. This is NOT a full-game success metric.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import time

from scripts.coop_original import CoopAgent
from scripts.action_interface import INTERFACES, present
from scripts.original_escape import ROOT
from scripts.run_original import write_json, diagnostics


def probe(case, interface, request):
    target, rows = case['step'], case['rows']
    def call(step, messages):
        expected = rows[step]['generation']['messages']
        if present(messages, 'coop', case['source_interface']) != expected:
            raise ValueError(f'Original prompt mismatch at {case["id"]}/{step}')
        if step < target:
            return rows[step]['generation']
        return request(present(messages, 'coop', interface))

    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        agent = CoopAgent(case['game'], tmp, call, max_steps=target+1, roles=case['roles'])
        iterator = agent.iterate('probe', case['game'])
        try:
            for step in range(target+1):
                try:
                    next(iterator)
                except StopIteration:
                    pass
                row = agent.record()
                if step < target:
                    for key in ('upstream', 'bags', 'evaluation', 'role', 'inbox', 'helper_active'):
                        if row[key] != rows[step][key]:
                            raise ValueError(f'State replay mismatch: {case["id"]}/{step}/{key}')
                else:
                    # Actor, observed state and inventory must be identical BEFORE the new action.
                    for key in ('evaluation', 'role', 'inbox', 'helper_active'):
                        if row[key] != rows[step][key]:
                            raise ValueError(f'Target state mismatch: {key}')
                    return row
        finally:
            iterator.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--wall-seconds', type=int, default=36000)
    args = parser.parse_args()
    if not args.dry_run and not os.environ.get('SLURM_JOB_ID'):
        parser.error('Use a Slurm GPU allocation')
    from scripts.run_matrix import BatchHF
    from scripts.run_experiment import local_model_identity
    folder = ROOT/'data/state_probes'
    cases = [json.loads(p.read_text()) for p in sorted(folder.glob('*.json')) if p.name != 'manifest.json']
    sources = ['scripts/run_state_probes.py', 'scripts/action_interface.py', 'scripts/coop_original.py',
               'scripts/original_escape.py', 'scripts/run_matrix.py', 'scripts/run_model.py', 'scripts/greedy_generation.py']
    manifest = dict(model=args.model, model_identity=local_model_identity(args.model), dry_run=args.dry_run,
        settings=dict(interfaces=INTERFACES, context=4096, output=256, batch=1, quantization='4bit', thinking=False),
        hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
        case_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.json')})
    args.output.mkdir(parents=True, exist_ok=True)
    config = args.output/'experiment.json'
    manifest = json.loads(json.dumps(manifest))
    if config.exists() and json.loads(config.read_text()) != manifest:
        raise SystemExit('Changed model/code/cases: choose a new output directory')
    write_json(config, manifest)
    stopped = [False]
    for sig in (signal.SIGTERM, signal.SIGUSR1, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.__setitem__(0, True))
    start = time.monotonic()
    def stop(): return stopped[0] or time.monotonic()-start >= args.wall_seconds
    backend = None
    try:
        if not args.dry_run:
            diagnostics(args.output)
            args.revision, args.quantization, args.seed, args.context_tokens = 'main', '4bit', 42, 4096
            backend = BatchHF(args)
            write_json(args.output/'model.json', backend.metadata)
        def request(messages):
            if stop(): raise InterruptedError('Probe time/signal limit')
            if args.dry_run:
                return dict(raw='Action: click(nonexistent)', messages=messages)
            result = backend.complete_batch([messages], stop)[0]
            if isinstance(result, Exception): raise result
            return result
        for case in cases:
            for interface in INTERFACES:
                out = args.output/f'{case["id"]}-{interface}.json'
                if out.exists(): continue
                row = probe(case, interface, request)
                write_json(out, dict(case=case['id'], interface=interface, record=row))
                print(case['id'], interface, row['upstream']['action_answer'], flush=True)
    except Exception as exc:
        write_json(args.output/'error.json', dict(error=f'{type(exc).__name__}: {exc}'))
        raise
    finally:
        if backend:
            write_json(args.output/'timing.json', dict(seconds=time.monotonic()-start,
                peak_gpu_bytes=backend.backend.torch.cuda.max_memory_allocated()))
    lines = ['# Matched next-action probes', '',
             'Selected failure states; single decisions, not success rates or a representative sample.', '',
             '| State | Interface | Action | Feedback |', '|---|---|---|---|']
    for case in cases:
        for interface in INTERFACES:
            row = json.loads((args.output/f'{case["id"]}-{interface}.json').read_text())['record']['upstream']
            cells = [case['id'], interface, row['action_answer'], row['response']]
            lines.append('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in cells)+' |')
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    main()
