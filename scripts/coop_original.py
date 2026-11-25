"""Two-agent cooperation on the pinned, unmodified EscapeBench engine.

Solo and 2-agent runs share one engine, one YAML, one progress counter, one
prompt format and one generation setting. This layer adds only:

* scene ownership: each role sees and enters only its own scenes;
* one bag per role (the engine's global bag is swapped in per turn);
* send(message) and give(tool), and a partner-update section in the prompt;
* A/B alternation over the shared team step budget, and role-aware help.

Nothing under vendor/ is modified. With every scene assigned to A and
coop=False, CoopAgent reproduces the original BaseAgent step for step
(tests/test_matrix.py checks prompts and logs against it).
"""
from copy import deepcopy
import json
import re

import scripts.original_escape as oe

gv = oe.gv
ROLES_DIR = oe.ROOT / 'data/roles'
BASE_ACTIONS = ['click', 'craft', 'apply', 'input', 'move']
COOP_ACTIONS = BASE_ACTIONS + ['send', 'give']
MAX_MESSAGE_CHARS = 300
VIA = ' via partner area'


class _RoleVisible:
    """Truthy marker: a scene shown as visible to one role for one turn only."""
    def __bool__(self):
        return True

    def __repr__(self):
        return 'ROLE_VISIBLE'


ROLE_VISIBLE = _RoleVisible()

COOP_PARAGRAPH = '''You are playing together with a partner. The scenes are divided between the two of you: you can only see and enter your own scenes, and your partner can only see and enter theirs. You cannot see your partner's scenes, bag, or thoughts. Some clues and tools you need may be on your partner's side, and some of yours may be needed by your partner. Two more actions let you cooperate:
- send(message): Send a short text message to your partner. For example, send(The note in my room says the code is 4305).
- give(<applicable tool>): Hand a tool in your bag over to your partner. It leaves your bag and appears in your partner's bag. For example, give(screwdriver).
Messages and tools from your partner will be shown to you. Changes your partner makes (such as opening a door) can also affect your scenes. The team escapes when either of you completes the final escape.'''


def coop_system_prompt():
    base = oe.SYS_PROMPT_COT
    marker = '\n\nHere are some reminders'
    assert base.count(marker) == 1
    return base.replace(marker, '\n\n' + COOP_PARAGRAPH + marker)


def find_last_call(text, names):
    """Same regex as upstream find_last_function_call, with a configurable name list."""
    pattern = r'\b(?:' + '|'.join(re.escape(fn) for fn in names) + r')\s*\([^()]*?\)\s*'
    matches = re.findall(pattern, text)
    return matches[-1] if matches else 'No action'


def load_roles(game):
    return json.loads((ROLES_DIR/f'{game}.json').read_text())


def solo_roles(game):
    """Every scene to A. Used only to prove parity with the original agent."""
    import yaml
    scenes = [s['name'] for s in yaml.safe_load((oe.UPSTREAM/'data'/f'{game}.yaml').read_text())]
    return dict(game=game, A=scenes, B=[])


def other(role):
    return 'B' if role == 'A' else 'A'


class CoopAgent(oe.Agent):
    def __init__(self, game, scratch, model_call, max_steps=4000, roles=None, coop=True):
        super().__init__(game, scratch, model_call, max_steps)
        spec = roles if roles is not None else load_roles(game)
        self.role_scenes = {'A': list(spec['A']), 'B': list(spec['B'])}
        # Optional {"B": scene}: the non-starting role begins inside its own room
        # (two-room setup). Without it, it enters once its scenes become reachable.
        self.role_starts = dict(spec.get('starts', {}))
        self.coop = coop
        self.system_prompt = coop_system_prompt() if coop else oe.SYS_PROMPT_COT
        self.action_names = COOP_ACTIONS if coop else BASE_ACTIONS

    # ---------------------------------------------------------------- setup
    def setup(self, controller, game_name):
        super().setup(controller, game_name)
        names = list(self.graph.scenes)
        a, b = self.role_scenes['A'], self.role_scenes['B']
        if sorted(a + b) != sorted(names) or set(a) & set(b):
            raise ValueError(f'Role split must assign each scene of {game_name} exactly once')
        self.owner = {s: r for r in 'AB' for s in self.role_scenes[r]}
        self.base_relations = {n: dict(s.scene_relations) for n, s in self.graph.scenes.items()}
        self.start_scene = names[0]
        start_role = self.owner[self.start_scene]
        # The engine bag created by reset_global_vars() belongs to the starting role.
        self.bags = {start_role: gv.bag, other(start_role): gv.Bag()}
        self.where = {'A': None, 'B': None}
        self.where[start_role] = self.start_scene
        for role, scene in self.role_starts.items():
            if role == start_role or self.owner.get(scene) != role:
                raise ValueError(f'Invalid start {role}={scene}: only the other role may start, in its own scene')
            self.where[role] = scene
        self.stacks = {'A': [], 'B': []}
        self.inbox = {'A': [], 'B': []}
        self.role_steps = {'A': 0, 'B': 0}
        self.next_role = start_role
        self.step_roles, self.step_role_index, self.step_inbox, self.step_hint = [], [], [], []
        self.hint_key = None
        self.current_hint = None
        self.evaluation_before = None

    def evaluation_snapshot(self):
        """Evaluator only. Never inserted into either model's prompt/history.

        Reachability means travel through currently visible scenes from the
        role's current position, not that an item/puzzle is ready to solve.
        """
        reachable = {}
        for role in 'AB':
            origin = self.graph.current_scene if role == self.active_role else self.where[role]
            seen, queue = ({origin}, [origin]) if origin is not None else (set(), [])
            for name in queue:
                for target in self.base_relations[name].values():
                    visible = self.graph.scenes[target].visible
                    if visible is ROLE_VISIBLE:
                        visible = False
                    if target not in seen and (visible or target == self.role_starts.get(role)):
                        seen.add(target)
                        queue.append(target)
            reachable[role] = sorted(n for n in seen if self.owner[n] == role)
        return dict(scene=self.graph.current_scene, reachable_scenes=reachable,
                    bags_before={r: sorted(self.bags[r].tools) for r in 'AB'})

    # ------------------------------------------------------------- movement
    def entry_scene(self, role):
        """First own scene reachable from the original start through visible scenes."""
        if self.owner[self.start_scene] == role:
            return self.start_scene
        seen, queue = {self.start_scene}, [self.start_scene]
        while queue:
            u = queue.pop(0)
            for v in self.base_relations[u].values():
                if v in seen or not self.graph.scenes[v].visible:
                    continue
                seen.add(v)
                if self.owner[v] == role:
                    return v
                queue.append(v)
        return None

    def role_relations(self, role, scene_name):
        """Original neighbors the role owns, plus own scenes reachable through
        visible partner scenes (the partner area is crossed, never entered).
        Target visibility is still checked by the original Scene.actions()."""
        base = self.base_relations[scene_name]
        if all(self.owner[t] == role for t in base.values()):
            return dict(base)
        direct = {t for t in base.values() if self.owner[t] == role} | {scene_name}
        added, rel = set(), {}
        for label, target in base.items():
            if self.owner[target] == role:
                rel[label] = target
                continue
            if not self.graph.scenes[target].visible:
                continue
            seen, queue = {target}, [target]
            while queue:
                u = queue.pop(0)
                for v in self.base_relations[u].values():
                    if v in seen:
                        continue
                    seen.add(v)
                    if self.owner[v] == role:
                        if v not in direct and v not in added:
                            rel[f'Go to {v}{VIA}'] = v
                            added.add(v)
                    elif self.graph.scenes[v].visible:
                        queue.append(v)
        return rel

    # ----------------------------------------------------------------- help
    def holder(self, tool):
        for role in 'AB':
            for name in self.bags[role].tools:
                if name.lower() == tool.strip().lower():
                    return role, name
        return None, None

    def plan_hint(self):
        """Role-aware version of the original helper target.

        The next unfinished reference step goes to the owner of its scene. When a
        tool it needs is in the other bag, the holder is first told to give it.
        Solo split: always the original target, position and action."""
        ref = self.helper[0]
        action = ref['action_answer']
        path = ref['position'].split(' -> ')
        op = action.split('(')[0].strip().lower()
        args = [a.strip() for a in action.split('(')[1].split(')')[0].split(',') if a.strip()]
        tools = args[:1] if op == 'apply' else (args if op == 'craft' else [])
        role = self.owner[path[-1]]
        if op == 'craft':
            role = next((r for r, _ in map(self.holder, tools) if r), role)
        for tool in tools:
            r, name = self.holder(tool)
            if r and r != role:
                return dict(role=r, action=f'give({name})', path=None, kind='give')
        return dict(role=role, action=action, kind='reference',
                    path=path if self.owner[path[-1]] == role else None)

    # ------------------------------------------------------------------ act
    def pick_role(self):
        for role in (self.next_role, other(self.next_role)):
            if self.where[role] is None:
                entry = self.entry_scene(role)
                if entry is None:
                    continue
                self.where[role] = entry
            return role
        raise RuntimeError('No role can act')

    def act(self, step):
        self.pending_generation = None
        self.help_before = self.stuck
        hint = None
        if self.stuck:
            if self.first_hint_progress is None:
                self.first_hint_progress = self.history[-1]['tracking']['progress']
            hint = self.plan_hint()
            key = (hint['role'], hint['action'])
            if key != self.hint_key:
                self.stuck_in_help, self.hint_key = 0, key
            role = hint['role']
            if self.where[role] is None and hint['path'] is None:
                self.where[role] = self.entry_scene(role)
                if self.where[role] is None:
                    raise RuntimeError(f'Hint for {role}, which has no reachable scene')
        else:
            self.hint_key = None
            role = self.pick_role()
        self.current_hint = hint
        self.active_role = role
        self.forced_before = self.stuck and self.stuck_in_help + 1 >= 10

        gv.bag = self.bags[role]
        if self.where[role] is not None:
            self.graph.current_scene = self.where[role]
        self.scene_stack = self.stacks[role]
        log = {'step': step}
        if self.stuck:
            self.stuck_in_help += 1
            if hint['path'] is not None:
                mine = [p for p in hint['path'] if self.owner[p] == role]
                self.scene_stack = mine
                self.graph.current_scene = mine[-1]
                log['position'] = (self.helper[0]['position'] if len(mine) == len(hint['path'])
                                   else ' -> '.join(mine))
            else:
                self.update_scene_stack()
                log['position'] = self.format_scene_stack()
        else:
            self.stuck_in_help = 0
            self.update_scene_stack()
            log['position'] = self.format_scene_stack()

        inbox, self.inbox[role] = self.inbox[role], []
        scene = self.graph.scenes[self.graph.current_scene]
        original_relations = scene.scene_relations
        scene.scene_relations = self.role_relations(role, scene.name)
        # Two-room start: the role's own start scene may still be hidden in the
        # engine (its outside door is locked). The role is inside, so it can always
        # walk back into it; the partner still cannot pass until the door opens.
        home = self.graph.scenes.get(self.role_starts.get(role))
        if home is not None and not home.visible:
            home.visible = ROLE_VISIBLE
        try:
            scene_prompt = self.graph.describe().strip()
            self.evaluation_before = self.evaluation_snapshot()
            self.take_action(scene_prompt, log, role, inbox)
            answer = log['action_answer']
            if answer.split('(')[0].strip().lower() in ('send', 'give') and self.coop:
                reward = self.coop_react(role, answer)
            else:
                reward = self.graph.react(answer)
        finally:
            scene.scene_relations = original_relations
            if home is not None and home.visible is ROLE_VISIBLE:  # a trigger's real value is kept
                home.visible = False
        log['response'] = reward.strip()
        log['completed_act'] = gv.completed_acts
        self.history.append(log)
        self.step_roles.append(role)
        self.step_role_index.append(self.role_steps[role])
        self.step_inbox.append(inbox)
        self.step_hint.append(deepcopy(hint))
        self.where[role] = self.graph.current_scene
        self.stacks[role] = self.scene_stack
        self.role_steps[role] += 1
        self.next_role = other(role)
        return 'game end' in reward.lower()

    # --------------------------------------------------------------- prompt
    def role_history(self, role, k):
        indices = [i for i, r in enumerate(self.step_roles) if r == role][-k:]
        prompt = ''
        for i in indices:
            h = self.history[i]
            prompt += f'History: [Step {self.step_role_index[i]}]\n'
            prompt += 'Your position: ' + h['position'] + '\n'
            for item in self.step_inbox[i]:
                prompt += 'Before this action, ' + item[0].lower() + item[1:] + '\n'
            prompt += 'Your action: ' + h['action_answer'] + '\n'
            prompt += 'Response from the environment: ' + h['response'] + '\n\n'
        return prompt

    def take_action(self, scene_prompt, log, role='A', inbox=()):
        """Original take_action with role-local history, step numbers and inbox."""
        step = log['step']
        position = log['position']
        role_step = self.role_steps[role]
        p1 = scene_prompt.find('Possible Actions:')
        log['scene'] = scene_prompt[:p1].strip()
        log['possible_actions'] = scene_prompt[p1:].strip()
        prompt = scene_prompt + '\n\n'
        if inbox:
            prompt += 'Updates from your partner since your last action:\n' + \
                ''.join(f'- {item}\n' for item in inbox) + '\n'
        if self.stuck:
            prompt += self.form_helper_prompt(position, position, self.current_hint['action'])
        prompt = (f'Now you need to act on [Step {role_step}]\nYour current position is: {position}.\n'
                  + prompt + 'Please try not to repeat previous actions that already fails, '
                  'and be creative to try different new actions. Your Response:\n')
        if not self.stuck and self.memory > 0 and role_step > 0:
            prompt = self.role_history(role, min(self.memory, role_step)) + prompt
        if self.stuck and self.stuck_in_help >= 10:
            action = self.current_hint['action']
        else:
            self.pending_generation = self.model_call(step, [
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user', 'content': prompt}])
            action = self.pending_generation['raw']
        log['action'] = action.strip()
        log['action_answer'] = find_last_call(action, self.action_names).strip()

    # ---------------------------------------------------------- coop react
    def coop_react(self, role, answer):
        partner = other(role)
        try:
            op = answer.split('(')[0].strip().lower()
            arg = answer.split('(', 1)[1].rsplit(')', 1)[0].strip()
            if op == 'send':
                text = arg.strip('"\'` ').strip()
                if len(text) > MAX_MESSAGE_CHARS:
                    raise ValueError(f'Message exceeds {MAX_MESSAGE_CHARS} characters; nothing delivered.')
                if not text:
                    raise ValueError('The message is empty.')
                self.inbox[partner].append(f'Your partner sent you a message: "{text}"')
                return 'Action executed successfully. Your message has been delivered to your partner.'
            name = next((n for n in self.bags[role].tools if n.lower() == arg.lower()), None)
            if name is None:
                raise ValueError(f'{arg.lower()} is not a tool in your bag.')
            self.bags[partner].add_tool(self.bags[role].tools.pop(name))
            self.inbox[partner].append(f'Your partner gave you the {name}. It is now in your bag.')
            return (f'Action executed successfully. You have given the {name} to your partner. '
                    'It is no longer in your bag.')
        except Exception as e:
            return f'Error raised during reaction: {e} Nothing happens.'

    def record(self):
        row = super().record()
        row.update(role=self.step_roles[-1], role_step=self.step_role_index[-1],
                   inbox=deepcopy(self.step_inbox[-1]), hint=deepcopy(self.step_hint[-1]),
                   bags={r: sorted(self.bags[r].tools) for r in 'AB'},
                   evaluation=deepcopy(self.evaluation_before))
        return row
