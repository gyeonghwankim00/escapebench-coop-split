"""HTTP integration tests for two independent room perspectives."""
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app import AppServer, DATA, GAMES


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = AppServer(('127.0.0.1', 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, path, data=None):
        raw = json.dumps(data).encode() if data is not None else None
        req = Request(self.base + path, data=raw,
                      headers={'Content-Type': 'application/json'} if raw else {})
        with urlopen(req, timeout=5) as response:
            content = response.read()
            return json.loads(content) if 'application/json' in response.headers['Content-Type'] else content

    def create(self, game='01_mirror_workshop'):
        session = self.request('/api/session', {'game': game})
        return {actor: {'session': session['session'], 'actor': actor, 'key': session['keys'][actor]}
                for actor in ('A', 'B')}

    def state(self, creds):
        return self.request('/api/state?' + urlencode(creds))

    def act(self, creds, **action):
        return self.request('/api/action', {**creds, 'action': action})

    def test_static_assets_and_safe_game_catalog(self):
        self.assertIn(b'Escape Room Lab', self.request('/'))
        self.assertIn(b'function render', self.request('/app.js'))
        self.assertEqual(len(self.request('/api/games')), 8)
        with self.assertRaises(HTTPError) as denied:
            self.request('/data/pilot/01_mirror_workshop/environment.json')
        self.assertEqual(denied.exception.code, 404)

    def test_roles_are_isolated_and_communicate(self):
        roles = self.create()
        a, b = roles['A'], roles['B']
        initial = self.state(a)
        self.assertEqual(initial['observation']['room'], 'A')
        self.assertNotIn('dining table close-up', json.dumps(initial))
        self.assertNotIn('accepted_input', json.dumps(initial))
        with self.assertRaises(HTTPError) as denied:
            self.state({**a, 'actor': 'B'})
        self.assertEqual(denied.exception.code, 403)
        self.act(b, type='move', target='dining table close-up')
        self.act(b, type='click', target='shard_1')
        before = self.state(a)
        self.assertEqual(before['observation']['inventory'], [])
        self.assertNotIn('shard_1', json.dumps(before))
        self.act(b, type='pass', tool='shard_1')
        self.act(b, type='send', message='A fragment is coming!')
        after = self.state(a)
        self.assertEqual(after['observation']['inventory'][0]['name'], 'shard_1')
        self.assertEqual(after['observation']['messages'][0]['text'], 'A fragment is coming!')
        self.assertNotIn('dining table close-up', json.dumps(after))
        self.assertEqual([item['kind'] for item in after['timeline']], ['received', 'message'])
        log = self.request('/api/log', a)
        self.assertNotIn('exposed_clues', json.dumps(log))
        self.assertNotIn('dining table close-up', json.dumps(log))

    def test_reset_updates_both_roles_and_generation(self):
        roles = self.create()
        self.act(roles['A'], type='move', target='bedroom')
        after = self.request('/api/reset', roles['B'])
        self.assertEqual(after['generation'], 1)
        self.assertEqual(after['turn'], 0)
        a_view = self.state(roles['A'])
        self.assertEqual(a_view['generation'], 1)
        self.assertEqual(a_view['observation']['area'], 'room A')
        self.assertEqual(a_view['timeline'], [])

    def test_complete_cooperative_witness_for_all_games_through_http(self):
        for game_id in GAMES:
            with self.subTest(game=game_id):
                roles = self.create(game_id)
                rows = json.loads((DATA/game_id/'reference.json').read_text())
                for index, row in enumerate(rows, 1):
                    response = self.request('/api/action', {**roles[row['actor']], 'action': row['action']})
                    self.assertTrue(response['result']['valid'], (game_id, index, row, response))
                    self.assertTrue(response['result']['effect'], (game_id, index, row, response))
                self.assertTrue(self.state(roles['A'])['observation']['team_success'])
                self.assertTrue(self.state(roles['B'])['observation']['team_success'])


if __name__ == '__main__':
    unittest.main()
