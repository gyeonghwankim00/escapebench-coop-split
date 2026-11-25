from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_collaboration import analyze
from scripts.run_matrix import summarize, PROTOCOL
from scripts.greedy_generation import GENERATION_VERSION, POLICY
from scripts.check_matrix_smoke import check

SPEC = dict(version='v3', A=['a'], B=['b'], reference_handoffs=[
    dict(tool='key', found_by='B', used_by='A', action='apply(key, lock)')])
CLUES = [dict(target='lock', target_scene='a', answer='1234',
              sources=[dict(object='note', scene='b', evidence=['1234'])])]


def row(role, text='', call='click(nothing)', inbox=(), bags=None, help=False, reachable=True, success=True):
    scene = 'a' if role == 'A' else 'b'
    observation = f'Scene Description: {text}'
    actions = 'Possible Actions: lock\nTools in Bag: empty'
    user = observation + '\n\n' + actions + '\n' + '\n'.join(inbox)
    return dict(role=role, upstream=dict(position=scene, scene=observation, possible_actions=actions,
        action_answer=call, response='Action executed successfully.' if success else 'Error: nothing happens.',
        tracking=dict(progress=0)), generation=dict(messages=[dict(role='user', content=user)]),
        inbox=list(inbox), bags=bags or {'A': [], 'B': []},
        evaluation=dict(scene=scene, bags_before={'A': [], 'B': []},
                        reachable_scenes={'A': ['a'], 'B': ['b'] if reachable else []}),
        helper_active=help, forced_action=False, hints_used=int(help), first_hint_progress=0 if help else None,
        hint=None)


class AnalysisTests(unittest.TestCase):
    def test_observe_deliver_use_and_keep_post_hint_actions_out_of_prefix(self):
        rows = [row('B', 'note: 1234', 'send(The lock code is 1234)'),
                row('A', inbox=['Your partner sent you a message: "The lock code is 1234"']),
                row('A', call='input(1234,lock)'),
                row('B', help=True), row('B', call='send(1234)')]
        report = analyze('fake', rows, SPEC, CLUES)
        before = report['before_first_hint']
        clue = before['clues'][0]
        self.assertEqual(clue['observations'][0]['observed_steps'], [0])
        self.assertEqual(clue['literal_received_candidate_steps'], [1])
        self.assertEqual(clue['stage_candidate'], 'resolved')
        self.assertEqual(before['messages'], 1)
        self.assertEqual(report['full_episode']['messages'], 2)
        self.assertEqual(report['first_help_row'], 3)

    def test_failed_send_hallucinated_thought_and_unreachable_are_not_discovery(self):
        r = row('B', 'note is blank', 'send(1234)', reachable=False, success=False)
        r['generation']['messages'][0]['content'] += '\nHistory: Your action: input(1234, lock)'
        result = analyze('fake', [r], SPEC, CLUES)['before_first_hint']
        self.assertEqual(result['clues'][0]['stage_candidate'], 'not_yet_reachable')
        self.assertEqual(result['clues'][0]['observations'][0]['observed_steps'], [])
        self.assertEqual(result['messages'], 0)

    def test_partial_literal_and_negated_message_need_review(self):
        rows = [row('B', 'note: 12345'), row('A', inbox=['Your partner sent you a message: "not 1234"'])]
        clue = analyze('fake', rows, SPEC, CLUES)['before_first_hint']['clues'][0]
        self.assertEqual(clue['observations'][0]['observed_steps'], [])
        self.assertEqual(clue['literal_received_candidate_steps'], [1])
        self.assertTrue(clue['needs_review'])
        self.assertFalse(clue['prerequisites_verified'])

    def test_forced_observation_is_not_a_model_observation(self):
        r = row('B', 'note: 1234', help=True)
        r['generation'] = None
        r['forced_action'] = True
        result = analyze('fake', [r], SPEC, CLUES)
        self.assertEqual(result['before_first_hint']['steps'], 0)
        self.assertEqual(result['full_episode']['clues'][0]['observations'][0]['observed_steps'], [])

    def test_object_transfer_must_be_successful_and_correct_direction(self):
        rows = [row('B', bags={'A': [], 'B': ['key']}),
                row('B', call='give(key)', bags={'A': [], 'B': ['key']}, success=False),
                row('A', call='give(key)', bags={'A': [], 'B': ['key']})]
        item = analyze('fake', rows, SPEC, [])['before_first_hint']['objects'][0]
        self.assertEqual(item['stage_candidate'], 'non_transfer_candidate')
        rows.extend([row('B', call='give(key)', bags={'A': ['key'], 'B': []}),
                     row('A', call='apply(key, lock)')])
        item = analyze('fake', rows, SPEC, [])['before_first_hint']['objects'][0]
        self.assertEqual(item['stage_candidate'], 'resolved')
        self.assertEqual(len(item['transfers']), 1)

    def test_clue_carried_in_a_tool_is_recorded_without_a_message(self):
        rows = [row('B', 'note: 1234', 'give(note)', bags={'A': ['note'], 'B': []}), row('A')]
        up = rows[1]['upstream']
        up['possible_actions'] = 'Possible Actions:\nTools in Bag:\n<applicable tool> note: 1234'
        rows[1]['generation']['messages'][0]['content'] = up['scene'] + '\n\n' + up['possible_actions']
        clue = analyze('fake', rows, SPEC, CLUES)['before_first_hint']['clues'][0]
        self.assertEqual(clue['object_carried_candidate_steps'], [1])
        self.assertEqual(clue['literal_received_candidate_steps'], [])
        self.assertEqual(clue['stage_candidate'], 'non_uptake_candidate')

    def test_craft_argument_order_is_not_a_false_non_use(self):
        spec = deepcopy(SPEC)
        spec['reference_handoffs'] = [dict(tool='x + y', found_by='both', used_by='either', action='craft(x, y)')]
        result = analyze('fake', [row('A', call='craft(y,x)')], spec, [])
        self.assertEqual(result['before_first_hint']['objects'][0]['stage_candidate'], 'resolved')

    def test_hint_on_first_row_has_empty_autonomous_prefix(self):
        rows = [row('B', call='send(code)', help=True), row('A', call='send(reply)')]
        result = summarize('coop', 'fake', rows, 'step_budget', None, 1)
        self.assertEqual(result['messages_before_first_hint'], 0)
        self.assertEqual(result['autonomous_prefix_steps'], 0)
        self.assertEqual(result['non_helper_mode_steps'], 1)


class SmokeTests(unittest.TestCase):
    def fixture(self, root):
        m = dict(protocol=PROTOCOL, generation_version=GENERATION_VERSION, conditions=['solo', 'coop'],
                 games=['one', 'two'], settings={'max_steps': 70})
        (root/'experiment.json').write_text(json.dumps(m))
        (root/'timing.jsonl').write_text(json.dumps(dict(batches=70, batch_seconds=100)) + '\n')
        for condition in m['conditions']:
            for game in m['games']:
                d = root/condition/game
                d.mkdir(parents=True)
                (d/'summary.json').write_text(json.dumps(dict(stop_reason='step_budget', steps=70)))
                rows = [row('A' if i % 2 == 0 else 'B') for i in range(70)]
                for r in rows:
                    r['generation']['effective_generation'] = dict(version=GENERATION_VERSION,
                        mode='greedy_search', use_model_defaults=False, config=POLICY)
                (d/'turns.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
                (d/'collaboration.json').write_text('{}')

    def test_pass_only_real_audited_finished_episodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            self.assertEqual(check(root)['checked_model_calls'], 280)
            path = root/'solo/one/turns.jsonl'
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            rows[0]['generation']['effective_generation']['config']['do_sample'] = True
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            with self.assertRaisesRegex(ValueError, 'effective generation'):
                check(root)

    def test_interruption_blocks_dependent_experiments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root/'coop/two/summary.json').write_text(json.dumps(dict(stop_reason='interrupted', steps=60)))
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                check(root)


if __name__ == '__main__':
    unittest.main()
