"""One controller sees both local observations in the SAME split environment as Peer."""
from copy import deepcopy
from scripts.coop_original import CoopAgent, other, ROLE_VISIBLE, BASE_ACTIONS, gv
from scripts.original_escape import SYS_PROMPT_COT

SOLO_RULE = '''You are the single controller of BOTH roles A and B in the split environment.
You receive both roles' current local observations and recent action/feedback histories.
The environment schedules one active role per team turn. Output exactly one action for that
active role, using its local scene actions and ONE shared bag. The other observation is
information, not permission to act there during this turn. Every collected tool enters the
same shared bag immediately, regardless of which role collected it. Either role can use or
craft these tools on its turn. Using or consuming a tool updates this one bag for both roles.
Both roles share you as their controller, so you already know the information shown for either
role. Decide directly from these observations and histories. Do not ask either role for
information, instructions, permission, or tools: you control both. If a future turn requires
the other role to collect a tool, perform that collection on the other role's turn.
Text messaging and tool transfers are unnecessary and unavailable: send and give are invalid
and consume the turn without changing the environment. Allowed actions are click, apply,
input, craft, and move. Collection, use, crafting, movement, and failed actions each cost
one team action. Reading both observations and accessing the shared bag cost no extra action.
Unexplored or hidden contents are not revealed. The team escapes when either role completes
the final escape.'''


def solo_system_prompt():
    marker = '\n\nHere are some reminders'
    assert SYS_PROMPT_COT.count(marker) == 1
    return SYS_PROMPT_COT.replace(marker, '\n\n' + SOLO_RULE + marker)


class CentralSoloAgent(CoopAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.system_prompt = solo_system_prompt()
        self.allowed_actions = tuple(BASE_ACTIONS)
        # Keep recognizing forbidden send/give calls in the parser, so they become an
        # explicit invalid action rather than falling back to an earlier call.

    def setup(self, controller, game_name):
        super().setup(controller, game_name)
        # One actual Bag object, not synchronized copies: stateful/consumed tools
        # must change once and immediately be the same from either viewpoint.
        self.shared_bag = gv.bag
        self.bags = {r: self.shared_bag for r in 'AB'}

    def plan_hint(self):
        # Tools are already shared. Never synthesize a give hint (including for
        # crafting); execute the original target at its owning role's scene.
        ref = self.helper[0]
        path = ref['position'].split(' -> ')
        return dict(role=self.owner[path[-1]], action=ref['action_answer'],
                    path=path, kind='reference')

    def record(self):
        row = super().record()
        row.update(inventory_mode='shared', shared_bag=sorted(self.shared_bag.tools))
        # `bags` remains a compatibility view of each role's accessible tools,
        # not two inventories to sum. The explicit shared_bag is canonical.
        return row

    def role_history(self, role, k):
        return ''  # attached centrally, also on B's first turn and during help

    def coop_react(self, role, answer):
        op = answer.split('(', 1)[0].strip().lower()
        if op in ('send', 'give'):
            return (f'Error raised during reaction: {op} is unavailable for the single controller. '
                    'Use both roles\' observations directly and choose an allowed action on the '
                    'active role\'s turn with the shared bag. Nothing happens.')
        return super().coop_react(role, answer)

    def central_history(self):
        # Same retention per role as Peer: 10 actions for A and 10 for B.
        return ''.join(f'Recent history for role {r}:\n' +
                       (super(CentralSoloAgent, self).role_history(r, self.memory) or '(none)\n')
                       for r in 'AB')

    def partner_observation(self, role):
        partner = other(role)
        origin = self.where[partner]
        if origin is None:
            return f'Role {partner} currently has no accessible position.'
        scene = self.graph.scenes[origin]
        relations, cache = scene.scene_relations, deepcopy(scene.action_cache)
        bag = self.bags[partner]
        bag_cache = deepcopy(bag.action_cache)
        home = self.graph.scenes.get(self.role_starts.get(partner))
        # Do not call Graph.describe(): it resets per-turn progress flags.
        if home is not None and not home.visible:
            home.visible = ROLE_VISIBLE
        try:
            scene.scene_relations = self.role_relations(partner, origin)
            actions, _ = scene.actions(self.graph.use_index)
            text = (f'Your current position is: {origin}.\nScene Description:\n'
                    + scene.describe().strip() + '\n\nPossible Actions:\n' + actions.strip())
            if self.inbox[partner]:
                text += '\nPending partner updates:\n' + '\n'.join(self.inbox[partner])
            return text
        finally:
            scene.scene_relations, scene.action_cache = relations, cache
            bag.action_cache = bag_cache
            if home is not None and home.visible is ROLE_VISIBLE:
                home.visible = False

    def take_action(self, scene_prompt, log, role='A', inbox=()):
        # Present the bag once, after the active scene; both views use this bag.
        scene_prompt = scene_prompt.replace('Tools in Bag:', 'Shared Bag (usable from A or B):', 1)
        observation = self.partner_observation(role)
        original_call = self.model_call
        def central_call(step, messages):
            messages = deepcopy(messages)
            content = messages[-1]['content']
            # Preserve the active observation exactly; label the two views explicitly.
            content = content.replace(scene_prompt, f'=== Active role {role}: act here ===\n' + scene_prompt, 1)
            messages[-1]['content'] = (f'Team turn {step}; active role: {role}.\n'
                + f'=== Role {other(role)}: information only this turn ===\n{observation}\n\n'
                + self.central_history() + content)
            return original_call(step, messages)
        self.model_call = central_call
        try:
            return super().take_action(scene_prompt, log, role, inbox)
        finally:
            self.model_call = original_call
