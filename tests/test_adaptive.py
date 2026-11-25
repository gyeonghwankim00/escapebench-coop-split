import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from scripts.adaptive_escape import AdaptivePeer,AdaptiveSolo,parse_action
from scripts.coop_original import gv
from scripts.run_matrix import run_episode,ALL_GAMES

class AdaptiveTests(unittest.TestCase):
    def drive(self,cls,actions,limit=None):
        prompts=[];rows=[]
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            def call(step,messages):
                prompts.append(messages)
                return dict(raw=actions[step] if step<len(actions) else 'Action: click(photo)',messages=messages)
            agent=cls('game1-3-easy',tmp,call,max_steps=limit or len(actions))
            agent.max_decisions=len(actions)
            it=agent.iterate('test',agent.game)
            while True:
                try:next(it);rows.append(agent.record())
                except StopIteration:break
        return rows,prompts

    def test_messages_are_opaque_and_length_rejected(self):
        text='Action: send(Please use apply(key, door) (after opening))'
        self.assertEqual(parse_action(text),text[8:])
        self.assertEqual(parse_action('Thought: apply(key, door)\nAction: send(code)'), 'send(code)')
        self.assertEqual(parse_action('Action: click(photo)\nAction: give(key)'), 'No action')
        rows,_=self.drive(AdaptivePeer,[text,'Action: send('+('x'*301)+')','Action: yield()'])
        self.assertIn('apply(key, door)',rows[1]['inbox'][0])
        self.assertIn('exceeds',rows[1]['upstream']['response'])
        self.assertEqual(rows[2]['inbox'],[])

    def test_fair_bursts_and_yield_cost(self):
        rows,_=self.drive(AdaptivePeer,['Action: click(photo)']*9)
        self.assertEqual([r['role'] for r in rows],list('AAAABBBBA'))
        rows,_=self.drive(AdaptivePeer,['Action: yield()']*6,limit=2)
        self.assertEqual([r['role'] for r in rows],list('ABABAB'))
        self.assertEqual(rows[-1]['environment_actions'],0)
        self.assertEqual(len(rows),6)

    def test_solo_role_selection_shared_bag_and_persistent_observation(self):
        rows,prompts=self.drive(AdaptiveSolo,[
            'Role: A\nAction: move(Go to left corner close-up)',
            'Role: A\nAction: click(pipe)',
            'Role: B\nAction: click(photo)',
            'Role: A\nAction: yield()'])
        self.assertEqual([r['role'] for r in rows],list('AABA'))
        self.assertIn('Patient 2 John',prompts[1][-1]['content'])
        self.assertIn('pipe',rows[2]['shared_bag'])
        self.assertIn('invalid action',rows[3]['upstream']['response'])
        self.assertEqual(rows[-1]['environment_actions'],4)

    def test_peer_does_not_receive_partner_observation(self):
        _,prompts=self.drive(AdaptivePeer,['Action: yield()','Action: click(photo)'])
        self.assertIn('Patient 2 John',prompts[0][-1]['content'])
        self.assertNotIn('Patient 2 John',prompts[1][-1]['content'])

    def test_resume_replays_role_choice_yield_and_real_bag(self):
        for clscondition in ('solo','coop'):
            with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
                calls=[]
                def request(messages):
                    i=len(calls);calls.append(messages)
                    if clscondition=='solo':raw='Role: B\nAction: click(bottle of wine)'
                    else:raw='Action: yield()' if i%2==0 else 'Action: click(bottle of wine)'
                    return dict(raw=raw,messages=messages)
                p=Path(tmp)/clscondition/'game1-3-easy'
                run_episode(clscondition,'game1-3-easy',p,request,lambda:len(calls)>=3,5)
                run_episode(clscondition,'game1-3-easy',p,request,lambda:False,5)
                self.assertGreaterEqual(len(calls),5)
                self.assertLessEqual(len(calls),10)

    def test_cost_budget_ignores_yield_but_counts_decisions(self):
        from scripts.run_cohort import budget_metrics
        rows,_=self.drive(AdaptivePeer,['Action: yield()','Action: click(photo)','Action: click(photo)'],limit=2)
        metric=budget_metrics(rows,dict(stop_reason='step_budget'),1)
        self.assertEqual(metric['actions_observed'],1)
        self.assertEqual(metric['decisions_observed'],2)

    def test_help_paths_finish_all_games_without_model_inference(self):
        for cls in (AdaptivePeer,AdaptiveSolo):
            for game in ALL_GAMES:
                with self.subTest(cls=cls.__name__,game=game),tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
                    agent=cls(game,tmp,None,max_steps=1000)
                    agent.help_policy='original'
                    def call(step,messages):
                        hint=agent.current_hint
                        return dict(raw='Role: '+hint['role']+'\nAction: '+hint['action'],messages=messages)
                    agent.model_call=call
                    it=agent.iterate('test',game)
                    # Set up manually, then prevent iterator's setup from resetting it.
                    agent.setup('test',game);agent.setup=lambda *a:None
                    done=False
                    for _ in range(400):
                        agent.stuck=True
                        try:next(it)
                        except StopIteration as result:done=result.value[0];break
                        if 'game end' in agent.history[-1]['response'].lower():done=True;break
                    it.close()
                    self.assertTrue(done)
