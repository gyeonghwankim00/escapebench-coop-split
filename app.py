"""Local browser interface for the two-room EscapeBench pilot.

Run: python3 app.py
The server binds to loopback and stores active games in memory only.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlparse

from scripts.coop_escape import World

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
DATA = ROOT / 'data' / 'pilot'
GAMES = {
    entry['id']: {
        'number': entry['id'][:2], 'title': entry['title'],
        'subtitle': entry['source'],
        'description': f"원본 객체 {entry['entities']}개와 핵심 행동 {entry['source_key_actions']}개를 보존한 두 방 협업 문제입니다.",
        'tags': ['원본 전체 분할', '정보·도구 전달'],
    }
    for entry in json.loads((DATA/'manifest.json').read_text())['instances']
}

ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
MAX_BODY = 8192


@dataclass
class GameSession:
    game_id: str
    world: World
    keys: dict[str, str]
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_views: dict = field(default_factory=dict)
    generation: int = 0

    def view(self, actor):
        """Record new observations only when they actually change, not on every poll."""
        view = self.world._observation(actor)
        if view != self.last_views.get(actor):
            self.world.observe(actor)
            self.last_views[actor] = deepcopy(view)
        return view

    def timeline(self, actor):
        entries = []
        for event in self.world.events:
            if event['type'] != 'action':
                continue
            action = event['action']
            if event['actor'] == actor:
                entries.append({'turn': event['turn'], 'kind': 'own',
                                'action': action, 'feedback': event['feedback'],
                                'valid': event['valid'], 'effect': event['effect']})
            elif action.get('type') == 'send' and event['valid']:
                entries.append({'turn': event['turn'], 'kind': 'message',
                                'text': action['message']})
            elif action.get('type') == 'pass' and event['valid']:
                entries.append({'turn': event['turn'], 'kind': 'received',
                                'tool': action['tool']})
        return entries

    def state(self, actor):
        return {'game': {'id': self.game_id, **GAMES[self.game_id]},
                'observation': self.view(actor), 'timeline': self.timeline(actor),
                'turn': self.world.turn, 'generation': self.generation}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.sessions: dict[str, GameSession] = {}
        self.sessions_lock = threading.RLock()


class Handler(BaseHTTPRequestHandler):
    server: AppServer

    def log_message(self, format, *args):
        # URLs contain role credentials; do not print them to the terminal.
        pass

    def reply(self, status, value, content_type='application/json; charset=utf-8'):
        data = (json.dumps(value, ensure_ascii=False).encode('utf-8')
                if content_type.startswith('application/json') else value)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def fail(self, status, message):
        self.reply(status, {'error': message})

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > MAX_BODY:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def authorized(self, session_id, actor, key):
        if not isinstance(session_id, str):
            return None
        with self.server.sessions_lock:
            session = self.server.sessions.get(session_id)
        if (session is None or actor not in ('A', 'B') or not isinstance(key, str)
                or not secrets.compare_digest(session.keys[actor], key)):
            return None
        return session

    def same_origin(self):
        origin = self.headers.get('Origin')
        if not origin:
            return True  # command-line clients and local tests
        parsed = urlparse(origin)
        return (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')
                and parsed.port == self.server.server_port)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ASSETS:
            filename, content_type = ASSETS[parsed.path]
            return self.reply(HTTPStatus.OK, (WEB / filename).read_bytes(), content_type)
        if parsed.path == '/api/games':
            return self.reply(HTTPStatus.OK, [{'id': k, **v} for k, v in GAMES.items()])
        if parsed.path == '/api/state':
            query = parse_qs(parsed.query)
            session = self.authorized(query.get('session', [''])[0],
                                      query.get('actor', [''])[0], query.get('key', [''])[0])
            if not session:
                return self.fail(HTTPStatus.FORBIDDEN, '게임을 찾을 수 없거나 접근 권한이 없습니다.')
            actor = query['actor'][0]
            with session.lock:
                return self.reply(HTTPStatus.OK, session.state(actor))
        self.fail(HTTPStatus.NOT_FOUND, '요청한 페이지를 찾을 수 없습니다.')

    def do_POST(self):
        if not self.same_origin():
            return self.fail(HTTPStatus.FORBIDDEN, '허용되지 않은 요청입니다.')
        body = self.body()
        if body is None:
            return self.fail(HTTPStatus.BAD_REQUEST, '요청 형식이 올바르지 않습니다.')
        path = urlparse(self.path).path
        if path == '/api/session':
            game_id = body.get('game')
            if not isinstance(game_id, str) or game_id not in GAMES:
                return self.fail(HTTPStatus.BAD_REQUEST, '문제를 선택해 주세요.')
            session_id = secrets.token_urlsafe(16)
            keys = {actor: secrets.token_urlsafe(24) for actor in ('A', 'B')}
            session = GameSession(game_id, World(DATA / game_id / 'environment.json'), keys)
            with self.server.sessions_lock:
                self.server.sessions[session_id] = session
            return self.reply(HTTPStatus.CREATED, {'session': session_id, 'keys': keys})
        if path in ('/api/action', '/api/reset', '/api/log'):
            actor = body.get('actor')
            session = self.authorized(body.get('session'), actor, body.get('key'))
            if not session:
                return self.fail(HTTPStatus.FORBIDDEN, '게임을 찾을 수 없거나 접근 권한이 없습니다.')
            with session.lock:
                if path == '/api/action':
                    action = body.get('action')
                    if not isinstance(action, dict):
                        return self.fail(HTTPStatus.BAD_REQUEST, '행동을 선택해 주세요.')
                    result = session.world.step(actor, action)
                    return self.reply(HTTPStatus.OK, {'result': result, **session.state(actor)})
                if path == '/api/reset':
                    session.world = World(DATA / session.game_id / 'environment.json')
                    session.last_views.clear()
                    session.generation += 1
                    return self.reply(HTTPStatus.OK, session.state(actor))
                # Only the player's own observations/actions and shared transfers.
                own = [e for e in session.world.events if e.get('actor') == actor]
                safe_own = [{k: v for k, v in event.items() if k != 'exposed_clues'} for event in own]
                return self.reply(HTTPStatus.OK, {'game': session.game_id, 'actor': actor,
                    'events': safe_own, 'shared_timeline': [x for x in session.timeline(actor)
                                                             if x['kind'] != 'own']})
        self.fail(HTTPStatus.NOT_FOUND, '요청한 페이지를 찾을 수 없습니다.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = AppServer(('127.0.0.1', args.port))
    print(f'\n  Escape Room Lab  →  http://127.0.0.1:{server.server_port}\n'
          '  종료하려면 Ctrl+C를 누르세요. 진행 상황은 서버가 켜진 동안 유지됩니다.\n', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
