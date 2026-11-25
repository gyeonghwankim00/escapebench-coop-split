"""Small deterministic interpreter for the pilot data. No LLM/API dependencies.

Dataset files are privileged environment definitions, never agent prompts.
Agents receive only observe(actor) and the result of their own step(actor, action).
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path


class InvalidAction(ValueError):
    pass


class World:
    def __init__(self, path):
        self.spec = json.loads(Path(path).read_text())
        self.entities = {e['name']: deepcopy(e) for e in self.spec['entities']}
        self.zones = {z['name']: deepcopy(z) for z in self.spec['zones']}
        self.location = {'A': 'room A', 'B': 'room B'}
        self.bags = {'A': {}, 'B': {}}
        self.inbox = {'A': [], 'B': []}
        self.exits = {'A': False, 'B': False}
        self.events = []
        self.turn = 0
        for e in self.entities.values():
            e.setdefault('state', 0)
            e.setdefault('visible', True)
            e.setdefault('interactable', True)
        self.exposures = {'A': set(), 'B': set()}
        # Evaluator-only counters. Stable IDs survive partial apply/craft consumption.
        self.completed_milestones = set()
        self._condition_ids = {}
        self._craft_ids = {}
        for name, entity in self.entities.items():
            for si, state in enumerate(entity['states']):
                for ti, transition in enumerate(state.get('transitions', [])):
                    self._condition_ids[name, si, ti] = [
                        f'key:{name}:{si}:{ti}:{ci}' for ci, _ in enumerate(transition.get('wait_for', []))]
                if entity['kind'] == 'tool':
                    self._craft_ids[name, si] = [
                        f'craft:{name}:{si}:{ci}' for ci, _ in enumerate(state.get('wait_for', []))]
        self._key_ids = {x for ids in [*self._condition_ids.values(), *self._craft_ids.values()] for x in ids}
        self._tool_ids = {f'tool:{n}' for n, e in self.entities.items() if e['kind'] == 'tool'}

    def progress(self):
        """Unique satisfied source conditions + newly acquired tools, never moves."""
        keys = len(self.completed_milestones & self._key_ids)
        tools = len(self.completed_milestones & self._tool_ids)
        total = len(self._key_ids) + len(self._tool_ids)
        return dict(key_steps=keys, total_key_steps=len(self._key_ids),
                    tools_collected=tools, total_tools=len(self._tool_ids),
                    completed=keys+tools, total=total, fraction=(keys+tools)/total if total else 0.0)

    @property
    def success(self):
        return all(self.exits.values())

    def _actor(self, actor):
        if actor not in self.bags:
            raise InvalidAction('Unknown actor.')

    def _state(self, entity):
        return entity['states'][entity['state']]

    def accessible_zones(self, actor):
        navigation = self.spec.get('navigation')
        if not navigation:
            return {z['name'] for z in self.zones.values()
                    if z['room'] == actor and z.get('visible', True)}
        scenes = {s['name']: s for s in navigation['scenes']}
        pending = [navigation['start']]
        reachable = set()
        while pending:
            name = pending.pop()
            if name in reachable or not self.zones[name].get('visible', True):
                continue
            reachable.add(name)
            pending.extend(scenes[name].get('scene_relations', {}).values())
        return {f'room {actor}'} | {n for n in reachable if self.zones[n]['room'] == actor}

    def _present(self, actor, name):
        entity = self.entities.get(name)
        if (entity is None or not entity['visible'] or entity['room'] != actor
                or entity['zone'] != self.location[actor]
                or entity['zone'] not in self.accessible_zones(actor)):
            # Deliberately do not reveal whether a guessed name exists remotely.
            raise InvalidAction('Target is not available in your current area.')
        return entity

    def _held(self, actor, name):
        if name not in self.bags[actor]:
            raise InvalidAction('That object is not in your inventory.')
        return self.bags[actor][name]

    def _observation(self, actor):
        zone = self.location[actor]
        visible = [e for e in self.entities.values()
                   if e['room'] == actor and e['zone'] == zone and e['visible']]
        result = {
            'room': actor, 'area': zone, 'description': self.zones[zone]['desc'],
            'areas': [n for n in self.zones if n in self.accessible_zones(actor)],
            'objects': [{'name': e['name'], 'description': self._state(e)['desc'],
                         'collectible': e['kind'] == 'tool',
                         'interactable': e['interactable']} for e in visible],
            'inventory': [{'name': n, 'description': self._state(e)['desc']}
                          for n, e in self.bags[actor].items()],
            'messages': deepcopy(self.inbox[actor]),
            'own_exit_open': self.exits[actor], 'team_success': self.success,
        }
        # Evaluator-only annotations: exposure means text actually rendered,
        # not that the model noticed or understood it.
        for clue in self.spec['annotations']['information_links']:
            source_name = clue.get('source_entity')
            source = next((e for e in visible if e['name'] == source_name), None)
            if source is None:
                source = self.bags[actor].get(source_name)
            # Incoming messages (including lucky guesses) are not discovery of
            # the physical source. Only the rendered source description counts.
            if (actor == clue['holder'] and source is not None
                    and all(s in self._state(source)['desc'] for s in clue['evidence_text'])):
                self.exposures[actor].add(clue['id'])
            if (actor == clue['holder'] and clue.get('source_scene') == zone
                    and all(s in result['description'] for s in clue['evidence_text'])):
                self.exposures[actor].add(clue['id'])
        return result

    def observe(self, actor):
        self._actor(actor)
        result = self._observation(actor)
        self.events.append({'turn': self.turn, 'type': 'observation', 'actor': actor,
                            'observation': deepcopy(result),
                            'exposed_clues': sorted(self.exposures[actor])})
        return result

    def _trigger(self, entity, trigger, actor):
        parts = [p.strip() for p in trigger.split(',')]
        op, args = parts[0], parts[1:]
        if op == 'finish_team':
            self.exits = {'A': True, 'B': True}
            return
        if op == 'become_tool':
            tool = self.entities[args[0]]
            tool['visible'] = False
            entity['visible'] = False
            self.bags[actor][tool['name']] = tool
            self.completed_milestones.add(f'tool:{tool["name"]}')
            return
        if op == 'open_exit':
            self.exits[args[0]] = True
            return
        if len(args) == 1:
            target, value = entity, args[0]
        else:
            kind, name, value = args
            target = self.zones[name] if kind in ('zone', 'scene') else self.entities[name]
        if op == 'change_state':
            target['state'] = int(value)
        elif op == 'change_visible':
            target['visible'] = value.lower() == 'true'
        elif op == 'change_interact':
            target['interactable'] = value.lower() == 'true'
        else:
            raise ValueError(f'Unsupported dataset trigger: {trigger}')

    def _consume_use(self, actor, tool, target_name):
        uses = self._state(tool).get('apply_to', [])
        uses.remove(target_name)
        if not uses and tool['state'] == len(tool['states']) - 1:
            self.bags[actor].pop(tool['name'])

    def _interact(self, actor, action):
        op = action['type']
        entity = self._present(actor, action['target'])
        if op == 'click' and entity['kind'] == 'tool':
            self.bags[actor][entity['name']] = entity
            entity['visible'] = False
            self.completed_milestones.add(f'tool:{entity["name"]}')
            return f"Collected {entity['name']}. {self._state(entity)['desc']}", True
        if not entity['interactable']:
            return 'This object cannot currently be operated.', False
        state = self._state(entity)
        tool = self._held(actor, action['tool']) if op == 'apply' else None
        for ti, transition in enumerate(state.get('transitions', [])):
            for idx, condition in enumerate(transition.get('wait_for', [])):
                parts = [p.strip() for p in condition.split(',')]
                match = parts[0] == op
                if op == 'input':
                    match = match and str(action['value']) == parts[-1]
                elif op == 'apply':
                    match = (match and parts[-1] == tool['name']
                             and entity['name'] in self._state(tool).get('apply_to', []))
                if not match:
                    continue
                ids = self._condition_ids[entity['name'], entity['state'], ti]
                milestone = ids[idx]
                if op == 'apply':
                    self._consume_use(actor, tool, entity['name'])
                    transition['wait_for'].pop(idx)
                    ids.pop(idx)
                    self.completed_milestones.add(milestone)
                    if transition['wait_for']:
                        return 'Object applied, but this mechanism still needs something else.', True
                self.completed_milestones.add(milestone)
                for trigger in transition.get('trigger', []):
                    self._trigger(entity, trigger, actor)
                return transition.get('reward', 'The mechanism responds successfully.'), True
        return state.get('neg_reward', 'Nothing happens.'), False

    def _craft(self, actor, first, second):
        x, y = self._held(actor, first), self._held(actor, second)
        for base, part in [(x, y), (y, x)]:
            waits = self._state(base).get('wait_for', [])
            if (part['name'] in waits
                    and base['name'] in self._state(part).get('apply_to', [])):
                ci = waits.index(part['name'])
                milestone = self._craft_ids[base['name'], base['state']].pop(ci)
                waits.remove(part['name'])
                self._consume_use(actor, part, base['name'])
                self.completed_milestones.add(milestone)
                if not waits:
                    base['state'] += 1
                return f"Assembled {base['name']}. {self._state(base)['desc']}", True
        return 'These objects cannot be combined in their current states.', False

    def step(self, actor, action):
        self._actor(actor)
        self.turn += 1
        valid, effect = True, False
        try:
            op = action['type']
            if op == 'move':
                zone = self.zones.get(action['target'])
                if zone is None or zone['name'] not in self.accessible_zones(actor):
                    raise InvalidAction('Area is not accessible from your room.')
                self.location[actor] = zone['name']
                feedback, effect = 'Moved to the selected area.', True
            elif op in ('click', 'input', 'apply'):
                feedback, effect = self._interact(actor, action)
            elif op == 'craft':
                feedback, effect = self._craft(actor, action['first'], action['second'])
            elif op == 'send':
                message = action['message']
                if not isinstance(message, str) or not message.strip() or len(message) > 2000:
                    raise InvalidAction('Messages must contain 1–2000 characters.')
                other = 'B' if actor == 'A' else 'A'
                self.inbox[other].append({'from': actor, 'turn': self.turn, 'text': message})
                feedback, effect = 'Message delivered.', True
            elif op == 'pass':
                tool = self._held(actor, action['tool'])
                other = 'B' if actor == 'A' else 'A'
                self.bags[other][tool['name']] = self.bags[actor].pop(tool['name'])
                feedback, effect = 'Object delivered through the hatch.', True
            elif op in ('look', 'wait'):
                feedback = 'You look around.' if op == 'look' else 'You wait.'
            else:
                raise InvalidAction('Unknown action type.')
        except (InvalidAction, KeyError, TypeError) as exc:
            valid = False
            feedback = str(exc) if isinstance(exc, InvalidAction) else 'Malformed action.'
        observation = self._observation(actor)
        # Some original clues exist only in an action reward, not the next state description.
        if valid and effect:
            for clue in self.spec['annotations']['information_links']:
                if (actor == clue['holder'] and action.get('target') == clue.get('source_entity')
                        and all(s in feedback for s in clue['evidence_text'])):
                    self.exposures[actor].add(clue['id'])
        result = {'valid': valid, 'effect': effect, 'feedback': feedback,
                  'observation': observation}
        self.events.append({'turn': self.turn, 'type': 'action', 'actor': actor,
                            'action': deepcopy(action), **deepcopy(result),
                            'exposed_clues': sorted(self.exposures[actor])})
        return result


def replay(dataset_path, trace_path=None):
    dataset_path = Path(dataset_path)
    world = World(dataset_path)
    trace = json.loads((Path(trace_path) if trace_path else
                        dataset_path.with_name('reference.json')).read_text())
    world.observe('A')
    world.observe('B')
    for index, row in enumerate(trace, 1):
        result = world.step(row['actor'], row['action'])
        if not result['valid'] or not result['effect']:
            raise AssertionError(f'{dataset_path.parent.name}: reference step {index}: '
                                 f'{row}: {result["feedback"]}')
    if not world.success:
        raise AssertionError(f'{dataset_path.parent.name}: exits not both open')
    return world


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    if args.replay:
        world = replay(args.dataset)
        print(json.dumps({'success': world.success, 'steps': world.turn,
                          'exits': world.exits}, indent=2))
    else:
        world = World(args.dataset)
        print('Enter JSON: {"actor":"A","action":{"type":"move","target":"..."}}. q to quit.')
        for actor in ('A', 'B'):
            print(json.dumps(world.observe(actor), ensure_ascii=False, indent=2))
        while not world.success:
            try:
                line = input('> ')
                if line.strip() == 'q':
                    break
                row = json.loads(line)
                print(json.dumps(world.step(row['actor'], row['action']),
                                 ensure_ascii=False, indent=2))
            except EOFError:
                break
            except (ValueError, KeyError) as exc:
                print(f'Invalid command: {exc}')
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in world.events))


if __name__ == '__main__':
    main()
