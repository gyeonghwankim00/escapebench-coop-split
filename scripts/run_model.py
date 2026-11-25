"""Alternate two private actors using one local Hugging Face model.

Run on an allocated GPU node. --dry-run only previews the initial prompts,
without downloading/loading a model. No answers/reference trace enter prompts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import signal
import statistics
import time

from scripts.coop_escape import World

ROOT = Path(__file__).resolve().parents[1]
ACTION_FIELDS = {
    'look': (), 'wait': (), 'move': ('target',), 'click': ('target',),
    'apply': ('tool', 'target'), 'input': ('value', 'target'),
    'craft': ('first', 'second'), 'send': ('message',), 'pass': ('tool',),
}


def parse_action(raw):
    """Allow one JSON object, optionally fenced; never extract a lucky substring."""
    text = raw.strip()
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if not match:
            raise ValueError('Return exactly one complete JSON action.')
        text = match[1].strip()
    try:
        action = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError('Response is not a single valid JSON action.') from exc
    if not isinstance(action, dict) or not isinstance(action.get('type'), str):
        raise ValueError('Action must be an object with a string type.')
    typ = action['type']
    if typ not in ACTION_FIELDS:
        raise ValueError('Unknown action type.')
    if set(action) != {'type', *ACTION_FIELDS[typ]}:
        raise ValueError('Unexpected or missing action fields.')
    if any(not isinstance(action[k], str) for k in ACTION_FIELDS[typ]):
        raise ValueError('All action arguments must be strings.')
    return action


def format_observation(observation):
    """Only consume the public actor observation; never accept the world spec."""
    o = observation
    lines = [f'Your room: {o["room"]}', f'Current area: {o["area"]}',
             'Scene Description:', o['description'], '\nVisible Objects:']
    for e in o['objects']:
        status = 'collectible' if e['collectible'] else ('operable' if e['interactable'] else 'not operable')
        lines.append(f'- {e["name"]} [{status}]: {e["description"]}')
    if not o['objects']:
        lines.append('(none)')
    lines += ['\nReachable Areas in Your Room:'] + ['- '+n for n in o['areas']]
    lines += ['\nTools in Bag:'] + [f'- {e["name"]}: {e["description"]}' for e in o['inventory']]
    if not o['inventory']:
        lines.append('(none)')
    lines.append('\nReceived Messages (all messages so far):')
    for m in o['messages']:
        lines.append(f'- Turn {m["turn"]}, from {m["from"]}: {m["text"]}')
    if not o['messages']:
        lines.append('(none)')
    lines.append(f'Your exit open: {o["own_exit_open"]}; Team escaped: {o["team_success"]}')
    return '\n'.join(lines)


def make_messages(system, actor, observation, history, history_turns):
    selected = history[-history_turns:] if history_turns else []
    records = []
    for row in selected:
        records.append(f'Turn {row["turn"]}, position: {row["area"]}\n'
                       f'Your response: {row["raw"]}\nEnvironment feedback: {row["feedback"]}')
    past = '\n\n'.join(records) or '(none)'
    return [{'role': 'system', 'content': system + f'\nYou control actor {actor} only.'},
            {'role': 'user', 'content': 'Your Recent Action History:\n'+past+'\n\n'
             + format_observation(observation)
             + '\n\nChoose your next action. Return exactly one JSON object.'}]


class HFModel:
    def __init__(self, args):
        # Lazy imports keep prompt preview and unit tests dependency-free.
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA GPU unavailable. Allocate a GPU node before running inference.')
        self.torch = torch
        self.args = args
        set_seed(args.seed)
        self.tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        kwargs = dict(revision=args.revision, torch_dtype=dtype, device_map={'': 0},
                      use_safetensors=True, attn_implementation='sdpa')
        if args.quantization == '4bit':
            kwargs['quantization_config'] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
        self.model = AutoModelForCausalLM.from_pretrained(args.model, **kwargs).eval()
        context = getattr(self.model.config, 'max_position_embeddings', args.context_tokens)
        self.context_limit = min(args.context_tokens, context)
        self.metadata = dict(
            model=args.model, requested_revision=args.revision,
            resolved_revision=getattr(self.model.config, '_commit_hash', None),
            quantization=args.quantization, compute_dtype=str(dtype),
            gpu=torch.cuda.get_device_name(0),
            gpu_memory_bytes=torch.cuda.get_device_properties(0).total_memory,
            cuda_runtime=torch.version.cuda, context_limit=self.context_limit,
            packages={p: importlib.metadata.version(p) for p in
                      ('torch','transformers','accelerate','bitsandbytes')})
        self.metadata['chat_template_sha256'] = hashlib.sha256(
            json.dumps(self.tokenizer.chat_template, sort_keys=True).encode()).hexdigest()

    def complete(self, messages, generation, stop=None):
        """Experimental runner: preserve the whole prompt and bound generation time.

        Kept separate from generate() to preserve the legacy experiment behavior.
        """
        from transformers import StoppingCriteria, StoppingCriteriaList
        torch = self.torch
        class StopRequested(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return bool(stop and stop())
        started = time.perf_counter()
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            enable_thinking=generation['thinking'])
        inputs = self.tokenizer(text, return_tensors='pt', add_special_tokens=False)
        count = inputs.input_ids.shape[-1]
        if count + generation['max_new_tokens'] > self.context_limit:
            raise ValueError('Experiment prompt exceeds context budget; no memory or observation was truncated.')
        inputs = inputs.to(self.model.device)
        torch.cuda.synchronize()
        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs, max_new_tokens=generation['max_new_tokens'], do_sample=True,
                temperature=generation['temperature'], top_p=generation['top_p'], top_k=generation['top_k'],
                repetition_penalty=1.0, pad_token_id=self.tokenizer.eos_token_id, use_cache=True,
                stopping_criteria=StoppingCriteriaList([StopRequested()]))
        torch.cuda.synchronize()
        generated = outputs[0, count:]
        raw = self.tokenizer.decode(generated, skip_special_tokens=True)
        # Some tokenizers strip thinking delimiters when decoding special tokens.
        # Preserve that boundary explicitly so reasoning is never parsed as an action.
        final_text = raw
        if generation['thinking']:
            token_ids = generated.tolist()
            closing = self.tokenizer.encode('</think>', add_special_tokens=False)
            boundary = next((i + len(closing) for i in range(len(token_ids) - len(closing) + 1)
                             if closing and token_ids[i:i + len(closing)] == closing), None)
            final_text = (self.tokenizer.decode(token_ids[boundary:], skip_special_tokens=True)
                          if boundary is not None else None)
        return dict(raw=raw, messages=messages, input_tokens=count, output_tokens=len(generated),
                    final_text=final_text,
                    seconds=time.perf_counter()-started,
                    prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    hit_output_limit=len(generated) >= generation['max_new_tokens'])

    def generate(self, system, actor, observation, history, history_turns):
        torch = self.torch
        started = time.perf_counter()
        keep = min(history_turns, len(history))
        while True:
            messages = make_messages(system, actor, observation, history, keep)
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            inputs = self.tokenizer(text, return_tensors='pt', add_special_tokens=False)
            count = inputs.input_ids.shape[-1]
            if count + self.args.max_new_tokens <= self.context_limit:
                break
            if not keep:
                raise RuntimeError('Current observation and inbox exceed context budget. '
                                   'Increase --context-tokens; no observation was silently truncated.')
            keep -= 1
        inputs = inputs.to(self.model.device)
        torch.cuda.synchronize()
        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs, max_new_tokens=self.args.max_new_tokens,
                do_sample=True, temperature=0.7, top_p=0.8, top_k=20,
                repetition_penalty=1.0,
                pad_token_id=self.tokenizer.eos_token_id, use_cache=True)
        torch.cuda.synchronize()
        generated = outputs[0, count:]
        raw = self.tokenizer.decode(generated, skip_special_tokens=True)
        return dict(raw=raw, messages=messages, input_tokens=count,
                    output_tokens=len(generated), seconds=time.perf_counter()-started,
                    history_turns_included=keep,
                    hit_output_limit=len(generated) >= self.args.max_new_tokens)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def make_solo_world(path):
    """Give one actor all original scenes, while retaining original reachability gates."""
    world = World(path)
    for zone in world.zones.values():
        if zone.get('source_scene'):
            zone['room'] = 'A'
    for entity in world.entities.values():
        entity['room'] = 'A'
    world.zones['room A']['desc'] = 'Explore the accessible areas and escape.'
    return world


SOLO_INSTRUCTIONS = '''You are alone in an escape game. Explore accessible areas, collect and use
objects, solve mechanisms, and escape. You can act only in your current area.
Use names exactly as observed. Return exactly one JSON object per turn.
Actions: {"type":"look"}, {"type":"move","target":"area name"},
{"type":"click","target":"object name"}, {"type":"apply","tool":"object name","target":"object name"},
{"type":"input","value":"string","target":"object name"},
{"type":"craft","first":"object name","second":"object name"}, {"type":"wait"}.
'''


def run_episode(world, backend, system, output, max_steps, history_turns, stop=None, solo=False):
    """Backend sees only actor observations/history. Invalid syntax spends one turn."""
    histories = {'A': [], 'B': []}
    latencies = []; valid = effects = parse_errors = 0
    reason = 'budget_exhausted'; completed = 0; error = None
    event_cursor = 0; pending_error = None; current_generation = None
    started = time.perf_counter()
    reference = world.spec.get('preservation', {}).get('source_action_mapping', [])
    matched = set()
    with (output/'turns.jsonl').open('w') as turns, (output/'events.jsonl').open('w') as events:
        try:
            for index in range(max_steps):
                if stop and stop():
                    reason = 'interrupted'; break
                actor = 'A' if solo or index % 2 == 0 else 'B'
                observation = world.observe(actor)
                current_generation = backend.generate(system, actor, observation, histories[actor], history_turns)
                raw = current_generation['raw']; parse_error = None
                try:
                    action = parse_action(raw)
                    if solo and action['type'] in ('send', 'pass'):
                        raise ValueError('Communication and object passing are unavailable in solo mode.')
                except ValueError as exc:
                    parse_error = str(exc); parse_errors += 1
                    action = {'type': '__invalid_model_output__'}
                result = world.step(actor, action)
                if result['valid'] and result['effect']:
                    for entry in reference:
                        if entry['source_step'] not in matched and entry['action'] == action:
                            matched.add(entry['source_step'])
                            break
                if parse_error:
                    result['feedback'] = parse_error
                    world.events[-1]['feedback'] = parse_error
                histories[actor].append(dict(turn=world.turn, area=observation['area'], raw=raw,
                                             feedback=result['feedback']))
                record = dict(turn=world.turn, actor=actor, **current_generation,
                              action=None if parse_error else action, parse_error=parse_error, result=result)
                turns.write(json.dumps(record, ensure_ascii=False)+'\n'); turns.flush()
                for event in world.events[event_cursor:]:
                    events.write(json.dumps(event, ensure_ascii=False)+'\n')
                events.flush(); event_cursor = len(world.events)
                latencies.append(current_generation['seconds'])
                valid += result['valid']; effects += result['effect']; completed += 1
                print(f'{world.turn:03} {actor} valid={result["valid"]} effect={result["effect"]} '
                      f'{current_generation["seconds"]:.2f}s {raw.strip()}', flush=True)
                current_generation = None
                if world.success:
                    reason = 'success'; break
        except KeyboardInterrupt as exc:
            reason = 'interrupted'; pending_error = exc
        except Exception as exc:
            reason = 'error'; error = f'{type(exc).__name__}: {exc}'; pending_error = exc
        finally:
            for event in world.events[event_cursor:]:
                events.write(json.dumps(event, ensure_ascii=False)+'\n')
            # Preserve a generated response even when processing it unexpectedly fails.
            if current_generation:
                write_json(output/'interrupted_generation.json', current_generation)
            summary = dict(stop_reason=reason, team_success=world.success, turns=completed,
                           valid_actions=valid, effectful_actions=effects, parse_errors=parse_errors,
                           wall_seconds=time.perf_counter()-started,
                           mean_call_seconds=statistics.mean(latencies) if latencies else None,
                           median_call_seconds=statistics.median(latencies) if latencies else None,
                           first_call_seconds=latencies[0] if latencies else None,
                           reference_actions_matched=len(matched), reference_actions_total=len(reference),
                           reference_action_match_fraction=len(matched)/len(reference) if reference else None,
                           error=error)
            write_json(output/'summary.json', summary)
    if pending_error:
        raise pending_error
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'data/pilot/01_mirror_workshop/environment.json')
    parser.add_argument('--model', default='Qwen/Qwen3-8B')
    parser.add_argument('--revision', default='main')
    parser.add_argument('--quantization', choices=['4bit','none'], default='4bit')
    parser.add_argument('--max-steps', type=int, default=30, help='Total A+B turns, not per actor.')
    parser.add_argument('--history-turns', type=int, default=10)
    parser.add_argument('--context-tokens', type=int, default=8192)
    parser.add_argument('--max-new-tokens', type=int, default=192)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--solo', action='store_true', help='One actor controls all original scenes and one inventory.')
    args = parser.parse_args()
    if args.max_steps < 1 or args.history_turns < 0 or not 0 < args.max_new_tokens < args.context_tokens:
        parser.error('Invalid turn or token budget.')
    output = args.output or ROOT/'outputs'/('model-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier experiment
    system = SOLO_INSTRUCTIONS if args.solo else (ROOT/'data/pilot/agent_instructions.txt').read_text()
    world = make_solo_world(args.dataset) if args.solo else World(args.dataset)
    config = {k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    config.update(dataset_sha256=hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
                  instructions_sha256=hashlib.sha256(system.encode()).hexdigest(),
                  python=platform.python_version(), output=str(output),
                  memory_policy='Recent own action/feedback only; full received inbox; oldest own history dropped to fit context.',
                  scheduler='Solo A only; invalid output consumes a turn.' if args.solo else 'Strict alternation A then B; invalid output consumes a turn.',
                  thinking=False, temperature=0.7, top_p=0.8, top_k=20)
    write_json(output/'config.json', config)
    if args.dry_run:
        for actor in ('A' if args.solo else 'AB'):
            write_json(output/f'prompt_{actor}.json', make_messages(system,actor,world.observe(actor),[],args.history_turns))
        write_json(output/'summary.json', dict(stop_reason='dry_run',model_loaded=False,turns=0))
        print(f'Prompt preview only (no model run): {output}')
        return
    # The GSDS docs prohibit workloads on login nodes, even lightweight inference.
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Allocate a GPU using launch-shell or sbatch first (SLURM_JOB_ID is missing).')
    stopped = [False]
    def handle_signal(signum, frame):
        stopped[0] = True
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGUSR1, handle_signal)
    load_started = time.perf_counter()
    try:
        backend = HFModel(args)
    except Exception as exc:
        write_json(output/'summary.json', dict(stop_reason='model_load_error',error=f'{type(exc).__name__}: {exc}',turns=0))
        raise
    backend.metadata['load_seconds'] = time.perf_counter()-load_started
    write_json(output/'model.json', backend.metadata)
    summary = run_episode(world,backend,system,output,args.max_steps,args.history_turns,lambda:stopped[0],solo=args.solo)
    write_json(output/'gpu.json',dict(peak_allocated_bytes=backend.torch.cuda.max_memory_allocated(),
                                    peak_reserved_bytes=backend.torch.cuda.max_memory_reserved()))
    print(json.dumps(summary,indent=2)); print(f'Logs: {output}')


if __name__ == '__main__':
    main()
