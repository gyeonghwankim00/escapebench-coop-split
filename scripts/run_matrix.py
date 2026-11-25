"""Solo vs 2-agent matrix on the original EscapeBench engine, batched on one GPU.

Every (condition, game) episode runs in its own thread. The engine keeps state
in module globals, so engine work is serialized by ENGINE and each episode's
globals are swapped in/out around it. The lock is released only while an
episode waits for the model, and the main thread generates one batch whenever
every live episode is waiting. Prompts, parsing and engine behavior are those
of scripts/original_escape.py (solo) and scripts/coop_original.py (coop).

Output layout:  <output>/experiment.json, report.md, results.json,
                <output>/<condition>/<game>/turns.jsonl, summary.json
Re-running with the same --output resumes: finished episodes are skipped and
interrupted ones are replayed from saved responses without model calls.
Exit status: 0 all finished, 75 interrupted (resubmit to resume), 1 error.
"""
import argparse
import contextlib
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time

from scripts.original_escape import Agent, ROOT, UPSTREAM, gv, verify_upstream
from scripts.coop_original import CoopAgent, ROLES_DIR
from scripts.run_original import load_trace, write_json
from scripts.greedy_generation import GENERATION_VERSION, generate_greedy
from scripts.action_interface import INTERFACES, present

PROTOCOL = 'escapebench-adaptive-v7'
CONDITIONS = ('solo', 'coop', 'original_solo')
# All 12 upstream base games, easy variant. Coop splits: data/roles/<game>.json.
ALL_GAMES = ['game1-1-easy', 'game1-2-easy', 'game1-3-easy', 'game1-4-easy', 'game1-5-easy',
             'game2-1-easy', 'game2-2-easy', 'game2-3-easy', 'game2-4-easy', 'game2-5-easy',
             'game3-1-easy', 'game3-2-easy']
FINAL = ('success', 'step_budget', 'decision_budget', 'upstream_exit')
EXIT_RESUMABLE = 75
# Files a Solo episode depends on. The coop layer, role files and this runner's
# bookkeeping may change without affecting a Solo run. Bump GENERATION_VERSION
# whenever BatchHF or run_episode changes what a Solo episode would produce.
SOLO_FILES = ('scripts/original_escape.py', 'scripts/run_original.py', 'scripts/run_model.py',
              'scripts/greedy_generation.py', 'scripts/action_interface.py')


def resume_key(manifest):
    """The part of a manifest that must be unchanged to continue a run."""
    key = {k: manifest.get(k) for k in ('upstream_commit', 'conditions', 'games', 'model', 'revision',
                                        'quantization', 'local_model_identity', 'dry_run', 'settings')}
    key['generation_version'] = manifest.get('generation_version', 1)
    if manifest['conditions'] == ['original_solo']:
        key['code'] = {f: manifest['code_hashes'].get(f) for f in SOLO_FILES}
    else:
        key.update(code=manifest['code_hashes'], roles=manifest['role_hashes'], protocol=manifest['protocol'])
    return key
ENGINE = threading.Lock()
PRINT = threading.Lock()
REAL_STDOUT = None  # set by main() before the engine's own prints are silenced


def say(*parts):
    with PRINT:
        print(*parts, file=REAL_STDOUT or sys.stdout, flush=True)


def save_globals():
    return gv.count, gv.bag, gv.completed_acts


def load_globals(state):
    if state is not None:
        gv.count, gv.bag, gv.completed_acts = state


def make_agent(condition, game, scratch, call, max_steps):
    if condition == 'original_solo':
        return Agent(game, scratch, call, max_steps)
    if condition == 'solo':
        from scripts.adaptive_escape import AdaptiveSolo
        return AdaptiveSolo(game, scratch, call, max_steps)
    if condition == 'coop':
        from scripts.adaptive_escape import AdaptivePeer
        return AdaptivePeer(game, scratch, call, max_steps)
    raise ValueError(condition)


class Interrupted(Exception):
    pass


class Batcher:
    """Collects one request per live episode, then generates them together."""

    def __init__(self, backend, stop, max_batch):
        self.backend, self.stop, self.max_batch = backend, stop, max_batch
        self.cv = threading.Condition()
        self.pending, self.alive = [], 0
        self.batches, self.batch_seconds, self.batch_sizes = 0, 0.0, []

    def register(self):
        with self.cv:
            self.alive += 1

    def unregister(self):
        with self.cv:
            self.alive -= 1
            self.cv.notify_all()

    def submit(self, messages):
        request = dict(messages=messages, done=False)
        with self.cv:
            self.pending.append(request)
            self.cv.notify_all()
            while not request['done']:
                self.cv.wait()
        if 'error' in request:
            raise request['error']
        return request['result']

    def _finish(self, batch, results):
        with self.cv:
            for request, result in zip(batch, results):
                if isinstance(result, BaseException):
                    request['error'] = result
                else:
                    request['result'] = result
                request['done'] = True
            self.cv.notify_all()

    def serve(self, report_every=50):
        while True:
            with self.cv:
                while self.alive and len(self.pending) < self.alive and not (self.stop() and self.pending):
                    self.cv.wait(timeout=1.0)
                if not self.alive:
                    return
                batch, self.pending = self.pending, []
            if self.stop():
                self._finish(batch, [Interrupted('Infrastructure time/signal limit')] * len(batch))
                continue
            started = time.perf_counter()
            try:
                results = []
                for i in range(0, len(batch), self.max_batch):
                    chunk = batch[i:i+self.max_batch]
                    results += self.backend.complete_batch([r['messages'] for r in chunk], self.stop)
            except Interrupted as exc:
                results = [exc] * len(batch)
            except Exception as exc:  # e.g. CUDA OOM: fail these episodes, keep the job alive
                results = [RuntimeError(f'Generation failed: {type(exc).__name__}: {exc}')] * len(batch)
            elapsed = time.perf_counter() - started
            self.batches += 1
            self.batch_seconds += elapsed
            self.batch_sizes.append(len(batch))
            if self.batches % report_every == 0:
                say(f'[batch {self.batches}] size={len(batch)} {elapsed:.2f}s '
                    f'mean={self.batch_seconds/self.batches:.2f}s/batch')
            self._finish(batch, results)


def summarize(condition, game, rows, reason, error, wall):
    last = rows[-1] if rows else None
    progress = last['upstream']['tracking']['progress'] if last else 0
    first_hint = next((r['first_hint_progress'] for r in rows if r['first_hint_progress'] is not None), None)
    gens = [r['generation'] for r in rows if r['generation']]
    answers = [r['upstream']['action_answer'] for r in rows]
    ok = [r['upstream']['response'].startswith('Action executed successfully') for r in rows]
    summary = dict(
        environment_actions=sum(r.get('action_cost',1) for r in rows),
        yield_decisions=sum(r.get('action_cost',1)==0 for r in rows),
        condition=condition, game=game, stop_reason=reason, error=error, success=reason == 'success',
        steps=len(rows), progress_percent=progress, hints_used=last['hints_used'] if last else 0,
        forced_actions=sum(r['forced_action'] for r in rows),
        pre_help_progress_percent=first_hint if first_hint is not None else progress,
        first_hint_step=next((i for i, r in enumerate(rows) if r['helper_active']), None),
        model_calls=len(gens),
        no_action_outputs=sum(a == 'No action' for a in answers),
        output_limit_hits=sum(bool(g.get('output_limit_hit')) for g in gens),
        input_tokens=sum(g.get('input_tokens', 0) for g in gens),
        output_tokens=sum(g.get('output_tokens', 0) for g in gens),
        last_attempt_wall_seconds=wall)
    if condition in ('solo', 'coop'):
        cut = summary['first_hint_step']
        prefix = rows[:cut] if cut is not None else rows
        summary.update(
            inventory_mode=last.get('inventory_mode', 'separate') if last else None,
            environment_actions_by_role={x:sum(r.get('action_cost',1) for r in rows if r['role']==x) for x in 'AB'},
            steps_by_role={x: sum(r['role'] == x for r in rows) for x in 'AB'},
            messages_sent=sum(a.startswith('send(') and k for a, k in zip(answers, ok)),
            gives=sum(a.startswith('give(') and k for a, k in zip(answers, ok)),
            gives_before_first_hint=sum(r['upstream']['action_answer'].startswith('give(')
                                        and r['upstream']['response'].startswith('Action executed')
                                        for r in prefix),
            messages_before_first_hint=sum(r['upstream']['action_answer'].startswith('send(')
                                           and r['upstream']['response'].startswith('Action executed')
                                           for r in prefix),
            give_hints=sum(1 for i, r in enumerate(rows) if r['hint'] and r['hint']['kind'] == 'give'
                           and (i == 0 or rows[i-1]['hint'] != r['hint'])),
            autonomous_prefix_steps=len(prefix),
            give_attempts_before_first_hint=sum(r['upstream']['action_answer'].startswith('give(') for r in prefix),
            give_failures_before_first_hint=sum(r['upstream']['action_answer'].startswith('give(')
                and not r['upstream']['response'].startswith('Action executed successfully') for r in prefix),
            move_failures_before_first_hint=sum(r['upstream']['action_answer'].startswith('move(')
                and r['upstream']['response'].startswith('Error') for r in prefix),
            distinct_scenes_by_role={r: len({x['evaluation']['scene'] for x in rows if x['role']==r and x.get('evaluation')}) for r in 'AB'},
            non_helper_mode_steps=sum(not r['helper_active'] for r in rows))
    return summary


def run_episode(condition, game, output, request, stop, max_steps, lock=ENGINE, interface='original', help_policy='none', max_decisions=None):
    """Run or resume one episode. `request(messages)` returns a generation dict."""
    output.mkdir(parents=True, exist_ok=True)
    previous = load_trace(output/'turns.jsonl')
    started = time.monotonic()
    state = [None]
    reason, error, terminal, recorded = 'interrupted', None, None, 0

    def call(step, messages):
        messages = present(messages, condition, interface)
        if step < len(previous):
            generation = previous[step]['generation']
            if generation is None or generation['messages'] != messages:
                raise ValueError(f'Resume prompt mismatch at step {step}')
            return generation
        if stop():
            raise Interrupted('Infrastructure time/signal limit; no action executed')
        saved = save_globals()
        lock.release()
        try:
            return request(messages)
        finally:
            lock.acquire()
            load_globals(saved)

    with tempfile.TemporaryDirectory() as scratch, (output/'turns.jsonl').open('a') as log:
        with lock:
            agent = make_agent(condition, game, scratch, call, max_steps)
            if condition != 'original_solo':
                agent.help_policy = help_policy
                agent.max_decisions = max_decisions or max_steps * 2
            iterator = agent.iterate('local-hf', game)
        try:
            while True:
                if recorded >= len(previous) and stop():
                    break
                with lock:
                    load_globals(state[0])
                    try:
                        next(iterator)
                    except StopIteration as result:
                        terminal = result.value
                    state[0] = save_globals()
                    record = agent.record() if len(agent.history) > recorded else None
                if record is not None:
                    if recorded < len(previous):
                        if json.loads(json.dumps(record)) != previous[recorded]:
                            raise ValueError(f'Resume state mismatch at step {recorded}')
                    else:
                        log.write(json.dumps(record, ensure_ascii=False) + '\n')
                        log.flush()
                        if recorded % 100 == 0 or terminal is not None:
                            say(f'{condition}/{game} step={recorded} '
                                f'progress={record["upstream"]["tracking"]["progress"]}% '
                                f'hints={record["hints_used"]}')
                    recorded += 1
                if terminal is not None:
                    reason = 'success' if terminal[0] else (getattr(agent, 'budget_stop', None) or ('step_budget' if recorded >= max_steps else 'upstream_exit'))
                    break
        except Interrupted:
            reason = 'interrupted'
        except Exception as exc:
            reason, error = 'error', f'{type(exc).__name__}: {exc}'
        finally:
            with lock:
                load_globals(state[0])
                iterator.close()
    rows = load_trace(output/'turns.jsonl')
    summary = summarize(condition, game, rows, reason, error, time.monotonic() - started)
    write_json(output/'summary.json', summary)
    if condition in ('solo', 'coop'):
        from scripts.analyze_collaboration import analyze, write_analysis
        frozen = output.parent.parent/'evaluation_inputs'
        spec_path, clues_path = frozen/'roles'/f'{game}.json', frozen/'clues.json'
        spec = json.loads(spec_path.read_text()) if spec_path.exists() else None
        clues = json.loads(clues_path.read_text())['games'][game] if clues_path.exists() else None
        write_analysis(output, analyze(game, rows, spec, clues))
    say(f'{condition}/{game} -> {reason} steps={summary["steps"]} hints={summary["hints_used"]} '
        f'pre-help={summary["pre_help_progress_percent"]}% final={summary["progress_percent"]}%'
        + (f' error={error}' if error else ''))
    return summary


def run_all(episodes, backend, stop, max_steps, max_batch, output, interface='original', help_policy='none', max_decisions=None):
    """episodes: list of (condition, game). Runs them concurrently; returns summaries."""
    batcher = Batcher(backend, stop, max_batch)
    results = {}

    def worker(condition, game):
        try:
            results[condition, game] = run_episode(condition, game, output/condition/game,
                                                   batcher.submit, stop, max_steps, interface=interface, help_policy=help_policy, max_decisions=max_decisions)
        except Exception as exc:  # never leave the batcher waiting on a dead thread
            results[condition, game] = dict(condition=condition, game=game, stop_reason='error',
                                            error=f'{type(exc).__name__}: {exc}')
        finally:
            batcher.unregister()

    threads = []
    for condition, game in episodes:
        batcher.register()
        thread = threading.Thread(target=worker, args=(condition, game), daemon=True)
        threads.append(thread)
    for thread in threads:
        thread.start()
    batcher.serve()
    for thread in threads:
        thread.join()
    timing = dict(batches=batcher.batches, batch_seconds=batcher.batch_seconds,
                  mean_batch_size=(sum(batcher.batch_sizes)/len(batcher.batch_sizes)) if batcher.batch_sizes else 0)
    return results, timing


class BatchHF:
    """Greedy batched generation; same settings as run_original.OriginalHF."""
    MAX_NEW = 256

    def __init__(self, args):
        from scripts.run_model import HFModel
        self.backend = HFModel(args)
        self.metadata = self.backend.metadata
        tok = self.backend.tokenizer
        tok.padding_side = 'left'
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        eos = self.backend.model.generation_config.eos_token_id
        self.eos = set(eos if isinstance(eos, (list, tuple)) else [eos])

    def complete_batch(self, batch, stop):
        from transformers import StoppingCriteria, StoppingCriteriaList
        tok, model, torch = self.backend.tokenizer, self.backend.model, self.backend.torch
        limit = self.backend.context_limit

        class Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.full((input_ids.shape[0],), bool(stop()), dtype=torch.bool,
                                  device=input_ids.device)

        texts = [tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False) for m in batch]
        lengths = [len(tok(t, add_special_tokens=False).input_ids) for t in texts]
        results = [None] * len(batch)
        ok = []
        for i, n in enumerate(lengths):
            if n + self.MAX_NEW > limit:
                results[i] = ValueError(f'Context overflow: {n}+{self.MAX_NEW} > {limit}; prompt not truncated')
            else:
                ok.append(i)
        if not ok:
            return results
        enc = tok([texts[i] for i in ok], return_tensors='pt', padding=True,
                  add_special_tokens=False).to(model.device)
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            out, effective = generate_greedy(model, enc, tok, StoppingCriteriaList([Stop()]))
        torch.cuda.synchronize()
        seconds = time.perf_counter() - start
        if stop():
            raise Interrupted('Generation interrupted; no action executed')
        new = out[:, enc['input_ids'].shape[1]:].tolist()
        for row, i in enumerate(ok):
            tokens = new[row]
            end = next((j + 1 for j, t in enumerate(tokens) if t in self.eos), None)
            kept = tokens[:end] if end else tokens
            results[i] = dict(raw=tok.decode(kept, skip_special_tokens=True), messages=batch[i],
                              prompt_sha256=hashlib.sha256(texts[i].encode()).hexdigest(),
                              input_tokens=lengths[i], output_tokens=len(kept),
                              output_limit_hit=end is None and len(kept) >= self.MAX_NEW,
                              seconds=seconds, batch_size=len(ok), effective_generation=effective)
        return results


class PreviewBackend:
    def complete_batch(self, batch, stop):
        return [dict(raw='Thought: Preview only.\nAction: click(nonexistent)', messages=m,
                     input_tokens=0, output_tokens=0, seconds=0.0) for m in batch]


def report(output, episodes):
    rows, lines = [], ['# Solo vs 2-agent (original engine)', '',
        '| Condition | Game | Status | Steps | Hints | Forced | Pre-help progress | Final progress | Msgs | Gives |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
    manifest = output/'experiment.json'
    if manifest.exists():
        interface = json.loads(manifest.read_text())['settings'].get('interface', 'original')
        lines[0] += f' — interface: {interface}'
    for condition, game in episodes:
        p = output/condition/game/'summary.json'
        if not p.exists():
            lines.append(f'| {condition} | {game} | pending | | | | | | | |')
            continue
        r = json.loads(p.read_text())
        rows.append(r)
        lines.append(f'| {condition} | {game} | {r["stop_reason"]} | {r["steps"]} | {r["hints_used"]} | '
                     f'{r["forced_actions"]} | {r["pre_help_progress_percent"]}% | {r["progress_percent"]}% | '
                     f'{r.get("messages_sent", "")} | {r.get("gives", "")} |')
    write_json(output/'results.json', rows)
    (output/'report.md').write_text('\n'.join(lines) + '\n')
    return rows


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', default=str(ROOT/'models/Qwen3-8B'))
    parser.add_argument('--revision', default='main')
    parser.add_argument('--quantization', choices=['4bit', 'none'], default='4bit')
    parser.add_argument('--conditions', nargs='+', choices=CONDITIONS, default=['solo', 'coop'])
    parser.add_argument('--games', nargs='+', default=ALL_GAMES)
    parser.add_argument('--max-steps', type=int, default=4000)
    parser.add_argument('--max-decisions', type=int, help='Default: twice the environment action budget')
    parser.add_argument('--help-policy', choices=['none','original'], default='none')
    parser.add_argument('--context-tokens', type=int, default=4096)
    parser.add_argument('--max-batch', type=int, default=16)
    parser.add_argument('--wall-seconds', type=int, default=40200)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interface', choices=INTERFACES, default='original')
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Write first prompts locally; no model.')
    args = parser.parse_args()
    if len(set(args.games)) != len(args.games) or any(not (ROLES_DIR/f'{g}.json').exists() for g in args.games):
        parser.error('Games must be distinct and have data/roles/<game>.json')
    if (args.max_decisions is not None and args.max_decisions <= 0) or args.max_steps <= 0 or args.max_batch <= 0 or args.context_tokens <= 256:
        parser.error('Invalid limits')
    if not args.dry_run and not os.environ.get('SLURM_JOB_ID'):
        parser.error('Inference requires a Slurm GPU allocation; use --dry-run locally')
    from scripts.run_experiment import local_model_identity
    episodes = [(c, g) for c in args.conditions for g in args.games]
    output = args.output
    manifest = dict(
        protocol=PROTOCOL, upstream_commit=verify_upstream().get('commit'), conditions=args.conditions,
        games=args.games, model=args.model, revision=args.revision, quantization=args.quantization,
        local_model_identity=local_model_identity(args.model), dry_run=args.dry_run,
        generation_version=GENERATION_VERSION,
        settings=dict(solo_definition='free role choice, shared bag, two current views and observable saved memory', interface=args.interface, memory=10, stuck_steps=50, stuck_behavior=args.help_policy, forced_after_help_steps=10, max_decisions=args.max_decisions or args.max_steps*2, peer_burst=4, memory_budgets_per_role=dict(observations=4000,discoveries=3000,received=1500,feedback=500),
                      max_steps=args.max_steps, use_cot=True, native_thinking=False, do_sample=False,
                      max_new_tokens=256, context_tokens=args.context_tokens, max_batch=args.max_batch),
        code_hashes={p: file_hash(ROOT/p) for p in (
            'scripts/original_escape.py', 'scripts/coop_original.py', 'scripts/central_solo.py', 'scripts/adaptive_escape.py', 'scripts/run_matrix.py',
            'scripts/run_original.py', 'scripts/run_model.py', 'scripts/greedy_generation.py', 'scripts/action_interface.py')},
        role_hashes={g: file_hash(ROLES_DIR/f'{g}.json') for g in args.games},
        evaluation_hashes={p: file_hash(ROOT/p) for p in ('data/clues.json', 'data/split_audit_v6.json', 'scripts/analyze_collaboration.py')},
        differences_from_paper=[
            'HF/SDPA with NF4 4-bit on one GPU instead of vLLM BF16',
            f'Context limit {args.context_tokens} (original deployment example: 2400; no prompt truncated)',
            'Batched greedy decoding with left padding; may differ in rare tokens from batch size 1',
            'Qwen3 native thinking disabled; original short Thought/Action prompt'])
    exp = output/'experiment.json'
    if exp.exists():
        previous, current = json.loads(exp.read_text()), json.loads(json.dumps(manifest))
        if resume_key(previous) != resume_key(current):
            raise SystemExit(f'Cannot resume {output}: code, data, model or settings changed. Use a new --output.')
        if previous != current:  # Solo run continued after unrelated coop/runner changes
            with (output/'resumed_with.jsonl').open('a') as f:
                f.write(json.dumps(dict(time=time.time(), manifest=current)) + '\n')
        say(f'Resuming {output}')
    else:
        output.mkdir(parents=True, exist_ok=True)
        write_json(exp, manifest)
        say(f'New run {output}')

    # Frozen evaluator-only inputs: never included in generation requests.
    frozen = output/'evaluation_inputs'
    (frozen/'roles').mkdir(parents=True, exist_ok=True)
    for source, dest in [(ROOT/'data/clues.json', frozen/'clues.json'), (ROOT/'data/split_audit_v6.json', frozen/'split_audit.json')] + [
            (ROLES_DIR/f'{g}.json', frozen/'roles'/f'{g}.json') for g in args.games]:
        if not dest.exists():
            dest.write_bytes(source.read_bytes())
    saved_manifest = json.loads(exp.read_text())
    if file_hash(frozen/'split_audit.json') != saved_manifest['evaluation_hashes']['data/split_audit_v6.json']:
        raise SystemExit('Frozen split audit changed')
    if file_hash(frozen/'clues.json') != saved_manifest['evaluation_hashes']['data/clues.json']:
        raise SystemExit('Frozen clue annotations changed')
    if any(file_hash(frozen/'roles'/f'{g}.json') != saved_manifest['role_hashes'][g] for g in args.games):
        raise SystemExit('Frozen role snapshot changed')

    global REAL_STDOUT
    REAL_STDOUT = sys.stdout
    sys.stdout = open(os.devnull, 'w')  # upstream engine prints (including correct codes)
    if args.dry_run:
        for condition, game in episodes:
            prompts = []
            def request(messages, prompts=prompts):
                prompts.append(messages)
                return PreviewBackend().complete_batch([messages], None)[0]
            run_episode(condition, game, output/condition/game, request, lambda: len(prompts) >= 3, 3, interface=args.interface)
            write_json(output/condition/game/'first_prompts.json', prompts)
        report(output, episodes)
        say(f'Dry run prompts: {output}/<condition>/<game>/first_prompts.json')
        return

    pending = []
    for condition, game in episodes:
        p = output/condition/game/'summary.json'
        final = FINAL + (() if args.retry_errors else ('error',))
        if not p.exists() or json.loads(p.read_text())['stop_reason'] not in final:
            pending.append((condition, game))
    if not pending:
        report(output, episodes)
        say('All episodes already finished.')
        return
    interrupted = [False]
    for sig in (signal.SIGTERM, signal.SIGUSR1, signal.SIGINT):
        signal.signal(sig, lambda *_: interrupted.__setitem__(0, True))
    start = time.monotonic()
    def stop():
        return interrupted[0] or time.monotonic() - start >= args.wall_seconds

    from scripts.run_original import diagnostics
    diagnostics(output)
    args.seed = 42
    load_start = time.monotonic()
    backend = BatchHF(args)
    backend.metadata['load_seconds'] = time.monotonic() - load_start
    write_json(output/f'model-{time.time_ns()}.json', backend.metadata)
    say(f'Model loaded in {backend.metadata["load_seconds"]:.0f}s; pending episodes: {len(pending)}')
    results, timing = run_all(pending, backend, stop, args.max_steps, args.max_batch, output, interface=args.interface, help_policy=args.help_policy, max_decisions=args.max_decisions)
    timing.update(wall_seconds=time.monotonic() - start, job=os.environ.get('SLURM_JOB_ID'))
    timing['peak_gpu_allocated_bytes'] = backend.backend.torch.cuda.max_memory_allocated()
    with (output/'timing.jsonl').open('a') as f:
        f.write(json.dumps(timing) + '\n')
    rows = report(output, episodes)
    reasons = [json.loads((output/c/g/'summary.json').read_text())['stop_reason']
               if (output/c/g/'summary.json').exists() else 'interrupted' for c, g in episodes]
    say(f'Timing: {timing}')
    if 'interrupted' in reasons:
        raise SystemExit(EXIT_RESUMABLE)
    if 'error' in reasons:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
