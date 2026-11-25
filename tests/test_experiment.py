import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.coop_escape import World
from scripts.run_model import ROOT
from scripts.solo_experiment import (Settings, choose_hint, compile_reference, final_answer,
                                     messages_for, new_world, run_trial)
from scripts.run_experiment import load_plan, report, trials, latest_summary

DATASET = ROOT/'data/pilot/01_mirror_workshop/environment.json'


class Backend:
    def __init__(self, actions=None, follow_hints=False):
        self.actions = iter(actions) if actions is not None else None
        self.follow_hints = follow_hints
        self.prompts = []

    def complete(self, messages, generation, stop):
        self.prompts.append(messages)
        text = messages[1]['content']
        raw = '{"type":"wait"}'
        if self.actions is not None:
            raw = next(self.actions)
            if isinstance(raw, Exception):
                raise raw
        elif self.follow_hints and 'External hint' in text:
            area = text.split('Go to area: ')[1].split('. If already there')[0]
            current = text.split('Current area: ')[1].split('\n')[0]
            action = json.loads(text.split('Target action: ')[1].split('\n')[0])
            raw = json.dumps(action if current == area else dict(type='move', target=area))
        return dict(raw=raw, messages=messages, input_tokens=100, output_tokens=10,
                    seconds=0.01, hit_output_limit=False)


class ExperimentTests(unittest.TestCase):
    def run_trial(self, backend, settings, stop=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name)/'trial'
        with contextlib.redirect_stdout(io.StringIO()):
            summary = run_trial(DATASET, backend, settings, output, stop)
        return summary, output

    def test_all_references_cover_unique_source_milestones(self):
        for path in sorted((ROOT/'data/pilot').glob('*/environment.json')):
            with self.subTest(dataset=path.parent.name):
                entries = compile_reference(path)
                world = new_world(path)
                self.assertEqual(len({x for e in entries for x in e['milestones']}), world.progress()['total'])

    def test_moves_and_invalid_actions_do_not_count_as_progress(self):
        world = new_world(DATASET)
        for _ in range(3):
            world.step('A', dict(type='move', target='living room'))
            world.step('A', dict(type='input', target='missing', value='wrong'))
        self.assertEqual(world.progress()['completed'], 0)

    def test_multitool_condition_ids_survive_consumption_and_repeat(self):
        spec = dict(annotations={'information_links': []}, zones=[dict(name='room A', room='A', desc='test')],
                    entities=[dict(name=n, kind='tool', room='A', zone='room A', states=[dict(desc=n, apply_to=['lock'])]) for n in ('x','y')])
        spec['entities'].append(dict(name='lock', kind='item', room='A', zone='room A', states=[dict(
            desc='lock', transitions=[dict(wait_for=['apply, x','apply, y'], trigger=['finish_team'])])]))
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'environment.json'; p.write_text(json.dumps(spec)); world=World(p)
            for name in ('x','y'): world.step('A',dict(type='click',target=name))
            world.step('A',dict(type='apply',tool='x',target='lock'))
            self.assertEqual(world.progress()['key_steps'],1)
            world.step('A',dict(type='apply',tool='x',target='lock'))
            self.assertEqual(world.progress()['key_steps'],1)
            world.step('A',dict(type='apply',tool='y',target='lock'))
            self.assertTrue(world.success)
            self.assertEqual(world.progress()['fraction'],1)

    def test_nohint_stops_at_50_and_hint_mode_does_not_act_for_model(self):
        nohint = Backend(); assisted = Backend()
        a, _ = self.run_trial(nohint, Settings())
        b, output = self.run_trial(assisted, Settings(hints=True, hint_patience=3))
        self.assertEqual(a['turns'],50)
        self.assertEqual(a['stop_reason'],'stalled')
        self.assertEqual(b['first_hint']['turn'],51)
        self.assertEqual(b['turns'],53)
        self.assertEqual(b['stop_reason'],'hint_following_failed')
        self.assertEqual(b['progress']['completed'],0)
        self.assertEqual(nohint.prompts, assisted.prompts[:50])
        self.assertTrue(all('External hint' not in m[1]['content'] for m in nohint.prompts))
        records = [json.loads(x) for x in (output/'turns.jsonl').read_text().splitlines()]
        self.assertTrue(all(r['result']['observation']['area']=='living room' for r in records))

    def test_actual_new_milestone_resets_stall_counter(self):
        entry = compile_reference(DATASET)[0]
        actions=[json.dumps(dict(type='move',target=entry['area'])),json.dumps(entry['action']),
                 '{"type":"wait"}', '{"type":"wait"}']
        result,_=self.run_trial(Backend(actions),Settings(stuck_steps=2))
        self.assertEqual(result['turns'],4)
        self.assertGreater(result['progress']['completed'],0)

    def test_following_hints_can_complete_without_teleport_or_forcing(self):
        summary, _ = self.run_trial(Backend(follow_hints=True), Settings(hints=True, stuck_steps=2, max_steps=400))
        self.assertTrue(summary['success'])
        self.assertFalse(summary['success_without_hints'])
        self.assertEqual(summary['progress']['fraction'],1)
        self.assertGreater(summary['hints_used'],0)

    def test_hint_selection_does_not_mutate_live_world(self):
        world=new_world(DATASET)
        hint=choose_hint(world,compile_reference(DATASET))
        self.assertIsNotNone(hint)
        self.assertEqual(world.turn,0)
        self.assertEqual(world.progress()['completed'],0)
        self.assertEqual(world.events,[])

    def test_thinking_final_only_and_truncated_output(self):
        self.assertEqual(final_answer('Reasoning {"type":"wait"}</think>{"type":"look"}',True),'{"type":"look"}')
        for raw in ('{"type":"wait"}', '<think>unfinished', 'reasoning</think>'):
            with self.assertRaises(ValueError): final_answer(raw,True)
        summary,_=self.run_trial(Backend(['unfinished']),Settings(thinking=True,max_steps=1))
        self.assertEqual(summary['parse_errors'],1)
        self.assertEqual(summary['turns'],1)

    def test_error_logs_are_preserved(self):
        summary,output=self.run_trial(Backend(['{"type":"wait"}',RuntimeError('fake error')]),Settings())
        self.assertEqual(summary['stop_reason'],'error')
        self.assertEqual(len((output/'turns.jsonl').read_text().splitlines()),1)
        self.assertTrue((output/'summary.json').exists())

    def test_interrupted_generation_does_not_execute_an_action(self):
        stopped = [False]
        class InterruptedBackend(Backend):
            def complete(self, *args):
                generated = super().complete(*args)
                stopped[0] = True
                return generated
        summary, output = self.run_trial(InterruptedBackend(), Settings(), lambda: stopped[0])
        self.assertEqual(summary['stop_reason'], 'interrupted')
        self.assertEqual(summary['turns'], 0)
        self.assertEqual(summary['model_calls'], 1)
        self.assertTrue((output/'interrupted_generation.json').exists())

    def test_decoded_final_boundary_overrides_reasoning_json(self):
        class TokenBoundaryBackend(Backend):
            def complete(self, *args):
                generated = super().complete(*args)
                generated.update(raw='reasoning with invalid JSON', final_text='{"type":"wait"}')
                return generated
        summary, _ = self.run_trial(TokenBoundaryBackend(), Settings(thinking=True, max_steps=1))
        self.assertEqual(summary['parse_errors'], 0)
        self.assertEqual(summary['turns'], 1)

    def test_prompt_and_plan_isolation(self):
        plan=load_plan(ROOT/'experiments/solo_pilot.json',[42,43,44])
        self.assertEqual(len(list(trials(plan))),24)
        obs=new_world(DATASET).observe('A')
        prompt=json.dumps(messages_for(obs,[],Settings()))
        for secret in ('cs546','source_action_mapping','completed_milestones','accepted_input'):
            self.assertNotIn(secret,prompt)
        with self.assertRaises(ValueError): messages_for(obs,[],Settings(),{'area':'x','action':{'type':'look'}})

    def test_empty_report_and_partial_attempts_are_not_successes(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp); plan=load_plan(ROOT/'experiments/solo_pilot.json')
            rows=report(output,plan)
            self.assertTrue(all(row['result'] is None for row in rows))
            self.assertIn('0/1',(output/'report.md').read_text())
            self.assertIsNone(latest_summary(output/'missing'))


if __name__ == '__main__':
    unittest.main()
