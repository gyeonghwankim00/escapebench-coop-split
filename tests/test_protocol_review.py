import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from scripts.adaptive_escape import AdaptiveSolo,AdaptivePeer
from scripts.cohort_policy import load_policy
from scripts.run_cohort import report

class ReviewTests(unittest.TestCase):
    def test_exact_condition_formats_and_current_view_not_duplicated(self):
        from tests.test_adaptive import AdaptiveTests
        drive=AdaptiveTests().drive
        for cls,raw in [(AdaptiveSolo,'Thought: Inspect.\nRole: A\nAction: click(photo)'),
                        (AdaptivePeer,'Thought: Inspect.\nAction: click(photo)')]:
            rows,prompts=drive(cls,[raw,raw])
            system=prompts[0][0]['content']
            self.assertEqual('exactly three lines' in system,cls is AdaptiveSolo)
            self.assertEqual('exactly two lines' in system,cls is AdaptivePeer)
            self.assertNotIn('Please respond in two lines',system)
            self.assertNotIn('Avoid repeating actions done before',system)
            for messages in prompts:
                self.assertEqual(messages[-1]['content'].count('You got out of an elevator and you are in a hallway.'),1)
            self.assertEqual(rows[0]['upstream']['action_answer'],'click(photo)')

    def test_role_symmetric_memory_protects_evidence_from_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            solo=AdaptiveSolo('game1-3-easy',tmp,None)
            peer=AdaptivePeer('game1-3-easy',tmp,None)
            for agent in (solo,peer):
                agent.setup('test',agent.game)
                agent.notebook={r:{'old room':dict(decision=1,text='old code '+r)} for r in 'AB'}
                agent.received={r:[(2,'important message '+r)] for r in 'AB'}
                agent.feedback_memory={r:{str(i):dict(decision=i+3,text='Error raised during reaction: '+str(i)) for i in range(500)} for r in 'AB'}
            combined=solo.saved_memory('AB')
            self.assertIn('old code A',combined);self.assertIn('old code B',combined)
            for role in 'AB':
                peertext=peer.saved_memory(role)
                self.assertIn(peertext.strip(),combined)
                self.assertEqual(solo.memory_selection[role],peer.memory_selection[role])
                self.assertEqual(solo.memory_selection[role]['feedback']['selected'],0)

    def test_policy_is_independent_of_legacy_frozen_audit(self):
        policy,metadata=load_policy()
        self.assertEqual(sum(v['tier']=='core' for v in policy['games'].values()),6)
        self.assertEqual(policy['games']['game1-4-easy']['tier'],'excluded')
        self.assertEqual(policy['games']['game1-1-easy']['tier'],'core')
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);tasks=[('test',c,g) for c in ('solo','coop') for g in ('game1-1-easy','game1-4-easy')]
            for model,c,g in tasks:
                run=root/f'test-{model}-{c}-{g}'
                frozen=run/'evaluation_inputs';frozen.mkdir(parents=True)
                (frozen/'split_audit.json').write_text(json.dumps(dict(games=[dict(game=g,cohort='main_candidate' if '1-4' in g else 'control_or_review')])))
            report(root,tasks=tasks,prefix='test',model_names={'test':'test'})
            rows=json.loads((root/'cohort-results.json').read_text())
            self.assertTrue(all(r['cohort']==('core' if '1-1' in r['game'] else 'excluded') for r in rows))
            used=json.loads((root/'cohort-policy-used.json').read_text())
            self.assertEqual(used['metadata']['sha256'],metadata['sha256'])

    def test_excluded_nightly_skips_before_slurm_or_model_loading(self):
        from unittest.mock import patch
        from scripts.run_nightly import main,EPISODES
        index=EPISODES.index(('solo','game1-4-easy'))
        stream=io.StringIO()
        with patch('sys.argv',['run_nightly','--model','qwen14','--index',str(index)]),contextlib.redirect_stdout(stream):main()
        self.assertIn('Skipping excluded',stream.getvalue())

    @staticmethod
    def replay_reference_solo(game):
        from scripts.check_protocol import replay_solo
        prompts=[]
        agent,escaped=replay_solo(game,lambda step,messages,agent: prompts.append(messages[-1]['content']))
        return agent,prompts,escaped

    def test_one_time_reveal_survives_in_saved_discoveries(self):
        # game2-2: the cross-room code 1040 appears only in the drawer-opening feedback.
        agent,prompts,escaped=self.replay_reference_solo('game2-2-easy')
        self.assertTrue(escaped)
        opened=[e for e in agent.discoveries['B'] if e['action']=='apply(entrance guard card, drawer)']
        self.assertEqual(len(opened),1)
        self.assertIn('"1040"',opened[0]['text'])
        self.assertNotIn('Action executed successfully',opened[0]['text'])
        later=prompts[opened[0]['decision']+1:]
        self.assertGreater(len(later),20)
        self.assertTrue(all('"1040"' in p for p in later))
        # Tool pickups are not discoveries; the bag already describes held tools.
        self.assertFalse(any(e['action'].startswith('click(entrance guard card') for e in agent.discoveries['B']))

    def test_compact_discovery_keeps_puzzle_text_only(self):
        from scripts.adaptive_escape import compact_discovery
        self.assertEqual(compact_discovery('apply(card, drawer)','Action executed successfully. You have successfully applied card to drawer. The drawer is opened, code "1040"\n'),
                         'The drawer is opened, code "1040"')
        self.assertEqual(compact_discovery('input(17:45, lock)','Action executed successfully. You have given an input 17:45 to lock. It opens\n'),'It opens')
        self.assertEqual(compact_discovery('craft(a, b)','Action executed successfully. You have successfully crafted x. and y together.\nYou get a new item: z. It is put into your bag.'),
                         'You get a new item: z. It is put into your bag.')
        # Unexpected spelling leaves the original sentence in place.
        self.assertIn('You have clicked on Box.',compact_discovery('click(box)','Action executed successfully. You have clicked on Box. Inside: 12'))

    def test_report_counts_escapes_within_budget(self):
        from scripts.run_cohort import budget_metrics
        row=lambda cost:dict(action_cost=1,upstream=dict(tracking=dict(progress=cost),response='ok'),hints_used=0,forced_action=False)
        rows=[row(i) for i in range(10)]
        self.assertTrue(budget_metrics(rows,dict(stop_reason='success'),10)['escaped'])
        self.assertTrue(budget_metrics(rows,dict(stop_reason='success'),50)['escaped'])
        self.assertFalse(budget_metrics(rows,dict(stop_reason='success'),5)['escaped'])
        self.assertFalse(budget_metrics(rows,dict(stop_reason='step_budget'),10)['escaped'])

    def test_preflight_replays_all_eligible_games_and_records_known_gap(self):
        from scripts.check_protocol import check
        result=check()
        self.assertTrue(result['passed'])
        self.assertFalse(result['tokenizer_checked'])
        self.assertEqual(len(result['games']),11)
        self.assertEqual(sum(len(g['skipped_reference_actions']) for g in result['games']),1)
        drawer=next(g for g in result['games'] if g['game']=='game2-2-easy')
        self.assertGreater(drawer['reveal_prompts'],20)

    def test_preflight_counts_real_chat_template_and_reserves_generation(self):
        from scripts.check_protocol import check
        from types import SimpleNamespace
        from unittest.mock import patch
        class Tokenizer:
            def apply_chat_template(self,messages,**kwargs):
                self.kwargs=kwargs
                return 'rendered chat'
            def __call__(self,text,**kwargs):
                assert text=='rendered chat' and kwargs==dict(add_special_tokens=False)
                return SimpleNamespace(input_ids=list(range(7937)))
        tok=Tokenizer()
        policy=dict(games={'game1-1-easy':dict(tier='core')})
        with patch('scripts.check_protocol.load_policy',return_value=(policy,{})):
            over=check(tok,8192)
            fits=check(tok,8193)
        self.assertFalse(over['passed'])
        self.assertTrue(fits['passed'])
        self.assertEqual(tok.kwargs,dict(tokenize=False,add_generation_prompt=True,enable_thinking=False))

    def test_witness_is_costed_and_reproducible(self):
        from scripts.reproduce_billiards_bypass import reproduce
        with tempfile.TemporaryDirectory() as tmp:
            r=reproduce(tmp)
            self.assertEqual((r['steps'],r['progress'],r['gives']),(73,71.05,1))
            self.assertEqual(len((Path(tmp)/'turns.jsonl').read_text().splitlines()),73)
