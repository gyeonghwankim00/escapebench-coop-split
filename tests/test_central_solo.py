import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from scripts.central_solo import CentralSoloAgent
from scripts.coop_original import CoopAgent, gv
from scripts.run_matrix import make_agent, run_episode, resume_key
from scripts.original_escape import Agent


class CentralSoloTests(unittest.TestCase):
    def play(self, cls, actions, game='game1-4-easy'):
        rows=[]; prompts=[]
        def call(step,messages):
            prompts.append(messages)
            return dict(raw='Action: '+actions[step],messages=messages)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            agent=cls(game,tmp,call,max_steps=len(actions))
            iterator=agent.iterate('test',game)
            for _ in actions:
                try: next(iterator)
                except StopIteration: pass
                rows.append(agent.record())
            iterator.close()
        return rows,prompts

    def test_shared_collection_and_cross_role_use_without_give(self):
        actions=['click(toolbox)','click(small key)','click(handle)','apply(small key, hearth)']
        solo,sp=self.play(CentralSoloAgent,actions)
        peer,pp=self.play(CoopAgent,actions)
        self.assertIn('Active role A',sp[0][-1]['content'])
        self.assertIn('kitchen',sp[0][-1]['content'])
        self.assertNotIn("You're in a kitchen",pp[0][-1]['content'])
        self.assertEqual(solo[1]['shared_bag'],['small key'])
        self.assertEqual(solo[1]['bags']['A'],solo[1]['bags']['B'])
        self.assertEqual(peer[1]['bags']['A'],[])
        self.assertIn('small key',sp[2][-1]['content'].split('Shared Bag (usable from A or B):')[1])
        self.assertNotIn('small key',pp[2][-1]['content'])
        self.assertIn('successfully',solo[3]['upstream']['response'])
        # A consumption removes the same tool from both accessible views.
        self.assertEqual(solo[3]['shared_bag'],['handle'])
        self.assertEqual(solo[3]['bags'],dict(A=['handle'],B=['handle']))
        self.assertEqual(sp[2][-1]['content'].count('Shared Bag (usable from A or B):'),1)
        self.assertNotIn('Tools in Bag:',sp[2][-1]['content'])
        self.assertEqual(solo[1]['upstream']['tracking']['tool_collected'],1)

    def test_forced_help_finishes_all_games_without_transfers(self):
        from scripts.run_matrix import ALL_GAMES
        from tests.test_matrix import drive, recorder
        cross_role_uses = 0
        for game in ALL_GAMES:
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                agent=CentralSoloAgent(game,tmp,recorder()[1],max_steps=9000)
                (ok,_),rows=drive(agent,game)
                self.assertTrue(ok)
                self.assertEqual(rows[-1]['upstream']['tracking']['progress'],100)
                self.assertIs(agent.bags['A'],agent.bags['B'])
                collectors={}
                for row in rows:
                    before=set(row['evaluation']['bags_before'][row['role']])
                    after=set(row['shared_bag'])
                    for tool in after-before:
                        collectors[tool]=row['role']
                    answer=row['upstream']['action_answer']
                    if answer.startswith('apply(') and row['upstream']['response'].startswith('Action executed successfully'):
                        tool=answer.split('(',1)[1].split(',')[0].strip()
                        cross_role_uses += tool in collectors and collectors[tool]!=row['role']

                self.assertFalse(any(r['hint'] and r['hint']['kind']=='give' for r in rows))
                self.assertFalse(any(r['upstream']['action_answer'].startswith(('send(','give(')) for r in rows))

        self.assertGreater(cross_role_uses,0)

    def test_history_keeps_ten_actions_per_role(self):
        rows,prompts=self.play(CentralSoloAgent,['click(nonexistent)']*24)
        text=prompts[-1][-1]['content']
        self.assertEqual(text.count('History: [Step '),20)
        self.assertIn('Recent history for role A',text)
        self.assertIn('Recent history for role B',text)

    def test_hidden_tool_is_not_revealed_by_second_view(self):
        _,prompts=self.play(CentralSoloAgent,['click(nonexistent)'],'game1-3-easy')
        text=prompts[0][-1]['content']
        self.assertIn('bottle of wine',text) # visible in B current scene
        self.assertNotIn('<interactable item> hammer',text) # suitcase still closed
        self.assertNotIn('<interactable item> key in the wall',text)

    def test_prompt_is_central_only_with_shared_inventory(self):
        from scripts.central_solo import solo_system_prompt
        text=solo_system_prompt()
        self.assertIn('single controller of BOTH roles',text)
        self.assertIn('ONE shared bag',text)
        self.assertNotIn('give(<applicable tool>)',text)
        self.assertNotIn("cannot see your partner",text)
        self.assertNotIn('playing together with a partner',text)
        self.assertNotIn('send(The note',text)

    def test_send_is_rejected_without_delivery_or_fallback(self):
        rows,prompts=self.play(CentralSoloAgent,[
            'click(toolbox)\nAction: send(Please give me a tool)', 'click(small key)'])
        self.assertTrue(rows[0]['upstream']['action_answer'].startswith('send('))
        self.assertIn('send is unavailable',rows[0]['upstream']['response'])
        self.assertEqual(rows[0]['upstream']['tracking']['key_steps'],0)
        self.assertEqual(rows[1]['inbox'],[])
        self.assertEqual(len(rows),2)  # rejected action still consumes its turn
        self.assertEqual(rows[1]['role'],'B')
        peer,_=self.play(CoopAgent,['send(Need a tool)','click(small key)'])
        self.assertIn('Need a tool',peer[1]['inbox'][0]) # Peer communication retained

    def test_give_rejected_without_losing_or_duplicating_tool(self):
        rows,_=self.play(CentralSoloAgent,['click(toolbox)','click(small key)','give(small key)'])
        self.assertIn('give is unavailable',rows[2]['upstream']['response'])
        self.assertEqual(rows[2]['shared_bag'],['small key'])
        self.assertEqual(rows[2]['inbox'],[])
        self.assertEqual(rows[2]['upstream']['tracking'],rows[1]['upstream']['tracking'])

    def test_shared_solo_is_not_labeled_as_failed_communication(self):
        from scripts.analyze_collaboration import analyze
        rows,_=self.play(CentralSoloAgent,['click(toolbox)','click(small key)'])
        result=analyze('game1-4-easy',rows)
        self.assertFalse(result['communication_stages_applicable'])
        window=result['full_episode']
        self.assertTrue(all(x['stage_candidate']=='unresolved_central_control'
                            for x in window['clues']+window['objects']))
        self.assertTrue(all(h['role']=='shared' for x in window['objects']
                            for holdings in x['holdings'].values() for h in holdings))

    def test_dispatch_and_exact_resume(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertIsInstance(make_agent('solo','game1-4-easy',tmp,None,10),CentralSoloAgent)
            self.assertIsInstance(make_agent('original_solo','game1-4-easy',tmp,None,10),Agent)
            calls=[]
            def request(messages):
                calls.append(messages)
                actions=['click(toolbox)','click(small key)','apply(small key, toolbox)']
                return dict(raw='Action: '+(actions[len(calls)-1] if len(calls)<=3 else 'click(nonexistent)'),messages=messages)
            out=Path(tmp)/'solo/game1-4-easy'
            run_episode('solo','game1-4-easy',out,request,lambda:len(calls)>=4,10)
            self.assertEqual(len(calls),4)
            run_episode('solo','game1-4-easy',out,request,lambda:False,10)
            self.assertEqual(len(calls),10) # saved steps replayed, no duplicate calls
            self.assertEqual(len((out/'turns.jsonl').read_text().splitlines()),10)


if __name__=='__main__':unittest.main()
