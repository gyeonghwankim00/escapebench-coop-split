"""Solo vs 2-agent runner on the original engine."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

import scripts.original_escape as oe
import scripts.coop_original as co
from scripts.run_original import DEFAULT_GAMES, load_trace
from scripts.run_matrix import ALL_GAMES, GENERATION_VERSION, Interrupted, run_all, run_episode


def v1(game):
    return json.loads((co.ROLES_DIR/'v1'/f'{game}.json').read_text())

GARBAGE = 'Thought: Test only.\nAction: click(nonexistent)'


def drive(agent, game):
    """Sequential driver: records every completed step, including the last."""
    rows, it, result = [], agent.iterate('test', game), None
    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            try:
                next(it)
            except StopIteration as stop:
                result = stop.value
            if len(agent.history) > len(rows):
                rows.append(agent.record())
            if result is not None:
                return result, rows


def recorder(responses=None):
    calls = []
    def call(step, messages):
        calls.append(deepcopy(messages))
        raw = responses.pop(0) if responses else GARBAGE
        return dict(raw=raw, messages=messages)
    return calls, call


class FakeBatch:
    def __init__(self, stop_after=None):
        self.batches, self.stop_after = 0, stop_after

    def complete_batch(self, batch, stop):
        self.batches += 1
        return [dict(raw=GARBAGE, messages=m, input_tokens=1, output_tokens=1, seconds=0.0) for m in batch]


class ParityTests(unittest.TestCase):
    def test_all_scenes_to_one_role_reproduces_original_agent(self):
        for game in ('game1-1-easy', 'game2-4-easy'):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                c1, f1 = recorder()
                r1 = drive(oe.Agent(game, tmp, f1), game)
                c2, f2 = recorder()
                r2 = drive(co.CoopAgent(game, tmp, f2, roles=co.solo_roles(game), coop=False), game)
                self.assertEqual(r1[0], r2[0])
                self.assertEqual(c1, c2)
                self.assertEqual([r['upstream'] for r in r1[1]], [r['upstream'] for r in r2[1]])
                self.assertEqual([r['forced_action'] for r in r1[1]], [r['forced_action'] for r in r2[1]])

    def test_parser_matches_upstream_for_base_actions(self):
        for text in ['Thought: click(a)\nAction: move(b)', 'no call', 'apply(x, y) then craft(a,b)']:
            self.assertEqual(co.find_last_call(text, co.BASE_ACTIONS), oe.find_last_function_call(text))
        self.assertEqual(co.find_last_call('click(a)\nAction: send(code is 42)', co.COOP_ACTIONS),
                         'send(code is 42)')

    def test_coop_prompt_is_original_plus_one_paragraph(self):
        prompt = co.coop_system_prompt()
        self.assertTrue(prompt.startswith(oe.SYS_PROMPT_COT.split('\n\nHere are some reminders')[0]))
        self.assertTrue(prompt.endswith('\n\nHere are some reminders' +
                                        oe.SYS_PROMPT_COT.split('\n\nHere are some reminders')[1]))
        self.assertEqual(len(prompt) - len(oe.SYS_PROMPT_COT), len(co.COOP_PARAGRAPH) + 2)


class CoopTests(unittest.TestCase):
    def test_forced_help_finishes_all_twelve_split_games(self):
        for game in ALL_GAMES:
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                (ok, steps), rows = drive(co.CoopAgent(game, tmp, recorder()[1], max_steps=9000), game)
                self.assertTrue(ok)
                self.assertEqual(rows[-1]['upstream']['tracking']['progress'], 100)
                self.assertTrue(any(r['upstream']['action_answer'].startswith('give(') for r in rows))
                self.assertEqual([r['role'] for r in rows[:2]], ['A', 'B'])  # both act from the start

    def test_forced_help_finishes_v1_splits_too(self):
        for game in DEFAULT_GAMES:
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                (ok, _), rows = drive(co.CoopAgent(game, tmp, recorder()[1], max_steps=6000, roles=v1(game)), game)
                self.assertTrue(ok)
                self.assertEqual({r['role'] for r in rows}, {'A', 'B'})

    def test_solo_forced_help_finishes_the_four_new_games(self):
        for game in sorted(set(ALL_GAMES) - set(DEFAULT_GAMES)):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                (ok, _), rows = drive(oe.Agent(game, tmp, recorder()[1], max_steps=9000), game)
                self.assertTrue(ok)
                self.assertEqual(rows[-1]['upstream']['tracking']['progress'], 100)

    def test_role_files_cover_every_scene_once_and_meet_the_split_criteria(self):
        import yaml
        for game in ALL_GAMES:
            with self.subTest(game=game):
                spec = co.load_roles(game)
                scenes = [s['name'] for s in yaml.safe_load((oe.UPSTREAM/'data'/f'{game}.yaml').read_text())]
                m = spec['metrics']
                self.assertEqual(spec['version'], 'v3')
                self.assertEqual(sorted(spec['A'] + spec['B']), sorted(scenes))
                self.assertEqual(spec['A'][0], scenes[0])
                self.assertIn(spec['starts']['B'], spec['B'])
                # no idle role: each can do >= 10% of the reference steps alone
                self.assertGreaterEqual(min(m['alone_A'], m['alone_B']), 0.1 * m['total'])
                needs_give = m['total'] - m['together_no_give']
                self.assertEqual(spec['low_interdependence'], needs_give < 0.15 * m['total'])
                self.assertEqual(m['clue_inputs_cross'], len(spec['cross_clues']))
                self.assertEqual(m['handoffs'], len(spec['reference_handoffs']))
                # a freely enterable dead-end scene (close-up) stays with the scene it opens from
                owner = {n: r for r in 'AB' for n in spec[r]}
                data = yaml.safe_load((oe.UPSTREAM/'data'/f'{game}.yaml').read_text())
                adj = {n: set() for n in scenes}
                for sc in data:
                    for t in (sc.get('scene_relations') or {}).values():
                        adj[sc['name']].add(t)
                        adj[t].add(sc['name'])
                for sc in data:
                    if len(adj[sc['name']]) == 1 and sc.get('visible', True) and sc['name'] != scenes[0]:
                        self.assertEqual(owner[sc['name']], owner[next(iter(adj[sc['name']]))], sc['name'])

    def test_clue_annotations_cover_every_code_input_with_checked_evidence(self):
        from scripts.make_clues import build
        from scripts.split_metrics import reference
        clues = json.loads((oe.ROOT/'data/clues.json').read_text())['games']
        self.assertEqual(json.loads(json.dumps(build())), clues)  # build() verifies evidence text
        self.assertEqual(sum(len(v) for v in clues.values()), 54)
        for game in ALL_GAMES:
            inputs = [r['action_answer'] for r in reference(game) if r['action_answer'].startswith('input(')]
            self.assertEqual(len(clues[game]), len(inputs))
            self.assertTrue(all(c['sources'] for c in clues[game]))

    def test_two_room_start_puts_b_inside_its_locked_room(self):
        game = 'game2-2-easy'  # v1: B idle until A opens the shop; v2: B starts in the inner office
        with tempfile.TemporaryDirectory() as tmp:
            calls, call = recorder()
            _, rows = drive(co.CoopAgent(game, tmp, call, max_steps=4), game)
        self.assertEqual([r['role'] for r in rows], ['A', 'B', 'A', 'B'])
        self.assertIn("You are in the scene 'inner office'", calls[1][1]['content'])
        bad = dict(co.load_roles(game), starts={'B': 'entrace of a shop'})
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, 'Invalid start'):
            drive(co.CoopAgent(game, tmp, recorder()[1], roles=bad), game)

    def test_random_play_never_strands_a_role_and_always_finishes(self):
        """Off the reference path: no turn without any item or exit (a role stuck in
        its own room), no engine error that Solo does not also have, game still ends."""
        import random
        import re

        def policy(rng):
            def call(step, messages):
                cur = messages[1]['content']
                cur = cur[cur.rfind('Now you need to act on'):]
                items = re.findall(r'<interactable item> (.+)', cur)
                scenes = re.findall(r'<interactable scene> (.+?): It leads to', cur)
                tools = re.findall(r'<applicable tool> (.+?): ', cur)
                hint = re.search(r'Your next target action should be: (.+)\.\n', cur)
                if hint and rng.random() < 0.5:
                    return dict(raw='Action: ' + hint.group(1), messages=messages)
                opts = ['send(hello)']
                if items:
                    opts += [f'click({rng.choice(items)})'] * 4
                if scenes:
                    opts += [f'move({rng.choice(scenes)})'] * 3
                if tools and items:
                    opts += [f'apply({rng.choice(tools)}, {rng.choice(items)})'] * 4
                if tools:
                    opts += [f'give({rng.choice(tools)})'] * 2
                return dict(raw='Action: ' + rng.choice(opts), messages=messages)
            return call

        for game in ALL_GAMES:
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                (ok, _), rows = drive(co.CoopAgent(game, tmp, policy(random.Random(0)), max_steps=6000), game)
                self.assertTrue(ok)
                for row in rows:
                    actions = row['upstream']['possible_actions']
                    self.assertTrue('<interactable item>' in actions or '<interactable scene>' in actions,
                                    (row['role'], row['upstream']['position']))
                    self.assertNotIn('ROLE_VISIBLE', json.dumps(row))

    def test_start_room_stays_closed_to_partner_until_opened(self):
        game = 'game1-4-easy'  # B starts in the kitchen, hidden behind A's hallway door
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            agent = co.CoopAgent(game, tmp, recorder()[1])
            agent.setup('test', game)
            kitchen = agent.graph.scenes['kitchen']
            self.assertFalse(kitchen.visible)
            agent.act(0)
            agent.act(1)  # B's turn: sees its room as open only while acting
            self.assertIs(kitchen.visible, False)
            agent.graph.scenes['storage room'].visible = True
            agent.where['B'] = 'storage room'
            agent.act(2)
            agent.act(3)
        self.assertIn('It leads to kitchen', agent.history[3]['possible_actions'])
        self.assertNotIn('kitchen', agent.history[2]['possible_actions'])  # A still locked out

    def test_roles_only_see_and_enter_own_scenes(self):
        game = 'game1-3-easy'
        roles = v1(game)
        with tempfile.TemporaryDirectory() as tmp:
            calls, call = recorder()
            _, rows = drive(co.CoopAgent(game, tmp, call, max_steps=40, roles=roles), game)
        for row in rows:
            scene = row['upstream']['position'].split(' -> ')[-1]
            self.assertIn(scene, roles[row['role']])
            for other in roles['B' if row['role'] == 'A' else 'A']:
                self.assertNotIn(f'It leads to {other}\n', row['upstream']['possible_actions'] + '\n')
        self.assertEqual([r['role'] for r in rows[:4]], ['A', 'B', 'A', 'B'])
        b_first = calls[1][1]['content']
        self.assertIn('You are in the scene \'left corner of the hallway\'', b_first)
        self.assertIn('Go to the elevator room via partner area: It leads to the elevator room', b_first)
        self.assertIn('send(message)', calls[0][0]['content'])

    def test_locked_out_role_is_skipped_until_reachable(self):
        game = 'game2-1-easy'  # v1 rule: B's scenes lie behind A's locked hallway
        with tempfile.TemporaryDirectory() as tmp:
            _, rows = drive(co.CoopAgent(game, tmp, recorder()[1], max_steps=30, roles=v1(game)), game)
        self.assertEqual({r['role'] for r in rows}, {'A'})
        self.assertEqual(len(rows), 30)

    def test_send_and_give_reach_partner(self):
        game = 'game1-3-easy'
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            calls, call = recorder(['Action: give(hammer)', 'Action: send(I got the hammer)',
                                    'Action: click(nonexistent)'])
            agent = co.CoopAgent(game, tmp, call, roles=v1(game))
            agent.setup('test', game)
            hammer = agent.graph.scenes['the billiard room'].tools['hammer']['tool']
            agent.bags['A'].add_tool(deepcopy(hammer))
            agent.act(0)  # A gives
            self.assertNotIn('hammer', agent.bags['A'].tools)
            self.assertIn('hammer', agent.bags['B'].tools)
            agent.act(1)  # B sends
            agent.act(2)  # A reads
        b_prompt, a_prompt = calls[1][1]['content'], calls[2][1]['content']
        self.assertIn('Your partner gave you the hammer. It is now in your bag.', b_prompt)
        self.assertIn('<applicable tool> hammer', b_prompt)
        self.assertIn('Your partner sent you a message: "I got the hammer"', a_prompt)
        self.assertIn('Your action: give(hammer)', a_prompt)  # own history, role-local step 0
        self.assertNotIn('send(I got the hammer)', a_prompt.split('Updates from your partner')[0])


class RunnerTests(unittest.TestCase):
    episodes = [('solo', 'game1-3-easy'), ('coop', 'game1-3-easy'),
                ('solo', 'game2-4-easy'), ('coop', 'game2-4-easy')]

    def sequential(self, root, max_steps):
        backend = FakeBatch()
        for condition, game in self.episodes:
            with contextlib.redirect_stdout(io.StringIO()):
                run_episode(condition, game, root/condition/game,
                            lambda m: backend.complete_batch([m], None)[0], lambda: False, max_steps)

    def test_batched_threads_match_sequential_and_resume_exactly(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            self.sequential(root/'seq', 130)
            results, timing = run_all(self.episodes, FakeBatch(), lambda: False, 130, 16, root/'batched')
            self.assertGreater(timing['mean_batch_size'], 2)
            backend = FakeBatch()
            stop = lambda: backend.batches >= 40
            first, _ = run_all(self.episodes, backend, stop, 130, 16, root/'resumed')
            self.assertTrue(all(r['stop_reason'] == 'interrupted' for r in first.values()))
            second, _ = run_all(self.episodes, FakeBatch(), lambda: False, 130, 16, root/'resumed')
            for condition, game in self.episodes:
                seq = load_trace(root/'seq'/condition/game/'turns.jsonl')
                self.assertEqual(len(seq), 130)
                self.assertEqual(load_trace(root/'batched'/condition/game/'turns.jsonl'), seq)
                self.assertEqual(load_trace(root/'resumed'/condition/game/'turns.jsonl'), seq)
                self.assertEqual(second[condition, game]['stop_reason'], 'step_budget')
                summary = json.loads((root/'resumed'/condition/game/'summary.json').read_text())
                self.assertEqual(summary['steps'], 130)


class BookkeepingTests(unittest.TestCase):
    def manifest(self, conditions, **changes):
        base = dict(protocol='p', upstream_commit='c', generation_version=GENERATION_VERSION,
                    conditions=conditions, games=['game1-3-easy'],
                    model='/m/Qwen3-8B', revision='main', quantization='4bit', local_model_identity={},
                    dry_run=False, settings=dict(max_steps=4000, context_tokens=8192, max_new_tokens=256),
                    code_hashes={'scripts/original_escape.py': 'a', 'scripts/coop_original.py': 'b',
                                 'scripts/run_matrix.py': 'c', 'scripts/run_original.py': 'd',
                                 'scripts/run_model.py': 'e', 'scripts/greedy_generation.py': 'f'},
                    role_hashes={'game1-3-easy': 'r'})
        base.update(changes)
        return base

    def test_solo_runs_survive_coop_and_role_changes_but_coop_runs_do_not(self):
        from scripts.run_matrix import resume_key
        changed = dict(code_hashes={'scripts/original_escape.py': 'a', 'scripts/coop_original.py': 'NEW',
                                    'scripts/run_matrix.py': 'NEW', 'scripts/run_original.py': 'd',
                                    'scripts/run_model.py': 'e', 'scripts/greedy_generation.py': 'f'},
                       role_hashes={'game1-3-easy': 'NEW'}, protocol='p2', generation_version=GENERATION_VERSION)
        self.assertEqual(resume_key(self.manifest(['original_solo'])), resume_key(self.manifest(['original_solo'], **changed)))
        self.assertNotEqual(resume_key(self.manifest(['coop'])), resume_key(self.manifest(['coop'], **changed)))
        engine = dict(changed, code_hashes=dict(changed['code_hashes'], **{'scripts/run_model.py': 'NEW'}))
        self.assertNotEqual(resume_key(self.manifest(['original_solo'])), resume_key(self.manifest(['original_solo'], **engine)))
        self.assertNotEqual(resume_key(self.manifest(['original_solo'])),
                            resume_key(self.manifest(['original_solo'], settings=dict(max_steps=10))))
        self.assertNotEqual(resume_key(self.manifest(['original_solo'])),
                            resume_key(self.manifest(['original_solo'], generation_version=1)))

    def test_report_keeps_old_solo_results_and_marks_old_split_coop_stale(self):
        from scripts.matrix_report import collect, comparison
        from scripts.run_matrix import ROLES_DIR, file_hash
        from scripts.run_original import write_json
        game = 'game1-3-easy'
        row = dict(game=game, stop_reason='success', steps=900, hints_used=12, pre_help_progress_percent=10.5,
                   messages_before_first_hint=1, gives_before_first_hint=0)
        current = dict(protocol=__import__('scripts.run_matrix',fromlist=['PROTOCOL']).PROTOCOL, code_hashes=dict(self.manifest(['coop'])['code_hashes'],
                                        **{'scripts/coop_original.py': file_hash(oe.ROOT/'scripts/coop_original.py'), 'scripts/adaptive_escape.py': file_hash(oe.ROOT/'scripts/adaptive_escape.py')}),
                       role_hashes={game: file_hash(ROLES_DIR/f'{game}.json')})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name, conditions, extra, hints in [('old-solo', ['solo'], {}, 12), ('old-coop', ['coop'], {}, 30),
                                                   ('new-coop', ['coop'], current, 9)]:
                (base/name/conditions[0]/game).mkdir(parents=True)
                write_json(base/name/'experiment.json', self.manifest(conditions, **extra))
                write_json(base/name/conditions[0]/game/'summary.json',
                           dict(row, condition=conditions[0], hints_used=hints))
            found = collect(base)
            self.assertEqual(found['Qwen3-8B', 'original_solo', game]['state'], 'done')
            self.assertEqual(found['Qwen3-8B', 'coop', game]['run'], 'new-coop')
            self.assertNotIn('| game1-3-easy | 12 | 9 | -3 |', '\n'.join(comparison(found)))
            (base/'new-coop'/'coop'/game/'summary.json').unlink()
            self.assertIn(collect(base)['Qwen3-8B', 'coop', game]['state'], ('queued', 'stale'))

    def test_old_generation_solo_is_visible_but_excluded_from_comparison(self):
        from scripts.matrix_report import collect, comparison
        from scripts.run_original import write_json
        game = 'game1-3-easy'
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base/'old'/'solo'/game
            path.mkdir(parents=True)
            write_json(base/'old'/'experiment.json', self.manifest(['solo'], generation_version=1))
            write_json(path/'summary.json', dict(stop_reason='success', hints_used=0, steps=20))
            found = collect(base)
            self.assertEqual(found['Qwen3-8B', 'original_solo', game]['state'], 'old_generation')
            self.assertNotIn('Paired games:', '\n'.join(comparison(found)))


class BatchHFTests(unittest.TestCase):
    def test_greedy_left_padded_batch_trims_at_eos_and_rejects_overflow_per_request(self):
        import contextlib as cl
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from scripts.run_matrix import BatchHF

        class Rows(list):
            def __getitem__(self, key):
                if isinstance(key, tuple):
                    return Rows(row[key[1]] for row in self)
                return list.__getitem__(self, key)
            def tolist(self):
                return [list(r) for r in self]
            @property
            def shape(self):
                return (len(self), len(list.__getitem__(self, 0)))

        class Enc(dict):
            def to(self, device):
                return self
        tok = MagicMock()
        tok.apply_chat_template.side_effect = lambda m, **kw: m[1]['content']
        lengths = {'short': 3, 'long': 9}
        def tokenize(texts, **kw):
            if isinstance(texts, str):
                return SimpleNamespace(input_ids=[0] * lengths[texts])
            self.assertTrue(kw['padding'])
            return Enc(input_ids=Rows([[0, 0, 0]] * len(texts)), attention_mask=None)
        tok.side_effect = tokenize
        tok.decode.side_effect = lambda ids, **kw: ' '.join(map(str, ids))
        tok.pad_token_id, tok.bos_token_id = 9, None
        model = MagicMock()
        model.generate.return_value = Rows([[0, 0, 0, 5, 6, 7, 99, 9, 9]])
        torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=lambda: None),
                                inference_mode=cl.nullcontext)
        hf = BatchHF.__new__(BatchHF)
        hf.backend = SimpleNamespace(tokenizer=tok, model=model, torch=torch, context_limit=264)
        hf.eos = {99}
        config = MagicMock()
        fake = SimpleNamespace(GenerationConfig=config, StoppingCriteria=object, StoppingCriteriaList=list)
        batch = [[dict(role='system', content='s'), dict(role='user', content='short')],
                 [dict(role='system', content='s'), dict(role='user', content='long')]]
        with patch.dict('sys.modules', {'transformers': fake}), patch(
                'scripts.run_matrix.generate_greedy', return_value=(model.generate.return_value, {'mode': 'greedy_search'})) as generate:
            out = hf.complete_batch(batch, lambda: False)
        generate.assert_called_once()
        self.assertIs(generate.call_args.args[0], model)
        self.assertEqual(out[0]['effective_generation']['mode'], 'greedy_search')
        self.assertFalse(tok.apply_chat_template.call_args.kwargs['enable_thinking'])
        self.assertEqual(out[0]['raw'], '5 6 7 99')
        self.assertEqual(out[0]['output_tokens'], 4)
        self.assertFalse(out[0]['output_limit_hit'])
        self.assertEqual(out[0]['messages'], batch[0])
        self.assertIsInstance(out[1], ValueError)  # 9 + 256 > 264, never truncated


if __name__ == '__main__':
    unittest.main()
