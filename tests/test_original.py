"""Compare the adapter against the actual pinned upstream BaseAgent loop."""
import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import scripts.original_escape as original
from scripts.run_original import DEFAULT_GAMES, OriginalHF, load_trace, run_game


class Backend:
    def __init__(self):
        self.calls = []

    def complete(self, messages, stop):
        self.calls.append(deepcopy(messages))
        return dict(raw='Thought: Test only.\nAction: click(nonexistent)',
                    messages=messages, input_tokens=1, output_tokens=1, seconds=0.0)


class OriginalTests(unittest.TestCase):
    def test_snapshot_matches_upstream_hashes_and_existing_eight_sources(self):
        original.verify_upstream()
        for game in DEFAULT_GAMES:
            source = original.ROOT/'data/source/escapebench'/f'{game}.yaml'
            self.assertEqual(source.read_bytes(), (original.UPSTREAM/'data'/f'{game}.yaml').read_bytes())

    def test_original_prompt_parser_and_neighbor_actions(self):
        with contextlib.redirect_stdout(io.StringIO()):
            messages = original.initial_messages('game1-1-easy')
        self.assertEqual(messages[0]['content'], original.instruction.BASE_SYS_PROMPT_COT)
        self.assertIn('Thought: ...\nAction: ...', messages[0]['content'])
        self.assertIn('Scene Description:', messages[1]['content'])
        self.assertIn('Possible Actions:', messages[1]['content'])
        self.assertIn('Tools in Bag:', messages[1]['content'])
        self.assertIn('<interactable scene>', messages[1]['content'])
        self.assertNotIn('"type":', messages[0]['content'])
        self.assertEqual(original.find_last_function_call('Thought: click(a)\nAction: move(b)'), 'move(b)')

    def test_exact_parity_with_stock_run_including_helper_and_forced_action(self):
        # Stock setup/run, in a disposable original-style directory, with only
        # call_LLM replaced by a deterministic response. No modified prompts.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'src').mkdir()
            (root/'data').symlink_to(original.UPSTREAM/'data', target_is_directory=True)
            args = SimpleNamespace(max_steps=75, memory=10, use_cot=True, stuck_steps=50,
                                   stuck_behavior='help', is_api=False, port='unused',
                                   overwrite=False, output_suffix='')
            agent = original.BaseAgent(args)
            stock_prompts = []
            def stock_call(model, system, user, *unused):
                stock_prompts.append([dict(role='system', content=system),dict(role='user', content=user)])
                return 'Thought: Test only.\nAction: click(nonexistent)'
            original.call_LLM = stock_call
            cwd = Path.cwd()
            try:
                os.chdir(root/'src')
                with contextlib.redirect_stdout(io.StringIO()):
                    agent.run('fake', 'game1-1-easy')
            finally:
                os.chdir(cwd)
            # Read snapshots as written at each step (history contains references).
            text = (root/'outputs/fake_cot_help/game1-1-easy/log.txt').read_text().lstrip()
            source = []
            while text:
                row, end = json.JSONDecoder().raw_decode(text)
                source.append(row)
                text = text[end:].lstrip()
            backend = Backend()
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_game('game1-1-easy', backend, root/'adapter', max_steps=75)
            rows = load_trace(root/'adapter/turns.jsonl')
            self.assertEqual([r['upstream'] for r in rows], source)
            self.assertEqual(backend.calls, stock_prompts)
            self.assertEqual(result['hints_used'], agent.help_cnt)
            self.assertEqual(result['forced_actions'], 1)
            hints = [r for r in rows if r['helper_active'] and r['generation']]
            self.assertTrue(hints)
            self.assertNotIn('History: [Step', hints[0]['generation']['messages'][1]['content'])
            self.assertTrue(rows[60]['forced_action'])
            self.assertIsNone(rows[60]['generation'])

    def test_resume_reconstructs_mid_hint_state_without_new_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp); first = Backend()
            stopped = run_game('game1-1-easy', first, root/'resume',
                               stop=lambda: len(first.calls) >= 55, max_steps=75)
            self.assertEqual(stopped['stop_reason'], 'interrupted')
            self.assertEqual(stopped['steps'], 54)
            second = Backend()
            resumed = run_game('game1-1-easy', second, root/'resume', max_steps=75)
            run_game('game1-1-easy', Backend(), root/'whole', max_steps=75)
            self.assertEqual(load_trace(root/'resume/turns.jsonl'), load_trace(root/'whole/turns.jsonl'))
            self.assertEqual(len(second.calls), 20)  # 21 remaining steps, one forced by oracle.
            self.assertEqual(resumed['stop_reason'], 'step_budget')

    def test_all_eight_upstream_games_finish_with_original_forced_help(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            for game in DEFAULT_GAMES:
                with self.subTest(game=game):
                    result = run_game(game, Backend(), Path(tmp)/game)
                    self.assertTrue(result['success'], result)
                    self.assertEqual(result['progress_percent'], 100)
                    self.assertGreater(result['forced_actions'], 0)

    def test_partial_log_tail_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'turns.jsonl'
            p.write_bytes(b'{"step":0}\n{"step":')
            self.assertEqual(load_trace(p), [{'step':0}])
            self.assertEqual(p.read_bytes(), b'{"step":0}\n')
            self.assertTrue(p.with_suffix('.partial').exists())

    def test_hf_transport_uses_greedy_short_cot_and_preserves_input(self):
        class Inputs(dict):
            input_ids = SimpleNamespace(shape=(1, 100))
            def to(self, device): return self
        class Output:
            def __getitem__(self, key): return [1, 2, 3]
        tokenizer = MagicMock()
        tokenizer.apply_chat_template.return_value = 'exact rendered prompt'
        tokenizer.return_value = Inputs(input_ids='fake inputs')
        tokenizer.decode.return_value = 'Thought: Open it.\nAction: click(door)'
        model = MagicMock()
        model.generate.return_value = Output()
        torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None),
                                inference_mode=contextlib.nullcontext)
        transport = OriginalHF.__new__(OriginalHF)
        transport.backend = SimpleNamespace(tokenizer=tokenizer, torch=torch, model=model, context_limit=2400)
        generation_config = MagicMock()
        fake_transformers = SimpleNamespace(GenerationConfig=generation_config,
                                            StoppingCriteria=object, StoppingCriteriaList=list)
        messages = [dict(role='system',content='original'),dict(role='user',content='observation')]
        with patch.dict('sys.modules', {'transformers':fake_transformers}), patch(
                'scripts.run_original.generate_greedy', return_value=(Output(), {'mode': 'greedy_search'})) as generate:
            result = transport.complete(messages, lambda:False)
            generate.assert_called_once()
            self.assertIs(generate.call_args.args[0], model)
            self.assertEqual(result['effective_generation']['mode'], 'greedy_search')
            self.assertFalse(tokenizer.apply_chat_template.call_args.kwargs['enable_thinking'])
            self.assertEqual(result['messages'], messages)
            self.assertEqual(result['rendered_prompt'], 'exact rendered prompt')
            self.assertEqual(result['raw'], 'Thought: Open it.\nAction: click(door)')
            transport.backend.context_limit=300
            with self.assertRaisesRegex(ValueError,'prompt not truncated'):
                transport.complete(messages, lambda:False)


if __name__ == '__main__':
    unittest.main()
