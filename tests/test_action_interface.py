import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.action_interface import present
from scripts.run_matrix import run_episode


class InterfaceTests(unittest.TestCase):
    def messages(self):
        return [dict(role='system', content='original'), dict(role='user', content='''History: old
<applicable tool> old key: no longer held
Now you need to act on [Step 2]
<interactable item> hammer
<interactable scene> Go into the room it leads to: It leads to lab room overview
Tools in Bag:
<applicable tool> pool ball 1: A ball
''')]

    def test_exact_current_labels_and_no_guessing_inventory(self):
        messages = self.messages()
        original = deepcopy(messages)
        self.assertIs(present(messages, 'coop'), messages)
        move = present(messages, 'coop', 'move_labels')[-1]['content'].split('Action-format reference')[1]
        self.assertIn('move(Go into the room it leads to)', move)
        self.assertNotIn('lab room overview', move)
        self.assertNotIn('give(', move)
        full = present(messages, 'coop', 'action_labels')[-1]['content'].split('Action-format reference')[1]
        self.assertIn('click(hammer)', full)
        self.assertIn('give(pool ball 1)', full)
        self.assertNotIn('give(hammer)', full)
        self.assertNotIn('old key', full)
        self.assertNotIn('give(', present(messages, 'solo', 'action_labels')[-1]['content'].split('Action-format reference')[1])
        self.assertEqual(messages, original)

    def test_diagnostic_replays_exactly_and_keeps_engine_action_errors(self):
        def request(messages):
            return dict(raw='Action: give(hammer)', messages=messages)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            path = Path(tmp)
            run_episode('coop', 'game1-3-easy', path, request, lambda: False, 4, interface='action_labels')
            before = (path/'turns.jsonl').read_bytes()
            result = run_episode('coop', 'game1-3-easy', path, request, lambda: False, 4, interface='action_labels')
            self.assertEqual(result['steps'], 4)
            self.assertEqual(before, (path/'turns.jsonl').read_bytes())
            rows = [json.loads(x) for x in before.splitlines()]
            self.assertTrue(all('not a tool in your bag' in r['upstream']['response'] for r in rows))
            self.assertTrue(all('Action-format reference' in r['generation']['messages'][-1]['content'] for r in rows))

    def test_diagnostic_results_do_not_enter_original_comparison(self):
        from scripts.matrix_report import collect
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'diagnostic').mkdir()
            (root/'diagnostic/experiment.json').write_text(json.dumps(dict(settings={'interface': 'move_labels'})))
            self.assertEqual(collect(root), {})


if __name__ == '__main__':
    unittest.main()
