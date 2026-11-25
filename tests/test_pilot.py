import json
from pathlib import Path
import unittest

from scripts.coop_escape import World, replay
from scripts.validate_pilot import validate

ROOT = Path(__file__).resolve().parents[1]
PATHS = sorted((ROOT/'data/pilot').glob('*/environment.json'))


class PilotTests(unittest.TestCase):
    def test_eight_valid_replayable_instances(self):
        self.assertEqual(len(PATHS), 8)
        for path in PATHS:
            with self.subTest(instance=path.parent.name):
                self.assertTrue(validate(path)['both_exits_open'])

    def test_remote_access_is_rejected_without_identity_leak(self):
        for path in PATHS:
            w = World(path)
            for actor, other in [('A','B'),('B','A')]:
                remote_zone = next(z['name'] for z in w.zones.values() if z['room'] == other)
                before = w.location[actor]
                self.assertFalse(w.step(actor, {'type':'move','target':remote_zone})['valid'])
                self.assertEqual(w.location[actor], before)
                remote = next(e['name'] for e in w.entities.values() if e['room'] == other)
                result = w.step(actor, {'type':'click','target':remote})
                unknown = w.step(actor, {'type':'click','target':'NONEXISTENT'})
                self.assertFalse(result['valid'])
                self.assertEqual(result['feedback'], unknown['feedback'])

    def test_hidden_clues_not_exposed_at_start(self):
        for path in PATHS:
            w = World(path)
            for actor in 'AB':
                observation = w.observe(actor)
                text = json.dumps(observation)
                self.assertNotIn('annotations', text)
                self.assertNotIn('wait_for', text)
                self.assertNotIn('trigger', text)
                self.assertNotIn('accepted_input', text)
                self.assertFalse(w.exposures[actor])
                for c in w.spec['annotations']['information_links']:
                    for token in c['evidence_text']:
                        self.assertNotIn(token, text)
                for z in w.zones.values():
                    if z['room'] == actor and not z.get('visible', True):
                        self.assertFalse(w.step(actor, {'type':'move','target':z['name']})['valid'])

    def test_hatch_requires_possession_and_transfers_exclusive_ownership(self):
        for path in PATHS:
            w = World(path)
            # Advance through the legitimate reveal path to the first pickup.
            for row in json.loads(path.with_name('reference.json').read_text()):
                a = row['action']
                if a['type'] == 'click' and w.entities[a['target']]['kind'] == 'tool':
                    entity = w.entities[a['target']]
                    break
                w.step(row['actor'], a)
            else:
                self.fail('No tool pickup in witness')
            actor = entity['room']; other = 'B' if actor == 'A' else 'A'; name = entity['name']
            self.assertFalse(w.step(actor, {'type':'pass','tool':name})['valid'])
            w.step(actor, {'type':'move','target':entity['zone']})
            self.assertTrue(w.step(actor, {'type':'click','target':name})['effect'])
            self.assertTrue(w.step(actor, {'type':'pass','tool':name})['effect'])
            self.assertNotIn(name, w.bags[actor]); self.assertIn(name, w.bags[other])
            self.assertFalse(w.step(actor, {'type':'pass','tool':name})['valid'])
            self.assertTrue(w.step(other, {'type':'pass','tool':name})['effect'])

    def test_messages_are_explicit_and_worlds_are_independent(self):
        for path in PATHS:
            one, two = World(path), World(path)
            one.step('A', {'type':'send','message':'Test message from A.'})
            self.assertEqual(len(one.observe('B')['messages']), 1)
            self.assertEqual(one.observe('A')['messages'], [])
            self.assertEqual(two.observe('B')['messages'], [])
            changed = one.observe('B'); changed['messages'][0]['text'] = 'tampered'
            self.assertEqual(one.observe('B')['messages'][0]['text'], 'Test message from A.')

    def test_incoming_guess_does_not_count_as_source_discovery(self):
        for path in PATHS:
            w = World(path)
            for clue in w.spec['annotations']['information_links']:
                w.step(clue['receiver'], {'type':'send', 'message':' '.join(clue['evidence_text'])})
                w.observe(clue['holder'])
                self.assertNotIn(clue['id'], w.exposures[clue['holder']])

    def test_omitting_hatch_breaks_path_but_original_exit_can_be_guessed(self):
        # Negative control for the witness, not an exhaustive no-hatch solver.
        for path in PATHS:
            w = World(path)
            rows = json.loads(path.with_name('reference.json').read_text())
            failures = 0
            for row in rows:
                if row['action']['type'] != 'pass':
                    result = w.step(row['actor'], row['action'])
                    failures += not (result['valid'] and result['effect'])
            self.assertGreater(failures, 0)
            self.assertEqual(w.success, path == PATHS[0], path.parent.name)

    def test_reference_without_messages_is_a_known_guessing_bypass(self):
        # The scripted witness knows the answers. Do not claim communication is
        # logically enforced simply because a no-message LLM baseline fails.
        for path in PATHS:
            w = World(path)
            for row in json.loads(path.with_name('reference.json').read_text()):
                if row['action']['type'] != 'send':
                    w.step(row['actor'], row['action'])
            self.assertTrue(w.success)
            self.assertFalse(w.inbox['A']); self.assertFalse(w.inbox['B'])

    def test_partial_tool_application_does_not_reveal_paper(self):
        path = PATHS[2]
        w = World(path)
        for row in json.loads(path.with_name('reference.json').read_text()):
            result = w.step(row['actor'], row['action'])
            if row['action'] == {'type':'apply','tool':'connector','target':'tool box'}:
                self.assertTrue(result['effect'])
                self.assertFalse(w.entities['paper 2']['visible'])
                self.assertNotIn('870472', json.dumps(result))
                break
        else:
            self.fail('Missing multi-tool transition in reference')

    def test_original_papers_remain_collectible(self):
        for path in PATHS:
            w = World(path)
            for e in w.entities.values():
                self.assertEqual(e['kind'], e['source']['kind'])

    def test_locked_parent_blocks_visible_child(self):
        w = World(PATHS[0])
        # The source marks the close-up visible, but the study entrance is locked.
        self.assertTrue(w.zones['photo close-up']['visible'])
        self.assertFalse(w.zones['study']['visible'])
        self.assertNotIn('photo close-up', w.observe('A')['areas'])
        self.assertFalse(w.step('A', {'type':'move', 'target':'photo close-up'})['valid'])
        for row in json.loads(PATHS[0].with_name('reference.json').read_text()):
            w.step(row['actor'], row['action'])
            if row['action']=={'type':'click','target':'left door to the study'}:
                break
        self.assertIn('photo close-up', w.observe('A')['areas'])

    def test_source_object_conversion_adds_tool_to_acting_inventory(self):
        for path, target, tool in [(PATHS[3], 'unfunctional drill', 'electric drill'),
                                   (PATHS[6], 'torch light', 'torch light with power')]:
            w = World(path)
            for row in json.loads(path.with_name('reference.json').read_text()):
                w.step(row['actor'], row['action'])
                if tool in w.bags[row['actor']]:
                    self.assertFalse(w.entities[target]['visible'])
                    self.assertFalse(w.entities[tool]['visible'])
                    break
            else:
                self.fail(f'Converted tool missing: {tool}')

    def test_wrong_input_has_no_effect_or_answer_leak(self):
        for path in PATHS:
            w = World(path)
            # Reach an input through the real gate/unlock sequence.
            for row in json.loads(path.with_name('reference.json').read_text()):
                if row['action']['type']=='input':
                    actor = row['actor']; name = row['action']['target']
                    before = w.entities[name]['state']
                    result = w.step(actor, {'type':'input','target':name,'value':'WRONG'})
                    self.assertTrue(result['valid']); self.assertFalse(result['effect'])
                    self.assertEqual(w.entities[name]['state'], before)
                    self.assertNotIn(row['action']['value'], result['feedback'])
                    break
                w.step(row['actor'], row['action'])



if __name__ == '__main__':
    unittest.main()
