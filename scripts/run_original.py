"""Run the pinned EscapeBench BaseAgent protocol with a local HF model."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from scripts.original_escape import Agent, ROOT, UPSTREAM, initial_messages, verify_upstream
from scripts.run_model import HFModel
from scripts.run_experiment import local_model_identity
from scripts.greedy_generation import GENERATION_VERSION, generate_greedy

DEFAULT_GAMES = ['game1-1-easy', 'game1-3-easy', 'game2-1-easy', 'game1-2-easy',
                 'game2-2-easy', 'game2-4-easy', 'game2-5-easy', 'game3-2-easy']


def write_json(path, obj):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def load_trace(path):
    if not path.exists():
        return []
    # A killed write can leave a partial final line. Preserve it for diagnosis.
    raw = path.read_bytes()
    complete = raw.rfind(b'\n') + 1
    rows = [json.loads(line) for line in raw[:complete].splitlines()]
    if complete < len(raw):
        path.with_suffix('.partial').write_bytes(raw[complete:])
        path.write_bytes(raw[:complete])
    return rows


def run_game(game, backend, output, stop=lambda: False, max_steps=4000):
    output.mkdir(parents=True, exist_ok=True)
    previous = load_trace(output/'turns.jsonl')
    started = time.monotonic()
    pending = None
    recorded = 0
    reason, error, terminal = 'interrupted', None, None
    def call(step, messages):
        nonlocal pending
        if step < len(previous):
            generation = previous[step]['generation']
            if generation is None or generation['messages'] != messages:
                raise ValueError(f'Resume prompt mismatch at step {step}')
            return generation
        if stop():
            raise InterruptedError('Infrastructure time/signal limit; no action executed')
        pending = backend.complete(messages, stop)
        if stop():
            raise InterruptedError('Generation interrupted; no action executed')
        return pending
    with tempfile.TemporaryDirectory() as scratch, (output/'turns.jsonl').open('a') as log:
        agent = Agent(game, scratch, call, max_steps)
        iterator = agent.iterate('local-hf', game)
        try:
            while True:
                # Reconstruct completed states before considering the next step.
                if recorded >= len(previous) and stop():
                    break
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        next(iterator)
                except StopIteration as result:
                    terminal = result.value
                if len(agent.history) > recorded:
                    record = agent.record()
                    if recorded < len(previous):
                        if record != previous[recorded]:
                            raise ValueError(f'Resume state mismatch at step {recorded}')
                    else:
                        log.write(json.dumps(record, ensure_ascii=False) + '\n')
                        log.flush()
                        print(f'{game} step={recorded+1} progress={record["upstream"]["tracking"]["progress"]}% '
                              f'hints={record["hints_used"]} forced={record["forced_action"]} '
                              f'{record["upstream"]["action_answer"]}', flush=True)
                    recorded += 1
                    pending = None
                if terminal is not None:
                    reason = 'success' if terminal[0] else ('step_budget' if recorded >= max_steps else 'upstream_exit')
                    break
        except InterruptedError:
            reason = 'interrupted'
        except Exception as exc:
            reason, error = 'error', f'{type(exc).__name__}: {exc}'
        finally:
            iterator.close()
            if pending:
                write_json(output/'interrupted_generation.json', pending)
            # Only committed, reproducible records count; never a partly executed step.
            rows = load_trace(output/'turns.jsonl')
            last = rows[-1] if rows else None
            progress = last['upstream']['tracking']['progress'] if last else 0
            first_hint = next((r['first_hint_progress'] for r in rows if r['first_hint_progress'] is not None), None)
            summary = dict(game=game, stop_reason=reason, error=error, success=reason == 'success',
                steps=len(rows), progress_percent=progress, hints_used=last['hints_used'] if last else 0,
                forced_actions=sum(r['forced_action'] for r in rows),
                early_exit_progress_percent=first_hint if first_hint is not None else progress,
                model_calls=sum(r['generation'] is not None for r in rows),
                input_tokens=sum(r['generation'].get('input_tokens', 0) for r in rows if r['generation']),
                output_tokens=sum(r['generation'].get('output_tokens', 0) for r in rows if r['generation']),
                generation_seconds=sum(r['generation'].get('seconds', 0) for r in rows if r['generation']),
                last_attempt_wall_seconds=time.monotonic()-started)
            write_json(output/'summary.json', summary)
    return summary


class OriginalHF:
    def __init__(self, args):
        self.backend = HFModel(args)
        self.metadata = self.backend.metadata

    def complete(self, messages, stop):
        from transformers import StoppingCriteria, StoppingCriteriaList
        backend = self.backend
        tokenizer, torch = backend.tokenizer, backend.torch
        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return bool(stop())
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
        inputs = tokenizer(text, return_tensors='pt', add_special_tokens=False)
        length = inputs.input_ids.shape[-1]
        if length + 256 > backend.context_limit:
            raise ValueError(f'Context overflow: {length}+256 > {backend.context_limit}; prompt not truncated')
        inputs = inputs.to(backend.model.device)
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            result, effective = generate_greedy(backend.model, inputs, tokenizer,
                                               StoppingCriteriaList([Stop()]))
        torch.cuda.synchronize()
        tokens = result[0, length:]
        return dict(raw=tokenizer.decode(tokens, skip_special_tokens=True), messages=messages,
                    rendered_prompt=text, input_tokens=length, output_tokens=len(tokens),
                    seconds=time.perf_counter()-start, output_limit_hit=len(tokens) >= 256,
                    effective_generation=effective)


def diagnostics(output):
    import sys
    import torch
    try:
        smi = subprocess.run(['nvidia-smi'], capture_output=True, text=True, timeout=20)
        smi_result = dict(returncode=smi.returncode, stdout=smi.stdout, stderr=smi.stderr)
    except Exception as exc:
        smi_result = {'error': str(exc)}
    result = dict(python=sys.executable, node=os.uname().nodename, torch=torch.__version__,
                  cuda_runtime=torch.version.cuda,
                  environment={k: os.environ.get(k) for k in ('SLURM_JOB_ID','SLURM_STEP_ID',
                      'SLURM_JOB_GPUS','SLURM_STEP_GPUS','CUDA_VISIBLE_DEVICES')}, nvidia_smi=smi_result)
    try:
        torch.cuda.init()
        value = torch.ones(1, device='cuda') + 1
        torch.cuda.synchronize()
        result.update(gpu=torch.cuda.get_device_name(0), cuda_test=float(value.item()))
    except Exception as exc:
        result['cuda_error'] = f'{type(exc).__name__}: {exc}'
    write_json(output/f'gpu-check-{time.time_ns()}.json', result)
    print(json.dumps(result, indent=2), flush=True)
    if 'cuda_error' in result:
        raise RuntimeError(result['cuda_error'])


def report(output, games):
    rows = []
    lines = ['# Original BaseAgent protocol', '',
             '| Game | Status | Steps | Hints | Forced actions | Pre-help progress | Final progress |',
             '|---|---|---:|---:|---:|---:|---:|']
    for game in games:
        p = output/game/'summary.json'
        if not p.exists():
            lines.append(f'| {game} | pending | — | — | — | — | — |')
            continue
        r = json.loads(p.read_text()); rows.append(r)
        lines.append(f'| {game} | {r["stop_reason"]} | {r["steps"]} | {r["hints_used"]} | '
                     f'{r["forced_actions"]} | {r["early_exit_progress_percent"]}% | {r["progress_percent"]}% |')
    write_json(output/'results.json', rows)
    (output/'report.md').write_text('\n'.join(lines)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=str(ROOT/'models/Qwen3-14B'))
    parser.add_argument('--revision', default='main')
    parser.add_argument('--quantization', choices=['4bit', 'none'], default='4bit')
    parser.add_argument('--context-tokens', type=int, default=2400)
    parser.add_argument('--games', nargs='+', default=DEFAULT_GAMES)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--wall-seconds', type=int, default=36000)
    args = parser.parse_args()
    if args.resume and (args.output or args.dry_run):
        parser.error('--resume cannot be combined with --output/--dry-run')
    if args.context_tokens <= 256 or args.wall_seconds <= 0:
        parser.error('Invalid context/time limit')
    valid_games = {p.stem for p in (UPSTREAM/'data').glob('game*.yaml')}
    if not args.games or len(set(args.games)) != len(args.games) or not set(args.games) <= valid_games:
        parser.error('Choose distinct upstream game names')
    if not args.dry_run and not os.environ.get('SLURM_JOB_ID'):
        parser.error('Inference requires a Slurm GPU allocation; use --dry-run locally')
    output = args.resume or args.output or ROOT/'outputs'/('original-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    manifest = dict(protocol='escapebench-baseagent-original-v2', generation_version=GENERATION_VERSION,
        upstream=verify_upstream(),
        games=args.games, model=args.model, revision=args.revision, quantization=args.quantization,
        context_tokens=args.context_tokens, local_model_identity=local_model_identity(args.model),
        settings=dict(memory=10, stuck_steps=50, stuck_behavior='help', max_steps=4000,
                      use_cot=True, native_thinking=False, do_sample=False, max_new_tokens=256, seed=42),
        differences=['HF/SDPA instead of vLLM; default NF4 instead of BF16',
                     'Qwen3 native thinking disabled; original short Thought/Action prompt unchanged',
                     'Selected games only, not automatically all 36',
                     'Infra interruption resumes by exact deterministic replay; no 30-minute episode cutoff',
                     'Upstream call_LLM debug stub and API secrets setup bypassed'],
        code_hashes={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                     ('scripts/original_escape.py','scripts/run_original.py','scripts/run_model.py',
                      'scripts/run_experiment.py','scripts/greedy_generation.py')})
    if args.resume:
        if (output/'preview.json').exists() or json.loads((output/'experiment.json').read_text()) != manifest:
            raise SystemExit('Cannot resume: preview, model, code, dataset or configuration mismatch')
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output/'experiment.json', manifest)
    print(f'Original protocol output: {output}', flush=True)
    if args.dry_run:
        for game in args.games:
            with contextlib.redirect_stdout(io.StringIO()):
                messages = initial_messages(game)
            write_json(output/f'{game}-prompt.json', messages)
        write_json(output/'preview.json', dict(model_loaded=False, games=args.games))
        return
    interrupted = [False]
    for sig in (signal.SIGTERM, signal.SIGUSR1, signal.SIGINT):
        signal.signal(sig, lambda *_: interrupted.__setitem__(0, True))
    start = time.monotonic()
    def stop(): return interrupted[0] or time.monotonic()-start >= args.wall_seconds
    pending = []
    for game in args.games:
        p = output/game/'summary.json'
        if not p.exists() or json.loads(p.read_text())['stop_reason'] not in ('success','step_budget','upstream_exit'):
            pending.append(game)
    if not pending:
        report(output, args.games)
        return
    args.seed = 42
    args.max_new_tokens = 256
    try:
        diagnostics(output)
        if stop(): raise InterruptedError('Stopped before model loading')
        load_start = time.monotonic()
        backend = OriginalHF(args)
        backend.metadata['load_seconds'] = time.monotonic()-load_start
        write_json(output/f'model-{time.time_ns()}.json', backend.metadata)
    except Exception as exc:
        write_json(output/'load_error.json', dict(error=f'{type(exc).__name__}: {exc}'))
        raise
    for game in pending:
        if stop(): break
        result = run_game(game, backend, output/game, stop)
        report(output, args.games)
        if result['stop_reason'] in ('error','interrupted'):
            raise SystemExit(1)
    report(output, args.games)
    if any(not (output/g/'summary.json').exists() or json.loads((output/g/'summary.json').read_text())['stop_reason']
           in ('error','interrupted') for g in args.games):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
