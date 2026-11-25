"""Dataset invariants and real-engine informed witnesses; no model or GPU."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import yaml
from scripts import split_v4 as v4
from scripts.split_evidence import EvidenceLedger, key

ROOT = Path(__file__).resolve().parents[1]


class SplitV4Tests(unittest.TestCase):
    def test_complete_package_and_reproducible_edits(self):
        self.assertEqual(len(v4.SPLITS), 12)
        self.assertEqual({p.stem for p in (v4.V4/'roles').glob('*.json')}, set(v4.SPLITS))
        for game, edit in v4.EDITS.items():
            scenes, ref, dropped, _, _ = v4.edit_game(game, edit)
            self.assertEqual(yaml.safe_load((v4.V4/'games'/f'{game}.yaml').read_text()), scenes)
            self.assertEqual(v4.read_reference(v4.V4/'reference'/f'key_log_{edit["ref"]}.txt'), ref)
            self.assertEqual(len(dropped), edit['expect_dropped'])
            spec = json.loads((v4.V4/'roles'/f'{game}.json').read_text())
            self.assertEqual(sorted(spec['A'] + spec['B']), sorted(s['name'] for s in scenes))
            self.assertFalse(set(spec['A']) & set(spec['B']))
            self.assertIn(spec['starts']['B'], spec['B'])
            self.assertEqual(json.loads((ROOT/'data/roles'/f'{game}.json').read_text())['version'], 'v3')

    def test_retained_object_states_are_unchanged(self):
        for game, edit in v4.EDITS.items():
            def objects(path):
                return {(s['name'], k, x[k]['name'].strip()): x[k]
                        for s in yaml.safe_load(path.read_text())
                        for field,k in [('items','item'),('tools','tool')] for x in s.get(field) or []}
            old = objects(v4.UPSTREAM/'data'/f'{game}.yaml')
            new = objects(v4.V4/'games'/f'{game}.yaml')
            moved = {(src,n): dst for n,src,dst in edit.get('rewire',{}).get('move_items',[])}
            expected = {(moved.get((scene,n),scene),k,n):obj for (scene,k,n),obj in old.items()
                        if (scene,n) not in edit['objects']}
            self.assertEqual(new, expected, game)

    def test_every_clue_has_live_sources_and_all_links_have_destinations(self):
        clues=json.loads((v4.V4/'clues.json').read_text())['games']
        for game in v4.SPLITS:
            scenes={s['name']:s for s in yaml.safe_load((v4.V4/'games'/f'{game}.yaml').read_text())}
            objects={n:{w[k]['name'].strip() for field,k in [('items','item'),('tools','tool')]
                        for w in scene.get(field) or []} for n,scene in scenes.items()}
            for scene in scenes.values():
                self.assertTrue(set((scene.get('scene_relations') or {}).values()) <= set(scenes),game)
            for clue in clues[game]:
                self.assertIn(clue['target'],objects[clue['target_scene']])
                self.assertTrue(clue['sources'])
                for source in clue['sources']:
                    self.assertTrue(source['evidence'])
                    self.assertTrue(all(str(e).strip() for e in source['evidence']))
                    self.assertIn(source['object'],objects[source['scene']] | {'@'+source['scene']})

    def test_live_witnesses_have_no_missing_steps_or_illegal_actions(self):
        with v4.overlay():
            for game in v4.SPLITS:
                if game in v4.EXCLUDED:
                    continue
                for solo in (True,False):
                    with self.subTest(game=game,solo=solo):
                        r,_ = v4.informed_replay(game,solo)
                        self.assertTrue(r['escaped'])
                        self.assertEqual(r['invalid_actions'],0)
                        self.assertEqual(r['remaining_reference_actions'],0)
                        self.assertFalse(r['skipped_reference_actions'])
                        if game not in v4.TRANSIT_EXCEPTIONS:
                            self.assertFalse(r['partner_area_moves'])
                        inputs = [s for s in v4.sm.reference(game) if s['action_answer'].startswith('input(')]
                        self.assertEqual(len(r['input_evidence']),len(inputs))

    def test_one_time_feedback_is_actually_sent_before_input(self):
        with v4.overlay():
            r,route=v4.peer_replay('game2-2-easy')
        sent=next(x for x in route if x['action'].startswith('send(') and '1040' in x['action'])
        used=next(x for x in route if x['action']=='input(1040, wall safe)')
        self.assertEqual(sent['role'],'B'); self.assertEqual(used['role'],'A')
        self.assertLess(sent['step'],used['step'])
        check=next(c for c in r['input_evidence'] if c['action']==used['action'])
        self.assertEqual(check['sources'][0]['via'],'message')
        self.assertEqual(check['sources'][0]['sender'],'B')

    def test_missing_upstream_clue_is_rejected(self):
        with v4.overlay(), self.assertRaisesRegex(AssertionError, 'evidence unavailable'):
            v4.peer_replay('game1-4-easy')

    def test_saved_verification_covers_inclusions_and_exclusion(self):
        report=json.loads((v4.V4/'verification.json').read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['eligible_games']),11)
        self.assertEqual(set(report['excluded']), {'game1-4-easy'})
        for path, digest in {**report['dataset_sha256'], **report['code_sha256']}.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        for game,r in report['games'].items():
            if not r['eligible']:
                self.assertFalse(r['evidence_closure']['full']['escape'])
                continue
            for f in r['files'].values():
                self.assertEqual(hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest(),f['sha256'])
            self.assertFalse(r['dead_steps']['observed_clues'])
            self.assertTrue(r['evidence_closure']['full']['escape'])


class EvidenceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.source=dict(scene='office',object='drawer',evidence=['1040'])
        self.clue=dict(target_scene='hall',target='safe',answer='1040',sources=[self.source])
        self.ledger=EvidenceLedger([self.clue])

    def test_open_drawer_name_and_oracle_answer_are_not_evidence(self):
        l=self.ledger;l.prompt='an opened drawer'
        l.remember('B',self.source,'an opened drawer',0,'visible_object')
        self.assertFalse(l.known['B'])
        with self.assertRaises(AssertionError):l.require('A','input(1040, safe)','hall',1)
        with self.assertRaises(AssertionError):l.message('B','A',self.source,1)

    def test_feedback_requires_observable_text(self):
        l=self.ledger;l.prompt='nothing here'
        l.remember('B',self.source,'1040',0,'action_feedback')
        self.assertFalse(l.known['B'])
        l.prompt='the paper says 1040';l.remember('B',self.source,'the paper says 1040',0,'action_feedback')
        self.assertIn(key(self.source),l.known['B'])
        with self.assertRaises(AssertionError):l.require('A','input(1040, safe)','hall',1)

    def test_full_long_message_with_parentheses_requires_successful_delivery(self):
        l=self.ledger;text='1040 (a clue). ' + 'Additional source text. '*30
        l.prompt=text.lower();l.remember('B',self.source,text,0,'action_feedback')
        parts=[]
        while key(self.source) not in l.known['A']:
            l.prompt=text.lower()
            action=l.message('B','A',self.source,1)
            self.assertLessEqual(len(action[5:-1]),300)
            self.assertNotIn(key(self.source),l.known['A'])
            parts.append(action[5:-1])
            fake=SimpleNamespace(history=[dict(action_answer=action,response='Action executed successfully. Your message has been delivered to your partner.')])
            l.observe(fake,[dict(content='\n'.join(parts))],[],2)
        self.assertEqual(''.join(parts),text.strip())
        l.require('A','input(1040, safe)','hall',3)

    def test_unknown_inputs_fail_closed(self):
        with self.assertRaisesRegex(AssertionError,'Unannotated input'):
            self.ledger.require('A','input(123, safe)','hall',0)

    def test_failed_send_does_not_establish_recipient_knowledge(self):
        l=self.ledger;l.prompt='the code is 1040'
        l.remember('B',self.source,'the code is 1040',0,'action_feedback')
        action=l.message('B','A',self.source,1)
        fake=SimpleNamespace(history=[dict(action_answer=action,response='Error: not delivered')])
        with self.assertRaises(AssertionError):l.observe(fake,[dict(content='')],[],2)
        self.assertNotIn(key(self.source),l.known['A'])


if __name__=='__main__':unittest.main()
