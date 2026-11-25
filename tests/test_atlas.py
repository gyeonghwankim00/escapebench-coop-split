import unittest
from scripts.replay_atlas import trace

class AtlasTests(unittest.TestCase):
    def test_solo_and_peer_witnesses_use_real_prompts_and_reach_exit(self):
        for game in ('game1-1-easy','game1-3-easy','game2-4-easy'):
            for condition in ('solo','peer'):
                with self.subTest(game=game,condition=condition):
                    rows=trace(game,condition)
                    self.assertIn('game end',rows[-1]['response'].lower())
                    self.assertEqual(rows[-1]['environment_actions'],sum(r['action_cost'] for r in rows))
                    for r in rows:
                        user=r['messages'][-1]['content']
                        self.assertIn('CURRENT VIEW '+r['role'],user)
                        self.assertEqual(r['action_cost'],int(r['action']!='yield()'))
                        if condition=='peer':
                            partner='B' if r['role']=='A' else 'A'
                            self.assertNotIn('\nCURRENT VIEW '+partner+':',user)
                            if r['action'].startswith('send('):self.assertLessEqual(len(r['action'][5:-1]),300)
                            if r['action'].startswith('give('):
                                tool=r['action'][5:-1]
                                self.assertIn(tool,r['before']['bags'][r['role']])
                                self.assertIn(tool,r['after']['bags'][partner])
                        else:
                            self.assertIn('SHARED BAG:',user)
                            self.assertEqual(r['after']['bags']['A'],r['after']['bags']['B'])
