"""GPU-free tests for prompt isolation, parsing, budgets and streaming logs."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.coop_escape import World
from scripts.run_model import format_observation, make_messages, make_solo_world, parse_action, run_episode
from scripts.run_solo_suite import run_suite

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT/'data/pilot/01_mirror_workshop/environment.json'


class FakeBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []

    def generate(self, system, actor, observation, history, history_turns):
        messages = make_messages(system,actor,observation,history,history_turns)
        self.seen.append((actor,messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return dict(raw=response,messages=messages,input_tokens=10,output_tokens=5,seconds=0.01)


class ModelRunnerTests(unittest.TestCase):
    def test_suite_continues_after_an_episode_error(self):
        other = ROOT/'data/pilot/02_records_billiards/environment.json'
        backend = FakeBackend([RuntimeError('one episode failed'), '{"type":"wait"}'])
        with tempfile.TemporaryDirectory() as temp:
            results = run_suite([DATASET, other], backend, Path(temp), 1, 10, [False], 42)
            self.assertEqual([r['stop_reason'] for r in results], ['error', 'budget_exhausted'])
            self.assertTrue((Path(temp)/other.parent.name/'turns.jsonl').is_file())
            self.assertEqual(json.loads((Path(temp)/'suite_summary.json').read_text())['planned'], 2)

    def test_solo_reference_replays_with_one_inventory(self):
        for dataset in sorted((ROOT/'data/pilot').glob('*/environment.json')):
            with self.subTest(dataset=dataset.parent.name):
                world = make_solo_world(dataset)
                trace = json.loads(dataset.with_name('reference.json').read_text())
                for row in trace:
                    action = row['action']
                    if action['type'] in ('send', 'pass'):
                        continue
                    if action['type'] in ('click', 'apply', 'input'):
                        zone = world.entities[action['target']]['zone']
                        if world.location['A'] != zone:
                            moved = world.step('A', {'type': 'move', 'target': zone})
                            self.assertTrue(moved['valid'], (row, moved['feedback']))
                    result = world.step('A', action)
                    self.assertTrue(result['valid'] and result['effect'], (row, result['feedback']))
                self.assertTrue(world.success)

    def test_solo_scheduler_and_reference_match(self):
        backend = FakeBackend(['{"type":"move","target":"bedroom"}',
                               '{"type":"pass","tool":"anything"}'])
        with tempfile.TemporaryDirectory() as temp:
            summary = run_episode(make_solo_world(DATASET), backend, 'solo', Path(temp), 2, 10, solo=True)
            self.assertEqual([actor for actor, _ in backend.seen], ['A', 'A'])
            self.assertEqual(summary['parse_errors'], 1)
            self.assertGreater(summary['reference_actions_total'], 0)

    def test_parser_accepts_one_action_only(self):
        self.assertEqual(parse_action('```json\n{"type":"wait"}\n```'), {'type':'wait'})
        for invalid in ['[]', '{}', '{"type":[]}', '{"type":"move"}',
                        '{"type":"input","target":"safe","value":1234}',
                        '{"type":"wait","actor":"B"}',
                        '{"type":"wait"}\n{"type":"look"}',
                        'I choose {"type":"look"}', '{"type":"unknown"}']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_action(invalid)

    def test_observation_text_does_not_contain_hidden_or_remote_state(self):
        world=World(DATASET)
        world.step('A',{'type':'move','target':'bedroom'})
        text=format_observation(world.observe('A'))
        self.assertIn('hammer handle',text)
        self.assertNotIn('cs546',text)
        self.assertNotIn('dining table close-up',text)
        self.assertNotIn('wait_for',text)
        self.assertNotIn('trigger',text)
        self.assertNotIn('annotations',text)

    def test_memory_window_and_role_isolation_with_explicit_message(self):
        backend=FakeBackend(['{"type":"move","target":"bedroom"}',
                             '{"type":"wait"}',
                             '{"type":"send","message":"Hello B"}',
                             '{"type":"look"}'])
        with tempfile.TemporaryDirectory() as temp:
            summary=run_episode(World(DATASET),backend,'rules',Path(temp),4,1)
            self.assertEqual(summary['turns'],4)
            b_first=backend.seen[1][1][1]['content']
            self.assertNotIn('hammer handle',b_first)
            self.assertNotIn('"target":"bedroom"',b_first)
            self.assertIn('Hello B',backend.seen[3][1][1]['content'])
            self.assertNotIn('hammer handle',backend.seen[3][1][1]['content'])
            self.assertEqual(len((Path(temp)/'turns.jsonl').read_text().splitlines()),4)

    def test_bad_output_consumes_turn_and_returns_private_error(self):
        backend=FakeBackend(['not json','{"type":"wait"}','{"type":"look"}'])
        with tempfile.TemporaryDirectory() as temp:
            summary=run_episode(World(DATASET),backend,'rules',Path(temp),3,10)
            self.assertEqual(summary['parse_errors'],1)
            self.assertEqual(summary['valid_actions'],2)
            self.assertEqual([a for a,m in backend.seen],['A','B','A'])
            self.assertNotIn('not json',backend.seen[1][1][1]['content'])
            self.assertIn('not json',backend.seen[2][1][1]['content'])

    def test_error_preserves_completed_turns_and_summary(self):
        backend=FakeBackend(['{"type":"look"}',RuntimeError('simulated CUDA failure')])
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                run_episode(World(DATASET),backend,'rules',Path(temp),4,10)
            summary=json.loads((Path(temp)/'summary.json').read_text())
            self.assertEqual(summary['stop_reason'],'error')
            self.assertEqual(summary['turns'],1)
            self.assertEqual(len((Path(temp)/'turns.jsonl').read_text().splitlines()),1)

    def test_no_memory_keeps_only_current_observation(self):
        world=World(DATASET)
        history=[dict(turn=1,area='private area',raw='old private action',feedback='old feedback')]
        messages=make_messages('rules','A',world.observe('A'),history,0)
        self.assertNotIn('old private action',messages[1]['content'])


if __name__ == '__main__':
    unittest.main()
