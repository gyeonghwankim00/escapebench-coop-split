"""Controlled solo protocol; evaluator state and hints never enter unassisted prompts."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import time

from scripts.run_model import make_solo_world, parse_action, write_json

PROTOCOL_VERSION = 'solo-v1'
INSTRUCTIONS = '''You are playing a text escape game alone. Explore, solve the mechanisms, and escape.
The observation already shows your current area, visible objects, inventory, and reachable areas.
These lists have different roles. Use exact names from the appropriate list:
- move: travel to a name in Reachable areas. A close-up is an AREA if listed there, not an object.
  Example: {"type":"move","target":"desk close-up"}
- click: examine or operate a visible object. Clicking a collectible object puts it in your inventory.
  Example: {"type":"click","target":"key"}
- apply: use a tool you ALREADY HOLD on an object in the CURRENT area.
  Example: {"type":"apply","tool":"key","target":"locked door"}
- input: enter a literal code or answer into a current object that accepts text.
  This does NOT execute a natural-language instruction such as "dig with a wrench".
  Example: {"type":"input","value":"1234","target":"keypad"}
- craft: combine two objects you ALREADY HOLD.
  Example: {"type":"craft","first":"battery","second":"remote control"}
- look: request the current observation again. It does not search inside objects or reveal hidden ones.
  Example: {"type":"look"}
- wait: take no action. Example: {"type":"wait"}
Do not invent tools or targets. Descriptions may mention things that are not currently actionable.
If a method fails and nothing relevant changes, try another method or explore another area.
Use observed clues to infer codes instead of repeatedly submitting the same unsupported guess.
There is no partner, messaging, or object passing in this solo game.
After any reasoning, your FINAL answer must be exactly one JSON action, without extra fields or prose.
'''


@dataclass(frozen=True)
class Settings:
    thinking: bool = False
    hints: bool = False
    max_steps: int = 1000
    stuck_steps: int = 50
    hint_patience: int = 20
    history_turns: int = 10
    max_new_tokens: int = 2048
    temperature: float = 0.6
    top_p: float = 0.95
    top_k: int = 20
    max_seconds: int = 1800

    def validate(self):
        for name in ('max_steps', 'stuck_steps', 'hint_patience', 'max_new_tokens', 'max_seconds'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'{name} must be a positive integer')
        if type(self.thinking) is not bool or type(self.hints) is not bool:
            raise ValueError('thinking/hints must be booleans')
        if self.history_turns < 0 or self.temperature <= 0 or not 0 < self.top_p <= 1 or self.top_k < 1:
            raise ValueError('Invalid memory or sampling configuration')

    def generation(self):
        return {k: getattr(self, k) for k in ('thinking', 'max_new_tokens', 'temperature', 'top_p', 'top_k')}


def new_world(dataset):
    world = make_solo_world(dataset)
    # The experimental protocol starts in the actual original opening scene.
    world.location['A'] = world.spec['navigation']['start']
    return world


def format_observation(o):
    lines = [f'Current area: {o["area"]}', 'Scene description:', o['description'], '\nVisible objects:']
    for obj in o['objects']:
        status = 'collectible by click' if obj['collectible'] else ('operable' if obj['interactable'] else 'not currently operable')
        lines.append(f'- {obj["name"]} [{status}]: {obj["description"]}')
    if not o['objects']:
        lines.append('(none)')
    names = [x['name'] for x in o['objects'] if x['collectible'] or x['interactable']]
    lines += ['\nCurrent object targets (not area names):', json.dumps(names), '\nReachable areas (use move):']
    lines += ['- '+area for area in o['areas'] if area != o['area'] and area != 'room A']
    lines += ['\nInventory (tools available for apply/craft):']
    lines += [f'- {x["name"]}: {x["description"]}' for x in o['inventory']] or ['(none)']
    return '\n'.join(lines)


def messages_for(observation, history, settings, hint=None):
    records = history[-settings.history_turns:] if settings.history_turns else []
    memory = '\n'.join(f'Turn {r["turn"]} at {r["area"]}: {r["action_text"]}\nFeedback: {r["feedback"]}' for r in records)
    text = 'Recent action history:\n' + (memory or '(none)') + '\n\n' + format_observation(observation)
    if hint is not None:
        if not settings.hints:
            raise ValueError('Hints cannot enter an unassisted condition')
        text += ('\n\nExternal hint (assistance, not your own discovery):\n'
                 f'Go to area: {hint["area"]}. If already there, perform the target action.\n'
                 f'Target action: {json.dumps(hint["action"])}\n'
                 'Move using ordinary actions; the environment will not move or act for you.')
    text += '\n\nChoose the next action. Final answer: one JSON action.'
    return [{'role': 'system', 'content': INSTRUCTIONS}, {'role': 'user', 'content': text}]


def final_answer(raw, thinking):
    if not thinking:
        return raw.strip()
    # Qwen's template may have already opened <think> before generated tokens.
    if '</think>' not in raw:
        raise ValueError('Thinking output did not close </think>; no complete final action.')
    answer = raw.split('</think>', 1)[1].strip()
    if not answer:
        raise ValueError('Thinking finished without a final action.')
    return answer


def compile_reference(dataset):
    """Replay the privileged witness once to map actions to semantic milestones."""
    world = new_world(dataset)
    entries = []
    for row in world.spec['preservation']['source_action_mapping']:
        action = deepcopy(row['action'])
        area = world.location['A'] if action['type'] == 'craft' else world.entities[action['target']]['zone']
        if world.location['A'] != area:
            moved = world.step('A', dict(type='move', target=area))
            if not moved['valid']:
                raise ValueError(f'Reference area inaccessible: {area}')
        before = set(world.completed_milestones)
        result = world.step('A', action)
        delta = world.completed_milestones - before
        if not result['valid'] or not result['effect'] or not delta:
            raise ValueError(f'Reference has no new milestone: {row}')
        entries.append(dict(source_step=row['source_step'], area=area, action=action, milestones=sorted(delta)))
    if not world.success or world.progress()['fraction'] != 1.0:
        raise ValueError('Reference does not cover all source milestones and escape.')
    return entries


def choose_hint(world, entries):
    """First unfinished *feasible* reference action, tested only on a copy."""
    for entry in entries:
        if set(entry['milestones']) <= world.completed_milestones:
            continue
        probe = object.__new__(type(world))
        probe.__dict__ = deepcopy({k: v for k, v in vars(world).items() if k != 'events'})
        probe.events = []
        hint = deepcopy(entry)
        if hint['action']['type'] == 'craft':
            hint['area'] = world.location['A']
        if probe.location['A'] != hint['area']:
            if not probe.step('A', dict(type='move', target=hint['area']))['valid']:
                continue
        before = set(probe.completed_milestones)
        result = probe.step('A', hint['action'])
        if result['valid'] and (probe.completed_milestones - before) & set(hint['milestones']):
            return hint
    return None


def run_trial(dataset, backend, settings, output, stop=None):
    settings.validate()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    world = new_world(dataset)
    reference = compile_reference(dataset) if settings.hints else None
    history = []; seen = set(); visited = set()
    stalled = hint_turns = hints = invalid = parse_errors = repetitions = output_limits = calls = 0
    input_tokens = output_tokens = 0
    first_stall = first_hint = active_hint = None
    reason = 'step_budget'; error = None; interrupted = None
    started = time.monotonic()
    cursor = 0
    def stop_requested():
        return (stop and stop()) or time.monotonic() - started >= settings.max_seconds
    config = dict(protocol=PROTOCOL_VERSION, settings=asdict(settings), dataset=str(dataset),
                  dataset_sha256=hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
                  prompt_sha256=hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(),
                  start='original starting scene', navigation='collapsed reachable scene graph',
                  memory='recent action/feedback only; no persistent notebook or hidden state',
                  hint_policy='first feasible unfinished reference action; no teleport or forced execution',
                  progress='unique source conditions satisfied + unique source tools acquired')
    write_json(output/'config.json', config)
    try:
        with (output/'turns.jsonl').open('w') as turns, (output/'events.jsonl').open('w') as events:
            for _ in range(settings.max_steps):
                if stop_requested():
                    reason = 'interrupted' if stop and stop() else 'time_budget'
                    break
                if settings.hints and active_hint is None and stalled >= settings.stuck_steps:
                    active_hint = choose_hint(world, reference)
                    if active_hint is None:
                        reason = 'no_feasible_hint'; break
                    hints += 1; hint_turns = 0
                    if first_hint is None:
                        first_hint = dict(turn=world.turn+1, progress=world.progress())
                observation = world.observe('A')
                visited.add(observation['area'])
                messages = messages_for(observation, history, settings, active_hint)
                generated = backend.complete(messages, settings.generation(), stop_requested)
                calls += 1
                input_tokens += generated['input_tokens']; output_tokens += generated['output_tokens']
                output_limits += bool(generated.get('hit_output_limit'))
                if stop_requested():
                    interrupted = generated
                    reason = 'interrupted' if stop and stop() else 'time_budget'
                    break
                parse_error = None
                try:
                    if 'final_text' in generated:
                        answer = generated['final_text']
                        if not answer or not answer.strip():
                            raise ValueError('No complete final action after thinking.')
                    else:
                        answer = final_answer(generated['raw'], settings.thinking)
                    action = parse_action(answer)
                    if action['type'] in ('send', 'pass'):
                        raise ValueError('No communication actions in solo mode.')
                except ValueError as exc:
                    parse_errors += 1; parse_error = str(exc)
                    action = dict(type='__invalid_model_output__')
                public_state = json.dumps(observation, sort_keys=True)
                signature = (public_state, json.dumps(action, sort_keys=True))
                before = set(world.completed_milestones)
                result = world.step('A', action)
                if parse_error:
                    result['feedback'] = parse_error
                    world.events[-1]['feedback'] = parse_error
                delta = world.completed_milestones - before
                repeated = not delta and signature in seen
                seen.add(signature); repetitions += bool(repeated)
                invalid += not result['valid']
                stalled = 0 if delta else stalled + 1
                history.append(dict(turn=world.turn, area=observation['area'],
                                    action_text=json.dumps(action) if not parse_error else '[invalid output]',
                                    feedback=result['feedback']))
                record = dict(turn=world.turn, **generated, action=action, parse_error=parse_error,
                              result=result, progress=world.progress(), new_milestones=sorted(delta),
                              stalled_steps=stalled, repeated_without_progress=bool(repeated), hint=active_hint)
                turns.write(json.dumps(record, ensure_ascii=False)+'\n'); turns.flush()
                for event in world.events[cursor:]:
                    events.write(json.dumps(event, ensure_ascii=False)+'\n')
                events.flush(); cursor = len(world.events)
                print(f'{world.turn:04} progress={world.progress()["fraction"]:.1%} '
                      f'stalled={stalled} hints={hints} {action}', flush=True)
                if world.success:
                    reason = 'success'; break
                if active_hint:
                    hint_turns += 1
                    if set(active_hint['milestones']) <= world.completed_milestones:
                        active_hint = None; hint_turns = 0; stalled = 0
                    elif hint_turns >= settings.hint_patience:
                        reason = 'hint_following_failed'; break
                if stalled >= settings.stuck_steps:
                    if first_stall is None:
                        first_stall = dict(turn=world.turn, progress=world.progress())
                    if not settings.hints:
                        reason = 'stalled'; break
            # Flush the observation even if a generation was interrupted.
            for event in world.events[cursor:]:
                events.write(json.dumps(event, ensure_ascii=False)+'\n')
    except Exception as exc:
        reason = 'error'; error = f'{type(exc).__name__}: {exc}'
    finally:
        if interrupted:
            write_json(output/'interrupted_generation.json', interrupted)
        summary = dict(protocol=PROTOCOL_VERSION, stop_reason=reason, error=error,
                       success=world.success, success_without_hints=world.success and hints == 0,
                       progress=world.progress(), first_stall=first_stall, first_hint=first_hint,
                       hints_used=hints, turns=world.turn, model_calls=calls,
                       invalid_actions=invalid, parse_errors=parse_errors,
                       repeated_without_progress=repetitions, output_limit_hits=output_limits,
                       visited_areas=len(visited), input_tokens=input_tokens, output_tokens=output_tokens,
                       wall_seconds=time.monotonic()-started)
        write_json(output/'summary.json', summary)
    return summary
