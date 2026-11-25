"""Evaluator-only evidence ledger for reference witnesses, never a model prompt.

Records visible source text/actual discovery feedback and successful messages.
An input must have annotated evidence available to its actor before execution.
This proves an executable, informed witness, not independent puzzle reasoning.
"""
from collections import deque


def norm(text):
    return ' '.join(str(text).replace('\\n', ' ').lower().split())


def key(source):
    return (source['scene'], source['object'], tuple(source['evidence']))


def contains(text, source):
    return all(norm(e) in norm(text) for e in source['evidence'])


class EvidenceLedger:
    def __init__(self, clues):
        self.clues = clues
        self.sources = {key(s): s for c in clues for s in c['sources']}
        self.known = {r: {} for r in 'AB'}
        self.checks = []
        self.transmissions = []
        self.pending = None
        self.prompt = ''
        self.queues = {}
        self.sent_chunks = {}

    def remember(self, role, source, text, step, via):
        if contains(text, source) and norm(text) in self.prompt:
            self.known[role].setdefault(key(source), dict(role=role, source=source,
                text=text, observed_decision=step, via=via))

    def observe(self, agent, messages, roles, step):
        self.prompt = norm('\n'.join(m['content'] for m in messages))
        if self.pending:
            action, sender, receiver, source, payload, decision = self.pending
            last = agent.history[-1]
            assert last['action_answer'] == action and last['response'] == (
                'Action executed successfully. Your message has been delivered to your partner.'), last
            task = (sender, receiver, key(source))
            self.sent_chunks.setdefault(task, []).append(payload)
            if not self.queues[task]:
                payloads = self.sent_chunks.pop(task)
                record = dict(self.known[sender][key(source)], role=receiver, via='message',
                              sender=sender, send_decision=decision, payloads=payloads)
                assert contains(''.join(payloads), source)
                self.known[receiver][key(source)] = record
                self.transmissions.append(record)
                del self.queues[task]
            self.pending = None
        for role in roles:
            scene_name = agent.where[role]
            if scene_name:
                scene = agent.graph.scenes[scene_name]
                for source in self.sources.values():
                    if source['scene'] != scene_name:
                        continue
                    if source['object'] == '@' + scene_name:
                        self.remember(role, source, scene.desc, step, 'scene')
                    wrapper = scene.items.get(source['object']) or scene.tools.get(source['object'])
                    if wrapper:
                        obj = wrapper.get('item') or wrapper.get('tool')
                        if obj.visible:
                            self.remember(role, source, obj.current_desc(), step, 'visible_object')
            for source in self.sources.values():
                tool = agent.bags[role].tools.get(source['object'])
                if tool:
                    self.remember(role, source, tool.current_desc(), step, 'bag')
                for event in agent.discoveries[role]:
                    target = event['action'].split('(', 1)[-1].rstrip(')').split(',')[-1].strip()
                    if event['scene'] == source['scene'] and target == source['object']:
                        self.remember(role, source, event['text'], step, 'action_feedback')

    def matching(self, action, scene):
        if not action.startswith('input('):
            return []
        answer, target = action[6:-1].rsplit(',', 1)
        matches = [c for c in self.clues if c['target_scene'] == scene
                   and c['target'] == target.strip() and str(c['answer']) == answer.strip()]
        assert matches, ('Unannotated input', scene, action)
        return matches

    def require(self, role, action, scene, step, shared=False):
        for clue in self.matching(action, scene):
            records = []
            for source in clue['sources']:
                record = self.known[role].get(key(source))
                if shared:
                    record = record or self.known['B' if role == 'A' else 'A'].get(key(source))
                assert record, ('Missing observed evidence', step, role, action, source)
                # Historical knowledge alone is insufficient if all of it fell out of context.
                present = (all(norm(p) in self.prompt for p in record['payloads'])
                           if record['via'] == 'message' else contains(self.prompt, source))
                assert present, ('Evidence absent from current prompt', step, role, action, source)
                records.append(record)
            self.checks.append(dict(decision=step, role=role, action=action, sources=records))

    def message(self, sender, receiver, source, step):
        record = self.known[sender].get(key(source))
        assert record, ('Sender never observed clue', sender, source)
        task = (sender, receiver, key(source))
        if task not in self.queues:
            # Preserve all source text, including diagrams and formatting. Long clues
            # use multiple real send actions; never replace them with evaluator answers.
            text = record['text'].strip().replace('\n', '\\n')
            assert contains(text, source)
            self.queues[task] = deque(text[i:i+280] for i in range(0, len(text), 280))
        payload = self.queues[task].popleft()
        assert contains(self.prompt, source), ('Sender evidence no longer in context', source)
        action = 'send(' + payload + ')'
        self.pending = (action, sender, receiver, source, payload, step)
        return action
