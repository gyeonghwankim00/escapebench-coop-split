"""Cost-aware split protocol. Legacy adapters and vendor remain reproducible."""
from copy import deepcopy
import re
from scripts.coop_original import CoopAgent, gv, other, ROLE_VISIBLE, BASE_ACTIONS, COOP_PARAGRAPH
from scripts.central_solo import CentralSoloAgent
from scripts.original_escape import SYS_PROMPT_COT

RULES = '''Explore all accessible areas, not just the currently blocked puzzle. Revisit earlier
locations and retry failed actions when tools, clues, or world state change.
Saved observations are dated snapshots, not live views. An absent update does not prove that
nothing changed elsewhere. Only the current views and current bag are live.
Use the condition-specific output format below. Put executable commands only on Action:.
Each environment action, including an invalid action, costs 1. There is a separate decision budget.
'''
PEER_RULES = '''You may continue for at most 4 consecutive decisions, then your partner gets a turn.
yield() hands over this opportunity only; you will be scheduled again even without a message.
Successful send(message) and give(tool) also hand over control. Both yielding is not termination.
A valid yield() costs 0 environment actions but consumes one decision/model call.
Messages may contain parentheses and action examples. Maximum message length: 300
characters; longer messages are rejected, never silently truncated.
You see only your own current scene, bag, saved observations, history and received messages.
'''
SOLO_RULES = '''You are the single controller of BOTH A and B. Choose the acting role freely on every
decision, then one action at that role's current location. Output Role: A or Role: B on a
separate line before Action:. You see both current views and both saved memories. ONE shared
bag contains every collected tool and is immediately usable at either location. Consumption
and crafting update this single bag. send, give and yield are unavailable. Hidden scenes and
objects are not revealed. Escape succeeds when the original final escape action succeeds.
'''


def parse_action(text):
    """Parse exactly one explicit outer action; never execute calls inside text."""
    lines = re.findall(r'^\s*Action:\s*(.*?)\s*$', text, re.M)
    if len(lines) != 1:
        return 'No action'
    value = lines[0]
    # Greedy outer match intentionally permits parentheses in opaque send text.
    match = re.fullmatch(r'([A-Za-z_]+)\((.*)\)', value)
    if not match:
        return 'No action'
    op, arg = match.groups()
    if op != 'send' and ('(' in arg or ')' in arg):
        return 'No action'
    return value


def compact_discovery(answer, reward):
    """Drop engine boilerplate that only restates the action; keep the puzzle's own text.

    Removes exact template strings rebuilt from the action arguments, so an
    unexpected spelling simply leaves the original text in place.
    """
    text = reward.strip()
    match = re.fullmatch(r'([a-z]+)\((.*)\)', answer.strip())
    if match:
        op, args = match.group(1), [a.strip() for a in match.group(2).split(',')]
        templates = {'click': lambda a: [f'You have clicked on {a[0]}.'],
                     'apply': lambda a: [f'You have successfully applied {a[0]} to {a[1]}.'] if len(a) == 2 else [],
                     'input': lambda a: [f'You have given an input {a[0]} to {a[1]}.'] if len(a) == 2 else []}
        for template in templates.get(op, lambda a: [])(args):
            text = text.replace(template, '', 1)
    text = text.replace('Action executed successfully.', '')
    lines = [l for l in text.splitlines() if not l.strip().startswith('You have successfully crafted ')]
    text = ' '.join(l.strip() for l in lines if l.strip())
    return text or 'Succeeded.'


class AdaptiveMixin:
    centralized = False
    burst_limit = 4
    # discoveries: feedback of actions that completed a new key step (engine
    # key_steps counter rose: first-time click/apply/input transition or craft).
    # Tool pickups are excluded; the bag already describes held tools.
    # One-time reveals such as game2-2's
    # drawer "1040" exist only in that feedback, so they are never overwritten
    # by later repeats and are not competed for by ordinary feedback.
    memory_budgets = dict(observations=4000, discoveries=3000, received=1500, feedback=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.help_policy = 'none'
        self.max_decisions = self.max_steps * 2
        base = SYS_PROMPT_COT.split('Please respond in two lines.')[0].rstrip()
        base = base.replace('2. Avoid repeating actions done before, avoid going back and forth between scenes, try to do new actions, explore new scenes, find or craft new tools.',
            '2. Avoid repeating a failed action without a reason. Retry or revisit when tools, clues, or world state change; explore other accessible areas when blocked.')
        output = ('Respond in exactly three lines:\nThought: brief plan and reason\nRole: A or B\nAction: one command'
                  if self.centralized else 'Respond in exactly two lines:\nThought: brief plan and reason\nAction: one command')
        self.system_prompt = base + '\n\n' + (SOLO_RULES if self.centralized else COOP_PARAGRAPH+'\n'+PEER_RULES) + RULES + '\n' + output

    def setup(self, controller, game_name):
        super().setup(controller, game_name)
        self.notebook = {r: {} for r in 'AB'}
        self.received = {r: [] for r in 'AB'}
        self.feedback_memory = {r: {} for r in 'AB'}
        self.discoveries = {r: [] for r in 'AB'}
        self.cost = 0
        self.burst_role, self.burst = None, 0
        self.last_yield = False
        self.budget_stop = None

    def view(self, role):
        origin = self.where[role]
        if origin is None:
            return 'No accessible position.'
        scene = self.graph.scenes[origin]
        rel, cache = scene.scene_relations, deepcopy(scene.action_cache)
        home = self.graph.scenes.get(self.role_starts.get(role))
        visible = home.visible if home is not None else None
        if home is not None and not home.visible:
            home.visible = ROLE_VISIBLE
        try:
            scene.scene_relations = self.role_relations(role, origin)
            actions, _ = scene.actions(False)
            return scene.describe().strip()+'\nPossible Actions:\n'+actions
        finally:
            scene.scene_relations, scene.action_cache = rel, cache
            if home is not None:
                home.visible = visible

    def saved_memory(self, roles, current_views=()):
        """Same independent category budgets per role in Solo and Peer.

        Current views are already rendered live. Old observations retain prose,
        not stale action menus. Errors remain in recent history and full logs.
        """
        sections=[];self.memory_selection={}
        for r in roles:
            categories={k:[] for k in self.memory_budgets}
            for scene,snapshot in self.notebook[r].items():
                if r in current_views and scene==self.where[r]:continue
                text=snapshot['text'].split('Possible Actions:',1)[0].strip()
                categories['observations'].append((snapshot['decision'],f"Role {r}; {scene}; last seen {snapshot['decision']}:\n{text}"))
            # Keep latest occurrence of an identical received update.
            unique={text:step for step,text in self.received[r]}
            for text,step in unique.items():
                categories['received'].append((step,f'Role {r}; received {step}: {text}'))
            for event in self.discoveries[r]:
                categories['discoveries'].append((event['decision'],f"{r} {event['decision']} {event['scene']} / {event['action']}: {event['text']}"))
            for key,event in self.feedback_memory[r].items():
                if event['text'].startswith(('Error','Nothing happens')) or event.get('discovery'):continue
                categories['feedback'].append((event['decision'],f"Role {r}; feedback {event['decision']}; {key}: {event['text']}"))
            self.memory_selection[r]={}
            for category,entries in categories.items():
                chosen=[];used=0;times=[]
                for step,text in sorted(entries,key=lambda e:e[0],reverse=True):
                    if used+len(text)<=self.memory_budgets[category]:
                        chosen.append(text);used+=len(text);times.append(step)
                omitted=len(entries)-len(chosen)
                self.memory_selection[r][category]=dict(chars=used,selected=len(chosen),omitted=omitted,decisions=times)
                sections.append(f'Saved {category} for {r} (dated, not live; omitted {omitted}):\n'+'\n\n'.join(chosen))
        return '\n\n'.join(sections)+'\n'

    def act(self, step):
        self.pending_generation = None
        self.help_before, self.forced_before = self.stuck, False
        hint = self.plan_hint() if self.stuck else None
        self.current_hint = hint
        key = (hint['role'],hint['action']) if hint else None
        if key != self.hint_key:
            self.stuck_in_help = 0
            self.hint_key = key
        role = hint['role'] if hint else self.pick_role()
        if hint and hint['path']:
            self.where[role] = hint['path'][-1]  # assisted teleport precedes observation
        candidates = list('AB') if self.centralized and not hint else [role]
        views = {}
        for r in candidates:
            views[r] = self.view(r)
            if self.where[r] is not None:
                self.notebook[r][self.where[r]] = dict(decision=step,text=views[r])
        roles = 'AB' if self.centralized else [role]
        for r in roles:
            for message in self.inbox[r]:
                self.received[r].append((step,message))
        inbox = list(self.inbox[role])
        if self.centralized:
            for r in 'AB':self.inbox[r]=[]
        else:
            self.inbox[role]=[]
        prompt = f'Decision {step}; environment actions {self.cost}/{self.max_steps}; decision limit {self.max_decisions}.\n'
        prompt += ('Choose Role: A or Role: B.\n' if self.centralized and not hint else f'Active role: {role}.\n')
        prompt += self.saved_memory(roles, views)
        for r in roles:
            prompt += f'\nRecent actions for {r}:\n'+CoopAgent.role_history(self,r,self.memory)
        for r,text in views.items():prompt+=f'\nCURRENT VIEW {r}:\n{text}\n'
        if self.centralized:
            prompt+='\nSHARED BAG:\n'+self.shared_bag.describe(False)
        else:
            prompt+='\nYOUR BAG:\n'+self.bags[role].describe(False)
        if hint:
            self.stuck_in_help += 1
            prompt+='\n'+self.form_helper_prompt('',hint['path'][-1] if hint['path'] else self.where[role],hint['action'])
        if hint and self.stuck_in_help >= 10:
            answer=hint['action'];raw='Role: '+role+'\nAction: '+answer;self.forced_before=True
        else:
            self.pending_generation=self.model_call(step,[dict(role='system',content=self.system_prompt),dict(role='user',content=prompt)])
            raw=self.pending_generation['raw'];answer=parse_action(raw)
            if self.centralized and not hint:
                selected=re.findall(r'^\s*Role:\s*([AB])\s*$',raw,re.M)
                if len(selected)==1 and self.where[selected[0]] is not None:role=selected[0]
                else:answer='No action'
        self.active_role=role
        gv.bag=self.bags[role]
        if self.where[role] is not None:self.graph.current_scene=self.where[role]
        self.scene_stack=self.stacks[role]
        if hint and hint['path']:
            self.graph.current_scene=hint['path'][-1]
        self.update_scene_stack()
        scene=self.graph.scenes[self.graph.current_scene]
        rel=scene.scene_relations
        scene.scene_relations=self.role_relations(role,scene.name)
        before_visibility={n:s.visible for n,s in self.graph.scenes.items()}
        home=self.graph.scenes.get(self.role_starts.get(role))
        if home is not None and not home.visible:home.visible=ROLE_VISIBLE
        key_steps_before=gv.count.key_steps
        action_scene=scene.name
        try:
            scene_prompt=self.graph.describe().strip()
            self.evaluation_before=self.evaluation_snapshot()
            op=answer.split('(',1)[0]
            valid_yield=answer=='yield()' and not self.centralized
            if valid_yield:reward='Action executed successfully. Control yielded temporarily; you will receive another opportunity.'
            elif op in ('send','give') and not self.centralized:reward=self.coop_react(role,answer)
            elif op in BASE_ACTIONS:reward=self.graph.react(answer)
            else:reward='Error raised during reaction: invalid action or role. Nothing happens.'
        finally:
            scene.scene_relations=rel
            if home is not None and home.visible is ROLE_VISIBLE:home.visible=False
        discovery=gv.count.key_steps>key_steps_before
        self.feedback_memory[role][self.graph.current_scene+' / '+answer] = dict(decision=step,text=reward,discovery=discovery)
        if discovery:
            self.discoveries[role].append(dict(decision=step,scene=action_scene,action=answer,text=compact_discovery(answer,reward)))
        self.cost += not valid_yield
        log=dict(step=step,position=self.format_scene_stack(),scene=views[role].split('Possible Actions:')[0].strip(),
                 possible_actions='Possible Actions:'+views[role].split('Possible Actions:',1)[1],
                 action=raw,action_answer=answer,response=reward.strip(),completed_act=deepcopy(gv.completed_acts))
        self.history.append(log)
        self.step_roles.append(role);self.step_role_index.append(self.role_steps[role])
        self.step_inbox.append(inbox);self.step_hint.append(deepcopy(hint))
        self.where[role]=self.graph.current_scene;self.stacks[role]=self.scene_stack;self.role_steps[role]+=1
        self.burst=self.burst+1 if self.burst_role==role else 1;self.burst_role=role
        handover=valid_yield or (op in ('send','give') and reward.startswith('Action executed successfully')) or self.burst>=self.burst_limit
        self.next_role=other(role) if handover else role
        if handover:self.burst=0
        self.last_yield=valid_yield
        # Global state changes are evaluator-only, never omniscient notifications.
        self.world_changes=[n for n,s in self.graph.scenes.items() if bool(s.visible)!=bool(before_visibility[n])]
        return 'game end' in reward.lower()

    def iterate(self, controller, game_name):
        self.setup(controller,game_name)
        last_gain=0
        for step in range(self.max_decisions):
            previous=gv.count.key_steps+gv.count.tool_collected
            escaped=self.act(step)
            total=self.key_step_num+self.tool_num
            progress=round((gv.count.key_steps+gv.count.tool_collected)*100/total,2)
            self.history[-1]['tracking']=dict(key_steps=gv.count.key_steps,tool_collected=gv.count.tool_collected,
                total_keys=self.key_step_num,total_tools=self.tool_num,progress=progress)
            if gv.count.key_steps+gv.count.tool_collected>previous:
                last_gain=self.cost
                for ref in list(self.helper):
                    if self.same_action(ref['action_answer'],self.history[-1]['action_answer']) and (self.same_position(ref['position'],self.history[-1]['position']) or ref['action_answer'].startswith('craft(')):
                        self.helper.remove(ref)
                        if self.stuck:self.stuck=False;self.stuck_in_help=0
                        break
            if self.help_policy=='original' and not self.stuck and self.helper and self.cost-last_gain>=50:
                self.stuck=True;self.help_cnt+=1;last_gain=self.cost
                if self.first_hint_progress is None:self.first_hint_progress=progress
            done=escaped or self.cost>=self.max_steps or step+1>=self.max_decisions
            if done:self.budget_stop='success' if escaped else 'step_budget' if self.cost>=self.max_steps else 'decision_budget'
            yield
            if done:return escaped,step+1
        return False,len(self.history)

    def record(self):
        row=super().record()
        row.update(memory_selection=deepcopy(self.memory_selection),environment_actions=self.cost,action_cost=0 if self.last_yield else 1,
                   decision=len(self.history)-1,world_changed_scenes=self.world_changes,
                   observed_memory=deepcopy(self.notebook),received_memory=deepcopy(self.received),
                   feedback_memory=deepcopy(self.feedback_memory),discovery_memory=deepcopy(self.discoveries))
        # Peer must never log partner memory as evidence supplied to its model;
        # these dictionaries are evaluator records, actual prompts are authoritative.
        return row


class AdaptivePeer(AdaptiveMixin,CoopAgent):
    pass


class AdaptiveSolo(AdaptiveMixin,CentralSoloAgent):
    centralized=True
